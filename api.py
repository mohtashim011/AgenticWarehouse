"""
HTTP API
========
Every route the system exposes, registered on the router in :mod:`core.router`.

Two rules run through all of it:

* **Routes declare a capability, not a role.** ``needs="staff.create"`` says what
  the route is for; which roles hold it is decided in one place
  (:data:`store.users.CAPABILITIES`) rather than scattered across handlers.
* **Agents decide, routes execute.** A handler gathers input, asks the relevant
  agent, and applies the answer. The decision and its reasoning go back to the
  browser so the interface can show *why*, not just *what*.
"""

import csv
import io
import json

import db
from agents import orchestrator, assistant_agent, registry as agent_registry
from agents import roster as agent_roster
from core import barcode, qrcode
from core.router import Router, Request, Response, HttpError
from ml import registry as ml_registry, dataset as ml_dataset
from store import users, settings
from store import cameras as camera_store

router = Router()

SESSION_COOKIE = "aw_session"

# Routes anyone may call, signed in or not.
PUBLIC = {"/api/auth/login", "/api/auth/session", "/api/health"}


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------
@router.use
def authenticate(request, options):
    """Attach the signed-in user, then enforce the route's capability."""
    token = request.cookie(SESSION_COOKIE)
    user, session = users.session_user(token)
    request.user = user
    request.session = session

    if request.path in PUBLIC or options.get("public"):
        return None

    if user is None:
        return Response.error("Please sign in to continue.", 401, code="unauthenticated")

    needed = options.get("needs")
    if needed:
        decision = agent_registry.get("Authorisation Agent").run(
            {"user": user, "capability": needed})
        if not decision.data.get("allowed"):
            if user.get("must_change_pw"):
                return Response.error(
                    "Choose a new password before using the system. The password "
                    "this account was issued is known to whoever issued it.",
                    403, code="password_change_required")
            return Response.error(
                decision.data.get("message", "Not permitted."), 403,
                code="forbidden", decision=decision.to_dict())
    return None


def _agent(name):
    agent = agent_registry.get(name)
    if agent is None:
        raise HttpError(503, "The %s is not available." % name)
    return agent


def _ok(message="", **extra):
    payload = {"ok": True, "message": message}
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# Health and session
# ---------------------------------------------------------------------------
@router.get("/api/health", public=True)
def health(request):
    return {"ok": True, "service": "agentic-warehouse", "version": "2.0"}


@router.post("/api/auth/login", public=True)
def login(request):
    body = request.json()
    decision = _agent("Authentication Agent").run({
        "username": body.get("username", ""),
        "password": body.get("password", ""),
        "ip": request.client_ip,
        "user_agent": request.user_agent,
    })

    if not decision.data.get("granted"):
        return Response.json(
            {"ok": False, "message": decision.data.get("message"),
             "decision": decision.to_dict()},
            status=401)

    user = decision.data["user"]
    token = users.create_session(user["id"], request.client_ip, request.user_agent)
    response = Response.json(_ok(
        "Signed in.",
        user=user,
        risk=decision.data.get("risk", 0),
        signals=decision.data.get("signals", []),
        decision=decision.to_dict(),
    ))
    # HttpOnly keeps the token out of reach of any script on the page, which is
    # the whole point of storing it in a cookie rather than localStorage.
    # Secure is set whenever the request itself arrived over TLS. Setting it
    # unconditionally would break the plain-HTTP localhost mode, where the
    # browser would refuse to store the cookie at all.
    secure = "; Secure" if request.is_secure else ""
    response.headers["Set-Cookie"] = (
        "%s=%s; Path=/; HttpOnly; SameSite=Lax%s; Max-Age=%d"
        % (SESSION_COOKIE, token, secure, users.SESSION_HOURS * 3600))
    return response


@router.post("/api/auth/logout")
def logout(request):
    users.revoke_session(request.cookie(SESSION_COOKIE))
    response = Response.json(_ok("Signed out."))
    response.headers["Set-Cookie"] = "%s=; Path=/; HttpOnly; Max-Age=0" % SESSION_COOKIE
    return response


@router.get("/api/auth/session", public=True)
def whoami(request):
    """Who is signed in. Public so the app can ask before showing a login form."""
    if request.user is None:
        return {"ok": True, "authenticated": False, "user": None}
    return {
        "ok": True,
        "authenticated": True,
        "user": request.user,
        "session": request.session,
        "roles": [{"key": r, "label": users.ROLE_LABELS[r],
                   "description": users.ROLE_DESCRIPTIONS[r]} for r in users.ROLES],
    }


@router.post("/api/auth/password")
def change_password(request):
    body = request.json()
    decision = _agent("Staff Agent").run({
        "action": "reset_password", "actor": request.user,
        "target": request.user, "payload": body,
    })
    if not decision.data.get("allowed", True):
        raise HttpError(403, decision.data["message"])
    ok, message = users.change_own_password(
        request.user["id"], body.get("current_password", ""), body.get("new_password", ""))
    if not ok:
        raise HttpError(400, message)
    return _ok(message, decision=decision.to_dict())


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------
@router.post("/api/scan", needs="scan")
def scan(request):
    body = request.json()
    result = orchestrator.process_scan(
        body.get("code", ""),
        (body.get("mode") or "IN").upper(),
        body.get("format", "unknown"),
        actor=request.user,
    )
    result["state"] = _state_bundle()
    return result


@router.post("/api/scan/recover", needs="scan")
def scan_recover(request):
    """Ask the Recovery Agent what a failed read might have been."""
    body = request.json()
    return orchestrator.recover(body.get("code", ""), body.get("reason", ""))


@router.post("/api/scan/decode-image", needs="scan")
def scan_decode_image(request):
    """Decode a 1-D barcode from a band of grayscale pixels sent by the browser.

    This exists because the browser decoder is handed a downscaled frame. The
    scanner library sizes its decode canvas from the CSS width of the element
    rather than the camera's resolution, so a 1920-wide frame reaches it at
    roughly 570 pixels -- under two pixels per module for an EAN-13, where the
    measured floor is about four. A QR survives that downscale and a barcode
    cannot, which is exactly the failure this route answers.

    The browser sends the frame at FULL camera resolution as one byte per pixel,
    row-major, with the geometry in the query string. Raw rather than JSON or
    base64: a 1920x160 band is 307 KB raw and 410 KB base64, and the browser is
    already an image decoder so there is nothing to gain by re-encoding it.

    Deliberately separate from `/api/scan`: this only *reads* a code. What to do
    with it stays with the orchestrator and its agents, so a decoded barcode
    goes through exactly the same pipeline, duplicate guard and audit trail as
    one read in the browser.
    """
    from core import barcode_decode

    width = request.int_arg("w", 0)
    height = request.int_arg("h", 0)
    pixels = request.raw_body or b""

    if not pixels:
        raise HttpError(400, "No image data was received. The frame may have "
                             "been larger than the server accepts.")
    if width <= 0 or height <= 0:
        raise HttpError(400, "Give the band geometry as ?w=<width>&h=<height>.")
    if width * height > len(pixels):
        raise HttpError(400, "The band is smaller than the stated width and height.")

    result = barcode_decode.decode_band(pixels, width, height)
    return {
        "ok": True,
        "decoded": bool(result.get("code")),
        "code": result.get("code"),
        "symbology": result.get("symbology"),
        "rows": result.get("rows"),
        "agreeing_lines": result.get("agreeing_lines"),
        "module_pixels": result.get("module_pixels"),
        "near_miss": result.get("near_miss"),
        "reason": result.get("reason"),
        "engine": "core.barcode_decode",
    }


@router.post("/api/vision/failover", needs="scan")
def vision_failover(request):
    """Ask the Vision Agent what to do about a misbehaving camera.

    The browser is the only thing that can see a camera, so it reports the
    symptom; the decision, and the explanation the operator reads, belong to an
    agent like every other judgement in this system.
    """
    body = request.json()
    decision = _agent("Vision Agent").run({
        "symptom": body.get("symptom", "healthy"),
        "cameras": body.get("cameras") or [],
        "active_index": body.get("active_index", 0),
        "tried": body.get("tried") or [],
        "idle_seconds": body.get("idle_seconds", 0),
        "decodes": body.get("decodes", 0),
        "patience": settings.get("camera_failover_seconds"),
    })
    return {
        "ok": True,
        "action": decision.data.get("action"),
        "target": decision.data.get("target"),
        "target_label": decision.data.get("target_label"),
        "advice": decision.data.get("advice"),
        "reasons": decision.rationale,
        "decision": decision.to_dict(),
    }


@router.post("/api/adjust", needs="inventory.adjust")
def adjust(request):
    body = request.json()
    ok, message, _ = db.adjust_stock(
        body.get("productno", ""), body.get("batchno", ""), body.get("qty", 0),
        actor=request.user)
    if not ok:
        raise HttpError(400, message)
    return _ok(message, **_state_bundle())


@router.post("/api/undo", needs="inventory.undo")
def undo(request):
    # `log_id` names the scan to reverse. Without it the newest reversible scan
    # is used, which is right for the "Undo last scan" button but wrong when
    # someone has opened an earlier scan and pressed Undo there.
    ok, message, _ = db.undo_last(request.json().get("log_id"), actor=request.user)
    if not ok:
        raise HttpError(400, message)
    return _ok(message, **_state_bundle())


@router.post("/api/rename", needs="catalog.manage")
def rename(request):
    body = request.json()
    ok, message = db.rename_product(body.get("productno", ""), body.get("name", ""),
                                    actor=request.user)
    if not ok:
        raise HttpError(400, message)
    ml_registry.invalidate()
    return _ok(message, **_state_bundle())


@router.post("/api/link", needs="catalog.manage")
def link(request):
    body = request.json()
    ok, message = db.link_code(body.get("code", ""), body.get("productno", ""),
                               actor=request.user)
    if not ok:
        raise HttpError(400, message)
    return _ok(message, **_state_bundle())


@router.post("/api/unlink", needs="catalog.manage")
def unlink(request):
    ok, message = db.unlink_code(request.json().get("code", ""))
    if not ok:
        raise HttpError(400, message)
    return _ok(message, **_state_bundle())


@router.get("/api/codes", needs="inventory.read")
def codes(request):
    """The code registry: every product and every code that reaches it.

    This is what guarantees a QR and a printed barcode for the same product land
    on the same stock record, in both directions.
    """
    return {"ok": True, "products": db.all_product_codes(), "links": db.list_aliases()}


# ---------------------------------------------------------------------------
# Inventory and state
# ---------------------------------------------------------------------------
def _state_bundle():
    return {
        "stats": db.stats(),
        "inventory": db.inventory_summary(),
        "low_stock": db.low_stock(),
        "logs": db.recent_logs(20),
        "undoable": db.last_undoable(),
    }


@router.get("/api/state", needs="inventory.read")
def state(request):
    bundle = _state_bundle()
    bundle.update({
        "ok": True,
        "charts": {
            "categories": db.category_totals(),
            "activity": db.activity_daily(7),
        },
        "model": ml_registry.summary(),
        "agents": agent_registry.summary(),
    })
    return bundle


@router.get("/api/logs", needs="inventory.read")
def logs(request):
    return {"ok": True, "logs": db.search_logs(
        request.arg("q"), request.arg("action"), request.int_arg("limit", 100))}


@router.post("/api/reorder", needs="reorder.manage")
def reorder(request):
    body = request.json()
    ok, message = db.set_min_qty(body.get("product", ""), body.get("min_qty", 0))
    if not ok:
        raise HttpError(400, message)
    return _ok(message, **_state_bundle())


@router.get("/api/procurement", needs="reports.read")
def procurement(request):
    decision = _agent("Procurement Agent").run({
        "lead_time_days": settings.get("lead_time_days"),
        "product": request.arg("product") or None,
    })
    return {"ok": True, "decision": decision.to_dict(),
            "proposals": decision.data.get("proposals", [])}


@router.get("/api/audit", needs="audit.read")
def audit(request):
    decision = _agent("Audit Agent").run({})
    return {"ok": True, "decision": decision.to_dict(),
            "findings": decision.data.get("findings", [])}


# ---------------------------------------------------------------------------
# Products (full CRUD)
# ---------------------------------------------------------------------------
@router.get("/api/products", needs="inventory.read")
def products(request):
    return {"ok": True, "products": db.list_products()}


@router.get("/api/products/<str:productno>", needs="inventory.read")
def product_get(request, productno):
    detail = db.product_detail(productno)
    if detail is None:
        raise HttpError(404, "No product with number %s." % productno)

    # The detail page shows what the agents make of this product, not just its
    # numbers: a forecast and a reorder proposal are the two questions anyone
    # opening it is about to ask.
    forecast = _agent("Forecast Agent").run({"name": detail["name"]})
    procurement = _agent("Procurement Agent").run({
        "lead_time_days": settings.get("lead_time_days"),
        "product": detail["name"],
    })
    detail["forecast"] = forecast.to_dict()
    detail["procurement"] = next(
        (p for p in procurement.data.get("proposals", []) if p["name"] == detail["name"]),
        None)
    return {"ok": True, "product": detail, "categories": db.categories_list()}


@router.post("/api/products", needs="catalog.manage")
def product_create(request):
    body = request.json()
    ok, message, detail = db.create_product(
        name=body.get("name", ""), productno=body.get("productno", ""),
        batchno=body.get("batchno", ""), qty=body.get("qty", 0),
        category=body.get("category"), min_qty=body.get("min_qty", 0),
        actor=request.user)
    if not ok:
        raise HttpError(400, message)
    ml_registry.invalidate()
    return _ok(message, product=detail, **_state_bundle())


@router.put("/api/products/<str:productno>", needs="catalog.manage")
def product_update(request, productno):
    body = request.json()
    ok, message = db.update_product(
        productno,
        name=body.get("name"), category=body.get("category"),
        min_qty=body.get("min_qty"), actor=request.user)
    if not ok:
        raise HttpError(400, message)
    ml_registry.invalidate()
    return _ok(message, product=db.product_detail(productno), **_state_bundle())


@router.delete("/api/products/<str:productno>", needs="catalog.manage")
def product_delete(request, productno):
    ok, message = db.delete_product(productno, force=request.arg("force") == "1",
                                    actor=request.user)
    if not ok:
        raise HttpError(400, message)
    return _ok(message, **_state_bundle())


@router.post("/api/products/<str:productno>/batches", needs="inventory.adjust")
def batch_create(request, productno):
    body = request.json()
    ok, message = db.add_batch(productno, body.get("batchno", ""), body.get("qty", 0),
                               actor=request.user)
    if not ok:
        raise HttpError(400, message)
    return _ok(message, product=db.product_detail(productno), **_state_bundle())


@router.delete("/api/products/<str:productno>/batches/<str:batchno>",
               needs="inventory.adjust")
def batch_delete(request, productno, batchno):
    # An empty batch is a legitimate key but cannot travel in a URL path, so the
    # UI sends this sentinel for it.
    ok, message = db.delete_batch(productno, "" if batchno == "-" else batchno,
                                  actor=request.user)
    if not ok:
        raise HttpError(400, message)
    return _ok(message, product=db.product_detail(productno), **_state_bundle())


# ---------------------------------------------------------------------------
# Printable labels and the phone connect code
# ---------------------------------------------------------------------------
def _svg(body, filename=None):
    headers = {"Cache-Control": "no-cache"}
    if filename:
        headers["Content-Disposition"] = 'inline; filename="%s"' % filename
    return Response(body.encode("utf-8"), 200, "image/svg+xml; charset=utf-8", headers)


@router.get("/api/products/<str:productno>/qr.svg", needs="inventory.read")
def product_qr(request, productno):
    """The QR a label carries: the payload the Scanner Agent parses."""
    detail = db.product_detail(productno)
    if detail is None:
        raise HttpError(404, "No product with number %s." % productno)
    payload = "%s,%s,%s" % (
        detail["name"], request.arg("batch") or
        (detail["batches"][0]["batchno"] if detail["batches"] else ""), productno)
    return _svg(qrcode.to_svg(payload, level="M", module=request.int_arg("module", 4)),
                "qr-%s.svg" % productno)


@router.get("/api/products/<str:productno>/barcode.svg", needs="inventory.read")
def product_barcode(request, productno):
    """The 1-D barcode for the same product, when the number is a retail code."""
    if not barcode.can_render(productno):
        raise HttpError(
            400, "%s is not a retail barcode number, so it cannot be drawn as "
                 "EAN-13. Its QR code still works." % productno)
    return _svg(barcode.to_svg(productno, module=request.int_arg("module", 2)),
                "barcode-%s.svg" % productno)


@router.get("/api/products/<str:productno>/label", needs="inventory.read")
def product_label(request, productno):
    """A printable label carrying both symbologies for one product.

    This is the bidirectional claim made checkable: the QR holds
    ``name,batch,productno`` and the barcode holds the product number, and
    scanning either one lands on this same record.
    """
    detail = db.product_detail(productno)
    if detail is None:
        raise HttpError(404, "No product with number %s." % productno)
    batch = request.arg("batch") or (
        detail["batches"][0]["batchno"] if detail["batches"] else "")
    payload = "%s,%s,%s" % (detail["name"], batch, productno)

    qr_svg = qrcode.to_svg(payload, level="M", module=4)
    if barcode.can_render(productno):
        bar_svg = barcode.to_svg(productno, module=2, height=54)
        bar_note = ""
    else:
        bar_svg = ""
        bar_note = ("This product number is not a retail barcode, so only the QR "
                    "code can be printed.")

    html = _LABEL_TEMPLATE % {
        "name": _escape(detail["name"]),
        "productno": _escape(productno),
        "batch": _escape(batch or "no batch"),
        "category": _escape(detail["category"]),
        "payload": _escape(payload),
        "qr": qr_svg,
        "barcode": bar_svg,
        "note": _escape(bar_note),
    }
    return Response(html.encode("utf-8"), 200, "text/html; charset=utf-8")


@router.get("/api/connect.svg", public=True)
def connect_qr(request):
    """A QR of this server's address, for a phone to scan and open."""
    url = request.arg("url") or ""
    if not url:
        raise HttpError(400, "Give the address to encode as ?url=")
    return _svg(qrcode.to_svg(url, level="M", module=5))


def _escape(text):
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


_LABEL_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Label - %(name)s</title>
<style>
  body { font: 13px ui-sans-serif, system-ui, "Segoe UI", Roboto, sans-serif;
         margin: 0; padding: 24px; background: #f4f4f2; color: #111; }
  .label { width: 340px; margin: 0 auto; padding: 16px; background: #fff;
           border: 1px solid #ccc; border-radius: 6px; }
  h1 { font-size: 16px; margin: 0 0 2px; }
  .meta { color: #555; font-size: 12px; margin-bottom: 12px; }
  .codes { display: flex; gap: 14px; align-items: center; }
  .payload { margin-top: 12px; padding-top: 10px; border-top: 1px dashed #ccc;
             font-family: monospace; font-size: 11px; color: #444;
             word-break: break-all; }
  .note { margin-top: 8px; font-size: 11px; color: #a15c00; }
  .actions { text-align: center; margin-top: 18px; }
  button { font: inherit; padding: 7px 16px; border: 1px solid #bbb;
           border-radius: 5px; background: #fff; cursor: pointer; }
  @media print { body { background: #fff; padding: 0; }
                 .actions { display: none; } .label { border: none; } }
</style></head>
<body>
  <div class="label">
    <h1>%(name)s</h1>
    <div class="meta">%(category)s &middot; batch %(batch)s &middot; %(productno)s</div>
    <div class="codes">%(qr)s%(barcode)s</div>
    <div class="payload">QR payload: %(payload)s</div>
    <div class="note">%(note)s</div>
  </div>
  <div class="actions"><button onclick="window.print()">Print</button></div>
</body></html>"""


# ---------------------------------------------------------------------------
# Daily reporting
# ---------------------------------------------------------------------------
@router.get("/api/reports/daily", needs="reports.read")
def report_daily(request):
    return {"ok": True, "report": db.daily_report(
        days=request.int_arg("days", 30),
        date_from=request.arg("from") or None,
        date_to=request.arg("to") or None,
    )}


@router.get("/api/export/daily.csv", needs="reports.read")
def export_daily(request):
    report = db.daily_report(
        days=request.int_arg("days", 30),
        date_from=request.arg("from") or None,
        date_to=request.arg("to") or None)
    return _csv(
        "daily-report-%s-to-%s.csv" % (report["from"], report["to"]),
        ["date", "in", "out", "net", "rejects", "adjusts", "anomalies", "total"],
        [[d["day"], d["in"], d["out"], d["net"], d["rejects"], d["adjusts"],
          d["anomalies"], d["total"]] for d in report["series"]],
    )


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------
@router.get("/api/categories", needs="inventory.read")
def categories(request):
    return {"ok": True, "categories": db.categories_list(),
            "uncategorised": db.uncategorised_products()}


@router.post("/api/categories/add", needs="categories.manage")
def category_add(request):
    ok, message = db.category_add(request.json().get("name", ""))
    if not ok:
        raise HttpError(400, message)
    return _ok(message, categories=db.categories_list(),
               uncategorised=db.uncategorised_products())


@router.post("/api/categories/rename", needs="categories.manage")
def category_rename(request):
    body = request.json()
    ok, message = db.category_rename(body.get("old", ""), body.get("new", ""))
    if not ok:
        raise HttpError(400, message)
    ml_registry.invalidate()
    return _ok(message, categories=db.categories_list(),
               uncategorised=db.uncategorised_products(), **_state_bundle())


@router.post("/api/categories/delete", needs="categories.manage")
def category_delete(request):
    ok, message = db.category_delete(request.json().get("name", ""))
    if not ok:
        raise HttpError(400, message)
    ml_registry.invalidate()
    return _ok(message, categories=db.categories_list(),
               uncategorised=db.uncategorised_products(), **_state_bundle())


@router.post("/api/categories/assign", needs="categories.manage")
def category_assign(request):
    body = request.json()
    ok, message = db.assign_category(body.get("product", ""), body.get("category", ""))
    if not ok:
        raise HttpError(400, message)
    # A new labelled example: the classifier should learn from it.
    ml_registry.invalidate()
    return _ok(message, categories=db.categories_list(),
               uncategorised=db.uncategorised_products(), **_state_bundle())


# ---------------------------------------------------------------------------
# Staff
# ---------------------------------------------------------------------------
@router.get("/api/staff", needs="staff.read")
def staff_list(request):
    return {
        "ok": True,
        "staff": users.list_users(),
        "summary": users.staff_summary(),
        "sessions": users.active_sessions(),
        "roles": [{"key": r, "label": users.ROLE_LABELS[r],
                   "description": users.ROLE_DESCRIPTIONS[r],
                   "capabilities": sorted(users.CAPABILITIES[r])} for r in users.ROLES],
    }


@router.post("/api/staff", needs="staff.create")
def staff_create(request):
    body = request.json()
    decision = _agent("Staff Agent").run({
        "action": "create", "actor": request.user, "target": None, "payload": body})
    if not decision.data.get("allowed"):
        raise HttpError(403, decision.data["message"], decision=decision.to_dict())

    ok, message, user = users.create_user(
        username=body.get("username", ""), password=body.get("password", ""),
        full_name=body.get("full_name", ""), role=body.get("role", "staff"),
        email=body.get("email", ""), phone=body.get("phone", ""),
        shift=body.get("shift", ""), actor=request.user,
        must_change_pw=body.get("must_change_pw", True))
    if not ok:
        raise HttpError(400, message)
    return _ok(message, user=user, decision=decision.to_dict(),
               staff=users.list_users(), summary=users.staff_summary())


@router.put("/api/staff/<int:staff_id>", needs="staff.update")
def staff_update(request, staff_id):
    body = request.json()
    target = users.get_user(staff_id)
    decision = _agent("Staff Agent").run({
        "action": "update", "actor": request.user, "target": target, "payload": body})
    if not decision.data.get("allowed"):
        raise HttpError(403, decision.data["message"], decision=decision.to_dict())

    ok, message, user = users.update_user(staff_id, actor=request.user, **{
        k: body.get(k) for k in ("full_name", "email", "phone", "role", "shift", "active")
        if k in body})
    if not ok:
        raise HttpError(400, message)
    return _ok(message, user=user, decision=decision.to_dict(),
               staff=users.list_users(), summary=users.staff_summary())


@router.delete("/api/staff/<int:staff_id>", needs="staff.delete")
def staff_delete(request, staff_id):
    target = users.get_user(staff_id)
    decision = _agent("Staff Agent").run({
        "action": "delete", "actor": request.user, "target": target, "payload": {}})
    if not decision.data.get("allowed"):
        raise HttpError(403, decision.data["message"], decision=decision.to_dict())

    ok, message = users.delete_user(staff_id, actor=request.user)
    if not ok:
        raise HttpError(400, message)
    return _ok(message, decision=decision.to_dict(),
               staff=users.list_users(), summary=users.staff_summary())


@router.post("/api/staff/<int:staff_id>/password", needs="staff.update")
def staff_password(request, staff_id):
    target = users.get_user(staff_id)
    decision = _agent("Staff Agent").run({
        "action": "reset_password", "actor": request.user,
        "target": target, "payload": request.json()})
    if not decision.data.get("allowed"):
        raise HttpError(403, decision.data["message"], decision=decision.to_dict())

    ok, message = users.set_password(
        staff_id, request.json().get("password", ""),
        actor=request.user, require_change=True)
    if not ok:
        raise HttpError(400, message)
    users.revoke_all_sessions(staff_id)
    return _ok(message, decision=decision.to_dict(), staff=users.list_users())


@router.post("/api/staff/<int:staff_id>/unlock", needs="staff.update")
def staff_unlock(request, staff_id):
    ok, message = users.unlock_user(staff_id, actor=request.user)
    if not ok:
        raise HttpError(400, message)
    return _ok(message, staff=users.list_users(), summary=users.staff_summary())


@router.get("/api/staff/events", needs="audit.read")
def staff_events(request):
    return {"ok": True, "events": users.recent_events(
        request.int_arg("limit", 100), request.arg("event") or None,
        request.arg("username") or None)}


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------
@router.get("/api/agents", needs="agents.read")
def agents(request):
    return {"ok": True, "agents": agent_roster(), "summary": agent_registry.summary()}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
@router.get("/api/models", needs="models.read")
def models(request):
    results = ml_registry.last_results()
    if results is None:
        results = ml_registry.train_all()
    return {"ok": True, "comparison": results, "summary": ml_registry.summary(),
            "dataset": ml_dataset.dataset_stats()}


@router.post("/api/models/train", needs="models.train")
def models_train(request):
    body = request.json()
    decision = _agent("Learning Agent").run({
        "action": "train",
        "deep": bool(body.get("deep")),
        "folds": body.get("folds"),
        "include_learned": body.get("include_learned", True),
    })
    return {"ok": True, "decision": decision.to_dict(),
            "comparison": decision.data.get("results"),
            "summary": ml_registry.summary()}


@router.get("/api/models/predict", needs="models.read")
def models_predict(request):
    """Ask the live model about a name without changing anything.

    A manager who wants to know why a product was suggested a category should be
    able to try one out, and see the reasoning, without scanning anything.
    """
    name = request.arg("name")
    if not name:
        raise HttpError(400, "Give a product name to classify.")
    model = ml_registry.active_model()
    if model is None:
        raise HttpError(503, "No model is trained yet.")
    label, confidence = model.predict(name)
    return {"ok": True, "name": name, "model": model.name,
            "prediction": label, "confidence": confidence,
            "explanation": model.explain(name),
            "probabilities": {k: round(v, 4)
                              for k, v in model.predict_proba(name).items()}}


@router.get("/api/report/comparison", needs="reports.read")
def report_comparison(request):
    """The evidence for how this system compares with the one it replaces."""
    from report import system_comparison
    results = ml_registry.last_results() or ml_registry.train_all()
    return {"ok": True, "comparison": system_comparison(results)}


@router.get("/api/report/market", needs="reports.read")
def report_market(request):
    """How this system compares with what a warehouse could buy instead.

    Distinct from `/api/report/comparison`, which compares it with the project
    it replaces. This one is measured against the market: paper, barcode
    hardware, scanning SDKs, enterprise WMS platforms, RFID and computer vision.
    """
    from market import market_comparison
    results = ml_registry.last_results() or ml_registry.train_all()
    return {"ok": True, "comparison": market_comparison(results)}


# ---------------------------------------------------------------------------
# Cameras
# ---------------------------------------------------------------------------
# Reading the camera list needs only `scan`, because the Scanner page has to
# know which camera to open. Changing the configuration needs
# `settings.manage`, which is the same bar as every other system setting.
@router.get("/api/cameras", needs="scan")
def cameras_list(request):
    station = request.arg("station") or None
    return {
        "ok": True,
        "cameras": camera_store.list_cameras(station),
        "stations": camera_store.stations(),
        "summary": camera_store.summary(station),
        "station": station,
    }


@router.get("/api/cameras/order", needs="scan")
def cameras_order(request):
    """The order the scanner should try cameras in, for this station.

    ``excluded`` carries the cameras that were deliberately turned off. The
    browser needs them by name: an attached-but-disabled camera is
    indistinguishable from one nobody has configured, and without this the
    scanner would helpfully offer to use it and undo the decision.
    """
    station = request.arg("station") or ""
    if not station:
        raise HttpError(400, "A station is required.")
    return {
        "ok": True,
        "cameras": camera_store.scanner_order(station),
        "excluded": camera_store.excluded(station),
        "summary": camera_store.summary(station),
    }


@router.post("/api/cameras", needs="settings.manage")
def cameras_create(request):
    body = request.json()
    ok, message, camera = camera_store.add_camera(
        station=body.get("station", ""),
        station_label=body.get("station_label", ""),
        name=body.get("name", ""),
        kind=body.get("kind", "device"),
        device_id=body.get("device_id", ""),
        device_label=body.get("device_label", ""),
        group_id=body.get("group_id", ""),
        facing=body.get("facing", ""),
        stream_url=body.get("stream_url", ""),
        role=body.get("role", "backup"),
        want_width=body.get("want_width", 1920),
        want_height=body.get("want_height", 1080),
        want_fps=body.get("want_fps", 15),
        notes=body.get("notes", ""),
        actor=request.user,
    )
    if not ok:
        raise HttpError(400, message)
    return _ok(message, camera=camera,
               cameras=camera_store.list_cameras(body.get("station")),
               summary=camera_store.summary(body.get("station")))


@router.put("/api/cameras/<int:camera_id>", needs="settings.manage")
def cameras_update(request, camera_id):
    body = request.json()
    ok, message, camera = camera_store.update_camera(
        camera_id, actor=request.user,
        **{k: body.get(k) for k in
           ("name", "role", "position", "want_width", "want_height", "want_fps",
            "notes", "stream_url", "facing", "station_label") if k in body})
    if not ok:
        raise HttpError(400, message)
    return _ok(message, camera=camera,
               cameras=camera_store.list_cameras(camera["station"]),
               summary=camera_store.summary(camera["station"]))


@router.delete("/api/cameras/<int:camera_id>", needs="settings.manage")
def cameras_delete(request, camera_id):
    existing = camera_store.get_camera(camera_id)
    ok, message = camera_store.delete_camera(camera_id)
    if not ok:
        raise HttpError(400, message)
    station = (existing or {}).get("station")
    return _ok(message, cameras=camera_store.list_cameras(station),
               summary=camera_store.summary(station))


@router.post("/api/cameras/reorder", needs="settings.manage")
def cameras_reorder(request):
    body = request.json()
    station = body.get("station", "")
    if not station:
        raise HttpError(400, "A station is required.")
    ok, message = camera_store.reorder(station, body.get("order") or [],
                                       actor=request.user)
    # `summary` is returned here as well as on create/update/delete. It was the
    # one mutation that omitted it, so a client refreshing from the response had
    # to special-case exactly this route.
    if not ok:
        raise HttpError(400, message)
    return _ok(message, cameras=camera_store.list_cameras(station),
               summary=camera_store.summary(station))


@router.post("/api/cameras/<int:camera_id>/test", needs="scan")
def cameras_test(request, camera_id):
    """Record a test the browser has just run.

    The measurement has to happen in the browser — it is the only place that can
    open the camera. The server scores and stores it, so the result is the same
    figure for everyone rather than a number that lives in one operator's tab.
    """
    ok, message, result = camera_store.record_test(
        camera_id, request.json(), actor=request.user)
    if not ok:
        raise HttpError(400, message)
    return _ok(message, result=result, camera=camera_store.get_camera(camera_id))


@router.get("/api/cameras/<int:camera_id>/tests", needs="scan")
def cameras_tests(request, camera_id):
    return {"ok": True, "tests": camera_store.test_history(
        camera_id, request.int_arg("limit", 20))}


# ---------------------------------------------------------------------------
# Assistant and settings
# ---------------------------------------------------------------------------
@router.post("/api/assistant", needs="assistant.use")
def assistant(request):
    return assistant_agent.run(request.json().get("question", ""))


@router.get("/api/settings", needs="inventory.read")
def settings_get(request):
    return {"ok": True, "settings": settings.all_settings(),
            "described": settings.described()}


@router.post("/api/settings", needs="settings.manage")
def settings_set(request):
    ok, message = settings.set_many(request.json().get("settings", {}),
                                    actor=request.user)
    if not ok:
        raise HttpError(400, message)
    return _ok(message, settings=settings.all_settings(),
               described=settings.described())


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------
def _csv(filename, header, rows):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    writer.writerows(rows)
    # A BOM, so Excel opens it as UTF-8 rather than mangling any accents.
    body = buf.getvalue().encode("utf-8-sig")
    return Response(body, 200, "text/csv; charset=utf-8", {
        "Content-Disposition": 'attachment; filename="%s"' % filename})


@router.get("/api/export/inventory.csv", needs="inventory.read")
def export_inventory(request):
    rows = []
    for r in db.inventory_summary()["rows"]:
        for b in r["batches"]:
            rows.append([r["name"], r["category"] or "", b["productno"],
                         b["batchno"], b["qty"], r["min_qty"]])
    return _csv("inventory.csv",
                ["product", "category", "productno", "batchno", "qty", "reorder_at"],
                rows)


@router.get("/api/export/logs.csv", needs="inventory.read")
def export_logs(request):
    entries = db.search_logs(request.arg("q"), request.arg("action"),
                             request.int_arg("limit", 500))
    return _csv("activity.csv",
                ["timestamp", "action", "product", "productno", "batchno",
                 "category", "staff", "anomaly", "undone"],
                [[l["ts"], l["action"], l["name"] or "", l["productno"] or "",
                  l["batchno"] or "", l["category"] or "", l.get("username", ""),
                  l["anomaly"], l["undone"]] for l in entries])


@router.get("/api/export/models.json", needs="models.read")
def export_models(request):
    results = ml_registry.last_results() or ml_registry.train_all()
    body = json.dumps(results, indent=2).encode("utf-8")
    return Response(body, 200, "application/json; charset=utf-8", {
        "Content-Disposition": 'attachment; filename="model-evaluation.json"'})
