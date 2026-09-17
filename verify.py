#!/usr/bin/env python3
"""
verify.py - self-test for the Agentic Warehouse MVP
===================================================
Runs the whole multi-agent pipeline in-process (no browser needed), plus a live
HTTP smoke test on a throwaway port, and reports the classifier's measured
accuracy. It uses a TEMPORARY database, so it never touches your real data.

Usage:
    python verify.py

Exit code 0 = every check passed. Exit code 1 = something failed.
"""

import os
import sys
import tempfile

# make the project importable when run from its own folder
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

results = []


def check(name, ok, detail=""):
    results.append((bool(ok), name, detail))
    tag = "[ OK ]" if ok else "[FAIL]"
    print(f"{tag}  {name}" + (f"  ->  {detail}" if detail else ""))
    return bool(ok)


def check_documented_total(base):
    """The published check count has to be the count this file actually runs.

    Golden rule 10 applied to the self-test itself. Six documents state a number
    of checks and, until this existed, nothing compared it to reality -- so the
    one figure a reader is most likely to quote was the one figure nothing
    verified. It drifted, of course.

    Counting itself is the whole difficulty: this check is one of the results it
    is counting, and it must run last. So it adds one for itself, and the
    documents state the total including it.
    """
    import re as _re

    stated = {}
    documents = 0
    for name in sorted(os.listdir(base)):
        if not name.endswith(".md"):
            continue
        documents += 1
        text = open(os.path.join(base, name), encoding="utf-8").read()
        # A word boundary after "checks", so "modulo 103 checksum" -- a real
        # sentence in these documents -- is not read as a check count.
        #
        # The boundary is built with chr(92) rather than written as an escape,
        # and that is not fussiness. A lone backslash-b inside a regular string
        # is the BACKSPACE character, and this file has already shipped a
        # doc-check regex whose boundaries were stored as literal 0x08 bytes:
        # it then matched nothing, reported nothing, and passed every run.
        # The guard below is what makes that failure loud instead of silent.
        edge = chr(92) + "b"
        hits = {int(m) for m in _re.findall(r"(\d+)\s*/\s*\d+\s+checks" + edge, text)}
        hits |= {int(m) for m in _re.findall(r"(\d+)\s+checks" + edge, text)}
        hits |= {int(m) for m in _re.findall(r"(\d+)-check" + edge, text)}
        if hits:
            stated[name] = hits

    total = len(results) + 1
    # An empty `stated` is a FAILURE when documents exist, not a pass. These
    # documents do state a count; finding none in them means the pattern above
    # stopped working, and the check would otherwise sail through green
    # forever -- which is precisely how its predecessor went unnoticed.
    #
    # No documents at all is a different thing and is fine: package_clean.py
    # strips every .md out of the delivered copy on purpose, and the self-test
    # is expected to pass there. Absent is not the same as unmatched.
    ok = (documents == 0) or (
        bool(stated) and all(hits == {total} for hits in stated.values()))
    if documents == 0:
        detail = f"{total} run; no markdown shipped in this copy"
    elif not stated:
        detail = f"{total} run; {documents} document(s) present and NONE states a count"
    else:
        detail = (f"{total} run; docs say "
                  + str({k: sorted(v) for k, v in stated.items()}))
    check("the documented check count matches this file", ok, detail)


def summary_and_exit():
    total = len(results)
    passed = sum(1 for ok, _, _ in results if ok)
    failed = [(n, d) for ok, n, d in results if not ok]
    print("-" * 64)
    print(f"  {passed}/{total} checks passed.")
    if failed:
        print("  FAILED:")
        for n, d in failed:
            print(f"    - {n}" + (f"  ({d})" if d else ""))
        print("=" * 64)
        sys.exit(1)
    print("  ALL CHECKS PASSED - the MVP works on this machine.")
    print("=" * 64)
    sys.exit(0)


def main():
    print("=" * 64)
    print("  Agentic Warehouse MVP - self-test (verify.py)")
    print("=" * 64)

    base = os.path.dirname(os.path.abspath(__file__))

    # 1) Python version
    v = sys.version_info
    check(f"Python {v.major}.{v.minor}.{v.micro} (need >= 3.8)", v >= (3, 8))

    # 2) required files present
    for rel in ("app.py", "db.py",
                "static/html5-qrcode.min.js", "static/lucide.min.js",
                "static/app.js", "static/styles.css", "templates/index.html"):
        p = os.path.join(base, rel)
        check(f"file present: {rel}", os.path.isfile(p) and os.path.getsize(p) > 0)

    # 3) import modules and point the DB at a temp file
    # Per-process, so two verify.py runs (a terminal and a CI job, say) do not
    # share one database and clobber each other's counts.
    tmp = os.path.join(tempfile.gettempdir(), "aw_selftest_%d.db" % os.getpid())
    for suf in ("", "-wal", "-shm"):
        try:
            os.remove(tmp + suf)
        except OSError:
            pass
    try:
        from core import dbcore
        dbcore.set_db_path(tmp)          # isolate every module from real data
        import db
        db.init_db()
        from store import settings as settings_store
        settings_store.init_settings()
        # The camera tables are created by app.initialise(), which this file
        # never calls -- so without this every camera check died on
        # "no such table: cameras" rather than on anything it was testing.
        from store import cameras as camera_store
        camera_store.init_cameras()
        from agents import orchestrator, classifier_agent, assistant_agent
        check("modules import + database init", True)

        # Measure the classifier NOW, on a database holding only the seeded
        # catalogue. Everything below creates products, and every product a
        # manager files becomes a labelled example -- so by the time the
        # bake-off runs at the end, the corpus has grown and no longer matches
        # the figure the documentation publishes. Both numbers are real; only
        # this one is reproducible from a fresh install.
        from ml import registry as _ml_reg, dataset as _ml_ds
        fresh_comparison = _ml_reg.train_all()
        fresh_stats = _ml_ds.dataset_stats()
        _ml_reg.invalidate()
    except Exception as e:               # noqa: BLE001
        check("modules import + database init", False, repr(e))
        summary_and_exit()
        return

    # 4) IN a catalogue item -> IN, classified, full 5-agent trace
    r = orchestrator.process_scan("ONT,BATCH01,900001", "IN", "manual")
    check("scan IN catalogue item -> IN", r["final"] == "IN" and r["ok"], r["final"])
    check("  classified as Networking", r["category"] == "Networking", r["category"])
    check("  5-agent trace recorded", len(r["trace"]) == 5,
          ", ".join(s["agent"] for s in r["trace"]))

    # 5) scanning the same code again ADDS another unit (quantity model)
    r = orchestrator.process_scan("ONT,BATCH01,900001", "IN", "manual")
    check("repeat IN -> quantity 2", r["final"] == "IN" and r["qty"] == 2, r["reason"])
    r = orchestrator.process_scan("ONT,BATCH01,900001", "IN", "manual")
    check("third IN -> quantity 3", r["final"] == "IN" and r["qty"] == 3, r["reason"])

    # 6) OUT decrements one unit at a time
    r = orchestrator.process_scan("ONT,BATCH01,900001", "OUT", "manual")
    check("scan OUT -> quantity 2", r["final"] == "OUT" and r["qty"] == 2, r["reason"])
    r = orchestrator.process_scan("ONT,BATCH01,900001", "OUT", "manual")
    check("scan OUT -> quantity 1", r["final"] == "OUT" and r["qty"] == 1, r["reason"])
    r = orchestrator.process_scan("ONT,BATCH01,900001", "OUT", "manual")
    check("scan OUT -> quantity 0", r["final"] == "OUT" and r["qty"] == 0, r["reason"])

    # 7) OUT past zero -> REJECT (cannot remove stock that is not there)
    r = orchestrator.process_scan("ONT,BATCH01,900001", "OUT", "manual")
    check("OUT at zero -> REJECT", r["final"] == "REJECT", r["reason"])

    # 7b) OUT of an item never seen -> REJECT
    r = orchestrator.process_scan("GHOST,B,999999", "OUT", "manual")
    check("OUT unknown item -> REJECT", r["final"] == "REJECT", r["reason"])

    # 8) plain barcode -> Unknown Item, accepted IN
    r = orchestrator.process_scan("8901234567890", "IN", "barcode")
    check("barcode-only IN -> Unknown Item", r["final"] == "IN" and r["name"] == "Unknown Item", r["name"])

    # 9) a novel name is NOT silently labelled — it is Uncategorised + a suggestion
    cats = db.category_names()
    c = classifier_agent.run("gigabit poe switch", None, cats)
    check("novel name -> Uncategorised, not a guess",
          c["category"] == db.UNCATEGORISED, c["category"])
    check("  classifier still offers a suggestion",
          c.get("suggestion") and c["suggestion"]["category"] in cats,
          (c.get("suggestion") or {}).get("category"))

    # 10) user-managed categories: create, assign, and see it stick
    ok, _ = db.category_add("Test Gear")
    check("add a category", ok and "Test Gear" in db.category_names())
    orchestrator.process_scan("Laser Sensor,B,900200", "IN", "manual")
    check("  unseen product lands in Uncategorised",
          any(p["name"] == "Laser Sensor" for p in db.uncategorised_products()))
    ok, _ = db.assign_category("Laser Sensor", "Test Gear")
    check("  assign product -> category", ok and db.catalog_lookup("Laser Sensor") == "Test Gear")
    check("  existing stock is re-filed",
          any(r["name"] == "Laser Sensor" and r["category"] == "Test Gear"
              for r in db.inventory_summary()["rows"]))
    r = orchestrator.process_scan("Laser Sensor,B,900200", "IN", "manual")
    check("  future scans reuse the assignment", r["category"] == "Test Gear", r["category"])
    ok, _ = db.category_rename("Test Gear", "Lab Gear")
    check("rename a category", ok and db.catalog_lookup("Laser Sensor") == "Lab Gear")
    ok, _ = db.category_delete("Lab Gear")
    check("delete a category -> falls back to Uncategorised",
          ok and db.catalog_lookup("Laser Sensor") == db.UNCATEGORISED)
    ok, _ = db.category_delete(db.UNCATEGORISED)
    check("  the Uncategorised bucket is protected", not ok)

    # 10b) batch tracking: two batches of one product number coexist
    orchestrator.process_scan("Router,BATCH-A,900300", "IN", "manual")
    orchestrator.process_scan("Router,BATCH-A,900300", "IN", "manual")
    r = orchestrator.process_scan("Router,BATCH-B,900300", "IN", "manual")
    check("two batches of one product number", r["qty"] == 3, f"total={r['qty']}")
    row = next(x for x in db.inventory_summary()["rows"] if x["name"] == "Router")
    check("  batch breakdown recorded",
          sorted((b["batchno"], b["qty"]) for b in row["batches"]) ==
          [("BATCH-A", 2), ("BATCH-B", 1)],
          str([(b["batchno"], b["qty"]) for b in row["batches"]]))
    r = orchestrator.process_scan("Router,BATCH-B,900300", "OUT", "manual")
    check("  OUT draws from the scanned batch", r["qty"] == 2, r["reason"])
    # BATCH-B is now empty, so a further OUT on it must fall back to BATCH-A (FIFO)
    r = orchestrator.process_scan("Router,BATCH-B,900300", "OUT", "manual")
    check("  empty batch falls back to FIFO",
          r["final"] == "OUT" and "FIFO" in r["reason"], r["reason"])

    # 10c) low-stock alerts driven by a user-set reorder level
    ok, _ = db.set_min_qty("Router", 3)
    check("set a reorder level", ok and db.min_qty_for("Router") == 3)
    alert = next((a for a in db.low_stock() if a["name"] == "Router"), None)
    check("  low stock raises an alert",
          alert and alert["status"] == "LOW" and alert["qty"] == 1,
          alert and f"qty={alert['qty']} min={alert['min_qty']}")
    f = next(s for s in orchestrator.process_scan("Router,BATCH-A,900300", "OUT", "manual")["trace"]
             if s["agent"] == "Forecast Agent")
    check("  forecast agent reports below-reorder", f.get("below_reorder") is True,
          str(f.get("notes"))[:70])
    ok, _ = db.set_min_qty("Router", 0)
    check("  reorder level 0 disables the alert",
          ok and not any(a["name"] == "Router" for a in db.low_stock()))
    ok, msg = db.set_min_qty("Router", -1)
    check("  negative reorder level is refused", not ok, msg)

    # 10d) manual stock correction
    orchestrator.process_scan("Set Top Box,STB1,900400", "IN", "manual")
    ok, msg, _ = db.adjust_stock("900400", "STB1", 25)
    check("manual correction sets the quantity",
          ok and db.product_total("900400") == 25, msg)
    check("  correction is logged as ADJUST",
          db.recent_logs(1)[0]["action"] == "ADJUST", db.recent_logs(1)[0]["action"])
    ok, msg, _ = db.adjust_stock("900400", "STB1", -1)
    check("  negative quantity is refused", not ok, msg)
    ok, msg, _ = db.adjust_stock("900400", "STB1", "abc")
    check("  non-numeric quantity is refused", not ok, msg)
    ok, msg, _ = db.adjust_stock("900400", "NOSUCH", 5)
    check("  unknown batch is refused", not ok, msg)

    # 10e) undo the last scan
    orchestrator.process_scan("Modem,MB1,900450", "IN", "manual")
    orchestrator.process_scan("Modem,MB1,900450", "IN", "manual")
    u = db.last_undoable()
    check("undo target is the last scan",
          u and u["action"] == "IN" and u["productno"] == "900450", u and u["action"])
    ok, msg, _ = db.undo_last()
    check("  undo an IN removes the unit", ok and db.product_total("900450") == 1, msg)
    check("  the reversal is recorded as UNDO",
          db.recent_logs(1)[0]["action"] == "UNDO", db.recent_logs(1)[0]["action"])
    orchestrator.process_scan("Modem,MB1,900450", "OUT", "manual")
    ok, msg, _ = db.undo_last()
    check("  undo an OUT restores the unit", ok and db.product_total("900450") == 1, msg)
    # A reversed scan is settled: undoing again must move on to an older scan
    # rather than reversing the same one twice.
    db.undo_last()                                  # reverses the remaining Modem IN
    check("  each scan is only undone once", db.product_total("900450") == 0,
          f"qty={db.product_total('900450')}")
    check("  undo then moves to an older scan",
          (db.last_undoable() or {}).get("productno") != "900450",
          (db.last_undoable() or {}).get("productno"))

    # Undo must refuse rather than drive stock negative.
    orchestrator.process_scan("Webcam,WC1,900460", "IN", "manual")
    db.adjust_stock("900460", "WC1", 0)          # the unit has since gone
    ok, msg, _ = db.undo_last()
    check("  undo refuses to go negative",
          not ok and db.product_total("900460") == 0, msg)

    # 10g) a bare product number matches the product it already is
    orchestrator.process_scan("Network Switch,SW01,900700", "IN", "manual")
    orchestrator.process_scan("Network Switch,SW01,900700", "IN", "manual")
    r = orchestrator.process_scan("900700", "IN", "barcode")     # barcode: no name, no batch
    check("barcode IN matches the existing product",
          r["name"] == "Network Switch" and r["qty"] == 3, f"{r['name']} qty={r['qty']}")
    check("  it lands on the existing batch, not a new one",
          [b["batchno"] for b in next(x for x in db.inventory_summary()["rows"]
                                      if x["name"] == "Network Switch")["batches"]] == ["SW01"],
          str([b["batchno"] for b in next(x for x in db.inventory_summary()["rows"]
                                          if x["name"] == "Network Switch")["batches"]]))
    check("  no stray 'Unknown Item' row is created",
          not any(x["name"] == "Unknown Item" and
                  any(b["productno"] == "900700" for b in x["batches"])
                  for x in db.inventory_summary()["rows"]))
    check("  it keeps its category", r["category"] == "Networking", r["category"])
    r = orchestrator.process_scan("900700", "OUT", "barcode")
    check("barcode OUT removes from the same product",
          r["name"] == "Network Switch" and r["qty"] == 2, f"{r['name']} qty={r['qty']}")

    # A product number never seen before is still honestly unknown...
    r = orchestrator.process_scan("8899776655", "IN", "barcode")
    check("a genuinely new barcode stays Unknown Item",
          r["name"] == "Unknown Item", r["name"])
    # ...until it is named, after which it matches like any other product.
    ok, msg = db.rename_product("8899776655", "Barcode Scanner")
    check("  naming an unknown product", ok, msg)
    orchestrator.reset_duplicate_state()      # naming it is a deliberate pause
    r = orchestrator.process_scan("8899776655", "IN", "barcode")
    check("  the named product then matches",
          r["name"] == "Barcode Scanner" and r["qty"] == 2, f"{r['name']} qty={r['qty']}")
    ok, msg = db.rename_product("8899776655", "   ")
    check("  an empty name is refused", not ok, msg)

    # 10h) the printed EAN-13 carries a check digit the QR payload does not
    orchestrator.process_scan("Martini Glass 225ML,27020,789076542345", "IN", "manual")
    orchestrator.process_scan("Martini Glass 225ML,27020,789076542345", "IN", "manual")
    check("QR product no. is 12 digits", db.product_total("789076542345") == 2)
    r = orchestrator.process_scan("7890765423458", "IN", "barcode")   # +check digit
    check("EAN-13 with check digit matches the QR product",
          r["name"] == "Martini Glass 225ML" and r["productno"] == "789076542345",
          f"{r['name']} / {r['productno']}")
    check("  it adds to the same stock, not a new row",
          db.product_total("789076542345") == 3 and db.product_total("7890765423458") == 0,
          f"canonical={db.product_total('789076542345')}")
    r = orchestrator.process_scan("7890765423458", "OUT", "barcode")
    check("  and OUT works the same way",
          r["final"] == "OUT" and r["qty"] == 2, r["reason"])

    # UPC-A <-> EAN-13 differ by a leading zero
    orchestrator.process_scan("Wine Glass,WG1,012345678905", "IN", "manual")
    r = orchestrator.process_scan("0012345678905", "IN", "barcode")
    check("UPC-A / EAN-13 leading zero also matches",
          r["name"] == "Wine Glass", r["name"])

    # A code that is genuinely different can be linked by hand.
    orchestrator.process_scan("5555000011112", "IN", "barcode")
    check("an unrelated code stays unknown",
          any(x["name"] == "Unknown Item" for x in db.inventory_summary()["rows"]))
    ok, msg = db.link_code("5555000011112", "789076542345")
    check("  link it to a product", ok, msg)
    check("  its stray unit is folded in, not stranded",
          db.product_total("789076542345") == 3, f"qty={db.product_total('789076542345')}")
    orchestrator.reset_duplicate_state()      # linking it is a deliberate pause
    r = orchestrator.process_scan("5555000011112", "IN", "barcode")
    check("  the linked code then matches",
          r["name"] == "Martini Glass 225ML" and r["qty"] == 4, f"{r['name']} qty={r['qty']}")
    ok, msg = db.link_code("999", "does-not-exist")
    check("  linking to a missing product is refused", not ok, msg)

    # Ordinary (non-barcode) product numbers must never be loosely matched.
    check("short product numbers are not variant-matched",
          db._code_variants("900001") == [], str(db._code_variants("900001")))

    # 10f) chart data + search + export feeds
    cats = db.category_totals()
    check("chart: stock by category", bool(cats) and all("qty" in c for c in cats),
          str([(c["category"], c["qty"]) for c in cats])[:60])
    act = db.activity_daily(7)
    check("chart: 7 days of activity, zero-filled",
          len(act) == 7 and all("in" in d and "out" in d for d in act),
          f"{len(act)} days")
    check("  activity totals match the log",
          sum(d["in"] for d in act) == db.stats()["scans_in"],
          f"chart={sum(d['in'] for d in act)} stats={db.stats()['scans_in']}")
    check("search the audit trail", len(db.search_logs("900001")) > 0,
          f"{len(db.search_logs('900001'))} hits")
    check("  filter by action",
          all(l["action"] == "ADJUST" for l in db.search_logs("", "ADJUST")),
          f"{len(db.search_logs('', 'ADJUST'))} rows")
    check("  a search with no match is empty", db.search_logs("zzzznope") == [])

    # 11) a camera double-read is now PREVENTED, not merely flagged after the
    # unit has already been added. This is the fix for one held label becoming
    # a dozen units.
    orchestrator.reset_duplicate_state()
    before = db.product_total("900100")
    orchestrator.process_scan("Universal Remote,B,900100", "IN", "qr")
    counted = db.product_total("900100")
    check("a camera scan adds exactly one unit", counted == before + 1,
          f"{before} -> {counted}")

    n_logs = len(db.search_logs("900100"))
    suppressed = 0
    for _ in range(11):          # the same label still sitting in front of the lens
        r2 = orchestrator.process_scan("Universal Remote,B,900100", "IN", "qr")
        if r2.get("duplicate"):
            suppressed += 1
    check("  holding it in frame does NOT keep adding units",
          db.product_total("900100") == counted,
          f"still {db.product_total('900100')} after 11 more decodes")
    check("  every repeat read is reported as a duplicate", suppressed == 11,
          f"{suppressed}/11 suppressed")
    check("  and none of them reaches the audit trail",
          len(db.search_logs("900100")) == n_logs,
          f"{len(db.search_logs('900100')) - n_logs} extra rows")

    # The window is a delay, not a lock: presenting the item again counts it.
    import time as _time
    _time.sleep(float(settings_store.get("double_read_window")) + 0.2)
    orchestrator.process_scan("Universal Remote,B,900100", "IN", "qr")
    check("  presenting it again after the delay adds another",
          db.product_total("900100") == counted + 1,
          f"qty={db.product_total('900100')}")

    # Two symbologies for one product are one item, not two.
    orchestrator.reset_duplicate_state()
    orchestrator.process_scan("Martini Glass 225ML,27020,789076542345", "IN", "qr")
    q = db.product_total("789076542345")
    r = orchestrator.process_scan("7890765423458", "IN", "barcode")
    check("  a QR and its printed barcode count once, not twice",
          r.get("duplicate") and db.product_total("789076542345") == q,
          f"{r.get('final')} qty={db.product_total('789076542345')}")

    # Different products in quick succession must never be delayed.
    orchestrator.reset_duplicate_state()
    a = orchestrator.process_scan("Router,BATCH-A,900300", "IN", "qr")
    b = orchestrator.process_scan("Network Switch,SW01,900700", "IN", "qr")
    check("  two different products back to back are both counted",
          a["final"] == "IN" and b["final"] == "IN", f"{a['final']}/{b['final']}")
    orchestrator.reset_duplicate_state()

    # ...but deliberate repeat entry is never suppressed: typing a code five
    # times is how someone counts five identical boxes in.
    for _ in range(5):
        r3 = orchestrator.process_scan("HDMI Cable,B,900101", "IN", "sample")
    check("  deliberate repeat entry still builds quantity",
          r3["final"] == "IN" and db.product_total("900101") == 5,
          f"qty={db.product_total('900101')}")
    an3 = next(s for s in r3["trace"] if s["agent"] == "Anomaly Agent")
    check("  and is not flagged as an anomaly", not an3.get("flagged"),
          f"score={an3.get('score')}")

    # 11) assistant offline responder works
    a = assistant_agent.run("how many items in stock?")
    check("assistant answers a question", bool(a.get("answer")), a.get("mode"))

    # 11b) authentication, roles and staff management
    from store import users as users_store
    seeded = users_store.init_auth()
    admin, reason = users_store.authenticate("admin", "admin12345", "127.0.0.1")
    check("default administrator can sign in", admin is not None, reason or admin["role"])

    # The issued password is deliberately near-useless until it is changed.
    check("  an account on its issued password cannot scan",
          not users_store.can(admin, "scan"))
    check("  nor manage staff", not users_store.can(admin, "staff.create"))
    ok, msg = users_store.set_password(admin["id"], "Warehouse#Admin1",
                                       actor=admin, require_change=False)
    admin, _ = users_store.authenticate("admin", "Warehouse#Admin1", "127.0.0.1")
    check("  changing it restores full access",
          ok and users_store.can(admin, "scan") and users_store.can(admin, "staff.create"), msg)
    bad, reason = users_store.authenticate("admin", "wrong-password", "127.0.0.1")
    check("  a wrong password is refused", bad is None, reason)
    ghost, reason = users_store.authenticate("nobody", "whatever", "127.0.0.1")
    check("  an unknown user is refused without saying so", ghost is None, reason)

    ok, msg, staff = users_store.create_user(
        "picker01", "Warehouse#1", full_name="Sam Picker", role="staff", actor=admin,
        must_change_pw=False)
    check("create a staff account", ok, msg)
    ok, msg, _ = users_store.create_user("x", "Warehouse#1", actor=admin)
    check("  too short a username is refused", not ok, msg)
    ok, msg, _ = users_store.create_user("picker02", "123", actor=admin)
    check("  a weak password is refused", not ok, msg)
    ok, msg, _ = users_store.create_user("picker01", "Warehouse#1", actor=admin)
    check("  a duplicate username is refused", not ok, msg)

    check("staff role holds 'scan'", users_store.can(staff, "scan"))
    check("  staff role does NOT hold 'staff.create'",
          not users_store.can(staff, "staff.create"))
    check("  admin role holds 'staff.create'", users_store.can(admin, "staff.create"))

    ok, msg, _ = users_store.update_user(admin["id"], actor=admin, role="staff")
    check("the last administrator cannot be demoted", not ok, msg)
    ok, msg = users_store.delete_user(admin["id"], actor=admin)
    check("  nor deleted", not ok, msg)

    token = users_store.create_session(staff["id"], "127.0.0.1", "selftest")
    who, sess = users_store.session_user(token)
    check("a session resolves to its user", who and who["username"] == "picker01",
          who and who["username"])

    other = users_store.create_session(staff["id"], "127.0.0.1", "another device")
    users_store.change_own_password(staff["id"], "Warehouse#1", "Warehouse#2")
    left, _ = users_store.session_user(other)
    check("  changing your own password signs out other devices", left is None)
    users_store.change_own_password(staff["id"], "Warehouse#2", "Warehouse#1")
    token = users_store.create_session(staff["id"], "127.0.0.1", "selftest")
    users_store.update_user(staff["id"], actor=admin, active=False)
    who, _ = users_store.session_user(token)
    check("  disabling an account kills its live session", who is None)
    users_store.update_user(staff["id"], actor=admin, active=True)

    for _ in range(users_store.MAX_FAILED_ATTEMPTS):
        users_store.authenticate("picker01", "nope", "127.0.0.1")
    locked, reason = users_store.authenticate("picker01", "Warehouse#1", "127.0.0.1")
    check("repeated failures lock the account", locked is None, reason)
    ok, msg = users_store.unlock_user(staff["id"], actor=admin)
    unlocked, reason = users_store.authenticate("picker01", "Warehouse#1", "127.0.0.1")
    check("  an administrator can unlock it", unlocked is not None, msg)

    # 11c) the Recovery Agent -- the backup scanner
    from agents.base import registry as agent_reg
    recov = agent_reg.get("Recovery Agent")
    orchestrator.process_scan("Wine Glass,WG1,012345678905", "IN", "manual")
    cases = [
        ("  a wedge scanner's stray control characters", "  012345678905\r\n"),
        ("  a GS1 label wrapped in identifiers", "(01)00012345678905(10)WG1"),
        ("  a character confusion (O read for 0)", "O12345678905"),
        ("  a truncated read", "01234567890"),
    ]
    for label, raw in cases:
        d = recov.run({"code": raw})
        check("recovery repairs" + label,
              d.data.get("repaired") == "012345678905",
              "%s via %s (%.0f%%)" % (d.data.get("repaired"), d.data.get("strategy"),
                                      d.confidence * 100))
    d = recov.run({"code": "zzz-not-a-code-at-all"})
    check("  and gives up honestly on nonsense",
          d.data.get("repaired") is None and d.data.get("advice") == "switch_input")

    # 11d) every component really is an agent
    from agents import roster
    all_agents = roster()
    check("every component is a registered agent", len(all_agents) >= 13,
          f"{len(all_agents)} agents across "
          f"{len({a['layer'] for a in all_agents})} layers")
    check("  each declares a role and a method",
          all(a["role"] and a["method"] for a in all_agents))

    # A failing agent must degrade, not take the pipeline down with it.
    from agents.base import Agent, Decision
    class _Exploding(Agent):
        name = "Exploding Test Agent"
        def decide(self, context):
            raise RuntimeError("deliberate failure")
    boom = _Exploding().run({})
    check("a failing agent degrades instead of raising",
          boom.degraded and boom.verdict == "DEGRADED", boom.rationale[0])

    # 11e) product CRUD
    db.category_add("Glassware")
    ok, msg, created = db.create_product(
        "Wine Glass Crystal", "900555", "WG-A", 12, "Glassware", 4)
    check("create a product by hand", ok and created["qty"] == 12, msg)
    check("  the opening quantity is logged as ADJUST, not a scan",
          db.recent_logs(1)[0]["action"] == "ADJUST")
    ok, msg, _ = db.create_product("Wine Glass Crystal", "900555", "WG-A", 1, "Glassware")
    check("  a duplicate product number is refused", not ok, msg)
    ok, msg, _ = db.create_product("Ghost", "900556", "", 1, "No Such Category")
    check("  an unknown category is refused", not ok, msg)
    ok, msg, _ = db.create_product("", "900557")
    check("  an empty name is refused", not ok, msg)

    ok, msg = db.update_product("900555", min_qty=6)
    check("update a product", ok and db.min_qty_for("Wine Glass Crystal") == 6, msg)
    ok, msg = db.update_product("900555", name="Crystal Wine Glass")
    check("  renaming carries across every batch",
          ok and db.product_detail("900555")["name"] == "Crystal Wine Glass", msg)

    ok, msg = db.add_batch("900555", "WG-B", 3)
    detail = db.product_detail("900555")
    check("add a batch", ok and len(detail["batches"]) == 2 and detail["qty"] == 15, msg)
    ok, msg = db.add_batch("900555", "WG-B", 1)
    check("  a duplicate batch is refused", not ok, msg)
    ok, msg = db.delete_batch("900555", "WG-B")
    check("  a batch holding stock cannot be deleted", not ok, msg)
    db.adjust_stock("900555", "WG-B", 0)
    ok, msg = db.delete_batch("900555", "WG-B")
    check("  an empty batch can be deleted",
          ok and len(db.product_detail("900555")["batches"]) == 1, msg)

    ok, msg = db.delete_product("900555")
    check("a product holding stock cannot be deleted", not ok, msg)
    db.adjust_stock("900555", "WG-A", 0)
    ok, msg = db.delete_product("900555")
    check("  an empty product can be deleted", ok and db.product_detail("900555") is None, msg)
    check("  but its audit history survives the deletion",
          len(db.search_logs("900555")) > 0,
          f"{len(db.search_logs('900555'))} entries kept")

    # 11f) product detail
    orchestrator.process_scan("Network Switch,SW01,900700", "IN", "manual")
    detail = db.product_detail("900700")
    check("product detail is assembled",
          detail and detail["name"] == "Network Switch" and detail["history"],
          f"{len(detail['history'])} history rows, {len(detail['codes'])} codes")
    check("  it lists every code that reaches the product",
          "900700" in detail["codes"])
    check("  and reports movement totals",
          detail["totals"]["in"] >= 1, str(detail["totals"]))
    check("  a missing product returns nothing rather than an empty shell",
          db.product_detail("does-not-exist") is None)

    # 11g) daily report
    report = db.daily_report(days=7)
    check("daily report covers the requested window",
          len(report["series"]) == 7 and report["from"] <= report["to"],
          f"{report['from']} to {report['to']}")
    check("  IN and OUT totals match the audit trail",
          report["summary"]["in"] == sum(d["in"] for d in report["series"]) and
          report["summary"]["out"] == sum(d["out"] for d in report["series"]))
    check("  net movement is in minus out",
          report["summary"]["net"] == report["summary"]["in"] - report["summary"]["out"],
          f"net={report['summary']['net']}")
    check("  every day is present, including quiet ones",
          all("day" in d and "in" in d and "out" in d for d in report["series"]))
    check("  it breaks down by product, category, staff and hour",
          all(k in report for k in ("by_product", "by_category", "by_staff", "by_hour")) and
          len(report["by_hour"]) == 24)
    ranged = db.daily_report(date_from="2026-01-01", date_to="2026-01-07")
    check("  an explicit date range is honoured",
          ranged["from"] == "2026-01-01" and ranged["days"] == 7,
          f"{ranged['from']} to {ranged['to']}")

    # 11h) QR and barcode generation
    from core import qrcode as qr_mod, barcode as bc_mod
    matrix = qr_mod.encode("ONT,BATCH01,900001", "M")
    check("QR encoder produces a square matrix of the right size",
          len(matrix) == len(matrix[0]) and (len(matrix) - 17) % 4 == 0,
          f"{len(matrix)}x{len(matrix)} (version {(len(matrix) - 17) // 4})")
    check("  finder patterns are in all three corners",
          matrix[0][0] == 1 and matrix[0][len(matrix) - 7] == 1 and matrix[len(matrix) - 7][0] == 1)
    svg = qr_mod.to_svg("https://10.0.0.28:8443", level="M")
    check("  it renders as SVG", svg.startswith("<svg") and svg.endswith("</svg>"),
          f"{len(svg)} bytes")
    try:
        qr_mod.encode("x" * 400)
        check("  an oversized payload is refused", False)
    except qr_mod.QRError:
        check("  an oversized payload is refused", True)

    # The QR encoder is now READ BACK, which it never was. Until this existed
    # the symbols were checked structurally -- module count, format bits, the
    # always-dark module -- and CLAUDE.md said so: not round-tripped, "it stays
    # a manual check". Structure confirms a QR-shaped thing was drawn; it does
    # not confirm the thing says what it was asked to say. A mask applied to
    # the wrong modules, a format copy written the wrong way round, or an
    # interleave off by one block all pass every structural assertion and
    # decode in nothing.
    from core import qrcode_decode as qr_dec
    import random as _random          # also used by the barcode checks below

    def _render_qr(matrix, scale=5, quiet=4, dark=25, light=245):
        n = len(matrix)
        side = (n + quiet * 2) * scale
        out = bytearray([light]) * (side * side)
        for r in range(n):
            for c in range(n):
                if not matrix[r][c]:
                    continue
                for y in range((r + quiet) * scale, (r + quiet + 1) * scale):
                    row = y * side
                    for x in range((c + quiet) * scale, (c + quiet + 1) * scale):
                        out[row + x] = dark
        return bytes(out), side

    _qr_round = []
    for _text, _level in (("ONT,BATCH01,900001", "L"),
                          ("Martini Glass 225ML,27020,789076542345", "M"),
                          ("https://10.0.0.28:8443", "L"),
                          ("HT SHOE BRUSH BLACK 10's,SHB011,600968988112", "L")):
        _band, _side = _render_qr(qr_mod.encode(_text, _level))
        _got = qr_dec.decode(_band, _side, _side)
        _qr_round.append((_text, _got.get("text"), _got.get("version"),
                          _got.get("level")))
    check("a QR the encoder drew is read back and says the same thing",
          all(a == b for a, b, _v, _l in _qr_round),
          "; ".join("%s -> %r" % (a[:20], b) for a, b, _v, _l in _qr_round if a != b)
          or "4/4, versions %s" % sorted({v for _a, _b, v, _l in _qr_round}))
    check("  and reports back the level it was asked for",
          all(l == want for (_t, _g, _v, l), want
              in zip(_qr_round, ("L", "M", "L", "L"))),
          str([l for _t, _g, _v, l in _qr_round]))

    # Every supported version, because the interleave tables differ per version
    # and an off-by-one block only shows up in the ones with two groups.
    _versions = {}
    for _n in (10, 30, 70, 120, 180, 230):
        _payload = ("AW" * 200)[:_n]
        try:
            _m = qr_mod.encode(_payload, "L")
        except qr_mod.QRError:
            continue
        _band, _side = _render_qr(_m, scale=4)
        _got = qr_dec.decode(_band, _side, _side)
        _versions[_got.get("version")] = (_got.get("text") == _payload)
    check("  across every version the encoder produces",
          _versions and all(_versions.values()),
          "versions %s" % sorted(k for k in _versions if k))

    # Reed-Solomon is the whole reason a QR survives a scuffed label, so it is
    # exercised rather than assumed: flip whole modules and require recovery.
    _m = qr_mod.encode("ONT,BATCH01,900001", "M")
    _band, _side = _render_qr(_m, scale=5)
    _damaged = bytearray(_band)
    _rnd4 = _random.Random(17)
    for _ in range(6):
        _mr, _mc = _rnd4.randrange(len(_m)), _rnd4.randrange(len(_m))
        _fill = 245 if _m[_mr][_mc] else 25
        for _y in range((_mr + 4) * 5, (_mr + 5) * 5):
            for _x in range((_mc + 4) * 5, (_mc + 5) * 5):
                _damaged[_y * _side + _x] = _fill
    _fixed = qr_dec.decode(bytes(_damaged), _side, _side)
    check("  and its error correction repairs a damaged symbol",
          _fixed.get("text") == "ONT,BATCH01,900001",
          "%s, %s codeword(s) repaired"
          % (_fixed.get("text") or _fixed.get("reason"),
             _fixed.get("corrected_codewords")))

    # The two format copies must carry the SAME value. The decoder deliberately
    # accepts either -- that redundancy is what survives a scuffed corner -- so
    # a round trip cannot notice when the encoder writes them differently. This
    # reads them straight off the matrix and compares.
    _fm = qr_mod.encode("ONT,BATCH01,900001", "M")
    _copy_a, _copy_b = qr_dec._format_candidates(_fm)
    check("  the QR encoder writes both format copies identically",
          _copy_a == _copy_b,
          "copy 1 = %s, copy 2 = %s" % (bin(_copy_a), bin(_copy_b)))

    _rnd5 = _random.Random(29)
    _qr_invented = 0
    for _ in range(25):
        _side = 160
        _noise = bytes(_rnd5.randrange(256) for _ in range(_side * _side))
        if qr_dec.decode(_noise, _side, _side).get("ok"):
            _qr_invented += 1
    check("  and random noise never produces a QR", _qr_invented == 0,
          f"{_qr_invented}/25")

    check("EAN-13: a 12-digit body gains its check digit",
          bc_mod.normalise("789076542345") == "7890765423458",
          bc_mod.normalise("789076542345"))
    check("  a complete UPC-A becomes an EAN-13 instead",
          bc_mod.normalise("012345678905") == "0012345678905",
          bc_mod.normalise("012345678905"))
    check("  a wrong check digit is refused", not bc_mod.can_render("7890765423450"))
    check("  a non-retail product number is refused", not bc_mod.can_render("900001"))
    bar = bc_mod.to_svg("7890765423458")
    check("  it renders as SVG", bar.startswith("<svg") and "</svg>" in bar,
          f"{len(bar)} bytes")

    # 11i) the defects the full-system audit found, each with a regression test
    check("a truncated code is only matched when its check digit proves it",
          db._code_variants("09000019") == ["090000195", "9000019"],
          str(db._code_variants("09000019")))
    check("  so an unrelated code no longer lands on a real product",
          db.resolve_productno("09000019") == (None, None),
          str(db.resolve_productno("09000019")))
    check("  while the documented EAN-13 case still resolves",
          db.resolve_productno("7890765423458")[0] == "789076542345",
          str(db.resolve_productno("7890765423458")))

    # One check-digit rule, not two. db.py used to carry its own copy that
    # anchored the alternating weights from the left, which is right for an
    # even-length body and wrong for an odd-length one -- so it agreed on every
    # 12-digit EAN-13 body and disagreed on four fifths of the 7- and 11-digit
    # bodies _code_variants feeds it. Both vectors above happen to be cases
    # where the two rules agree, which is exactly why it survived.
    check("  the resolver and the encoder share one check-digit rule",
          db._ean_check_digit is bc_mod.check_digit)
    check("  which is right for an odd-length body, not just an even one",
          db._ean_check_digit("03600029145") == "2",
          f'03600029145 -> {db._ean_check_digit("03600029145")}, printed 2')
    check("  so a UPC-A body is offered as a variant of its EAN-13",
          "03600029145" in db._code_variants("036000291452"),
          str(db._code_variants("036000291452")))
    # Two vectors chosen because the left-anchored rule and the real one give
    # OPPOSITE answers for them, one in each direction. Under the old rule the
    # first grew a variant it had no right to -- the 09000019 failure again --
    # and the second lost one it should have had.
    # str.isdigit() is True for superscripts, which int() then refuses. Every
    # guard in front of the check digit used it, so a product number pasted with
    # a footnote marker still attached reached int() and raised ValueError from
    # inside a database write -- the row committed and the request returned 500,
    # after which /api/codes raised for every product.
    _sup = "1234567²"
    check("  a superscript digit is not mistaken for a digit",
          _sup.isdigit() and not bc_mod.is_numeric(_sup),
          f"isdigit={_sup.isdigit()}, is_numeric={bc_mod.is_numeric(_sup)}")
    check("  so it is refused rather than crashing a check-digit sum",
          db._code_variants(_sup) == [] and not bc_mod.can_render(_sup))
    try:
        bc_mod.check_digit(_sup)
        check("  and the check digit itself refuses it in the module's own way", False)
    except bc_mod.BarcodeError:
        check("  and the check digit itself refuses it in the module's own way", True)
    except Exception as _e:                  # noqa: BLE001
        check("  and the check digit itself refuses it in the module's own way",
              False, type(_e).__name__)

    check("  a truncation the wrong rule would have admitted is still refused",
          "1000000" not in db._code_variants("10000009"),
          str(db._code_variants("10000009")))
    check("  and one it would have refused is now offered",
          "1000000" in db._code_variants("10000007"),
          str(db._code_variants("10000007")))

    orchestrator.reset_duplicate_state()
    db.create_product("Undo Alpha", "900801", "B1", 0, db.UNCATEGORISED, 0)
    db.create_product("Undo Beta", "900802", "B1", 0, db.UNCATEGORISED, 0)
    ra = orchestrator.process_scan("Undo Alpha,B1,900801", "IN", "manual")
    rb = orchestrator.process_scan("Undo Beta,B1,900802", "IN", "manual")
    check("a scan can be named for undo", bool(ra.get("log_id")), str(ra.get("log_id")))
    ok, msg, _ = db.undo_last(ra["log_id"])
    check("  undo reverses the named scan, not the newest",
          db.product_total("900801") == 0 and db.product_total("900802") == 1,
          f"alpha={db.product_total('900801')} beta={db.product_total('900802')}")

    actor = {"id": 99, "username": "tester"}
    db.adjust_stock("900802", "B1", 4, actor=actor)
    check("manual corrections record who made them",
          db.search_logs("900802")[0]["username"] == "tester",
          db.search_logs("900802")[0]["username"])

    audit = agent_reg.get("Audit Agent").run({})
    check("the audit reconciles a hand-created product instead of skipping it",
          audit.data["checks_run"] == 5, str(audit.data["checks_run"]))
    import sqlite3 as _sq
    _c = _sq.connect(tmp)
    _c.execute("UPDATE items SET qty = 77 WHERE productno = '900802'")
    _c.commit(); _c.close()
    audit = agent_reg.get("Audit Agent").run({})
    check("  and it CATCHES stock that no longer matches the log",
          any(f["check"] == "reconciliation" for f in audit.data["findings"]),
          f"{audit.data['errors']} error(s)")
    db.adjust_stock("900802", "B1", 4, actor=actor)      # put it back

    check("a rejection that is not an unresolved code says so",
          orchestrator.process_scan("Undo Alpha,B1,900801", "OUT", "manual")
              .get("unresolved") is False)

    # 11i2) the 1-D barcode decoder: reads what the encoder draws, and above
    # all never reads it as something else.
    from core import barcode_decode
    from core.barcode import modules as _modules, normalise as _normalise

    def _render(bits, px, height=32, quiet=10, blur=1, tilt=0.0, noise=0, seed=1,
                ink=0):
        """A module string as a grayscale band, degraded the way a camera does.

        ``ink`` is the printing bias in pixels: positive lays too much down, so
        every bar grows and every space shrinks; negative is a worn print head
        or an eroded thermal label. It is the one degradation that survives the
        matcher's scale-free normalisation, because it moves bars and spaces in
        opposite directions instead of scaling both.
        """
        rnd = _random.Random(seed)
        full = "0" * quiet + bits + "0" * quiet
        if ink:
            row = []
            for x in range(len(full) * px):
                edges = []
                for probe in (x - ink, x, x + ink):
                    i = int(probe // px)
                    edges.append(0 <= i < len(full) and full[i] == "1")
                dark = all(edges) if ink < 0 else any(edges)
                row.append(0 if dark else 255)
        else:
            row = [0 if b == "1" else 255 for b in full for _ in range(px)]
        if blur:
            row = [sum(row[max(0, i - blur):i + blur + 1])
                   // len(row[max(0, i - blur):i + blur + 1])
                   for i in range(len(row))]
        band = bytearray()
        for _y in range(height):
            for i, value in enumerate(row):
                v = int(value * (1.0 - tilt * (i / float(len(row)))))
                if noise:
                    v += rnd.randint(-noise, noise)
                band.append(max(0, min(255, v)))
        return bytes(band), len(row)

    _code = _normalise("7890765423458")
    _, _bits = _modules(_code)

    band, w = _render(_bits, px=5)
    got = barcode_decode.decode_band(band, w, 32)
    check("the barcode decoder reads what the barcode encoder drew",
          got["code"] == _code, f"{got.get('code')} ({got.get('symbology')})")
    check("  and reports how many pixels per module it had",
          got.get("module_pixels", 0) >= 4, str(got.get("module_pixels")))

    band, w = _render(_bits, px=5, blur=2, tilt=0.35, noise=6)
    check("  it still reads through blur, uneven lighting and noise",
          barcode_decode.decode_band(band, w, 32)["code"] == _code)

    band, w = _render(_bits, px=5)
    reversed_band = bytearray()
    for y in range(32):
        reversed_band.extend(band[y * w:(y + 1) * w][::-1])
    check("  and reads a label presented upside down",
          barcode_decode.decode_band(bytes(reversed_band), w, 32)["code"] == _code)

    # THE property that matters. A wrong product number is worse than no read:
    # it moves stock onto the wrong record and the log then shows the wrong
    # number, so nothing looks amiss afterwards.
    _rnd = _random.Random(11)
    invented = 0
    for _ in range(40):
        noise_band = bytes(_rnd.randint(0, 255) for _ in range(800 * 12))
        if barcode_decode.decode_band(noise_band, 800, 12).get("code"):
            invented += 1
    check("random noise never produces a barcode", invented == 0,
          f"{invented}/40 invented a code")

    # Below the resolution floor it must MISS, not guess. This is the whole
    # reason the server decoder exists: the browser's downscaled frame sits
    # here, and a decoder that guessed at this resolution would be worse than
    # one that fails.
    band, w = _render(_bits, px=1, blur=1)
    tiny = barcode_decode.decode_band(band, w, 32)
    check("  a frame below the resolution floor misses rather than guesses",
          tiny.get("code") in (None, _code),
          f"{tiny.get('code') or 'clean miss'}")

    # An EAN-8 pattern genuinely occurs inside an EAN-13's bars, check digit and
    # all. Without the quiet-zone rule this returned 23456129 for 0012345678905.
    upc = _normalise("0012345678905")
    _, upc_bits = _modules(upc)
    band, w = _render(upc_bits, px=3, blur=1, tilt=0.35, noise=6, seed=2)
    inner = barcode_decode.decode_band(band, w, 32)
    check("  an EAN-8 found inside an EAN-13 is refused, not returned",
          inner.get("code") in (None, upc),
          f"{inner.get('code') or 'clean miss'}")

    check("  the decoder shares the encoder's tables rather than copying them",
          barcode_decode._L_ODD[0] == [3, 2, 1, 1],
          str(barcode_decode._L_ODD[0]))

    # A cut through an EAN-13's bars used to supply the very quiet zone the
    # embedded EAN-8 needed: the band edge counted as clear space, so a fragment
    # came back as a complete, check-digit-valid, WRONG product number with
    # every scanline agreeing. The browser sends a band spanning the full frame
    # width, so the band edge is the frame edge and this was reachable in normal
    # use. An EAN-8 must now show a real quiet zone on both sides.
    # NOTE: do not name the loop variable _code -- the close-up checks below
    # still read the outer _code, and shadowing it made them silently compare
    # against whatever this loop happened to end on.
    _cut_misreads = []
    _cut_frames = 0
    for _victim in ("0499574977861", "0100000733103", "7890765423458"):
        _want = _normalise(_victim)
        _, _cut_bits = _modules(_want)
        for _cut in (6, 13, 20):
            for _px in (3, 5, 8):
                band, w = _render(_cut_bits, px=_px, quiet=0)
                rows = [band[y * w:(y + 1) * w] for y in range(32)]
                # Both edges, separately. The left cut exercises _quiet_before
                # and the right cut exercises _quiet_after; only one of the two
                # allow_edge=False arguments is reachable from each.
                for _side in ("left", "right"):
                    trimmed = ([r[_cut * _px:] for r in rows] if _side == "left"
                               else [r[:w - _cut * _px] for r in rows])
                    w2 = len(trimmed[0])
                    if w2 < 80:
                        continue
                    _cut_frames += 1
                    got = barcode_decode.decode_band(b"".join(trimmed), w2, 32).get("code")
                    if got and got != _want:
                        _cut_misreads.append(f"{_victim} {_side}@{_cut}/{_px}px -> {got}")
    check("  a frame cut through an EAN-13 never reads as an EAN-8",
          not _cut_misreads,
          "; ".join(_cut_misreads[:3]) or f"{_cut_frames} cut frames, none misread")

    # The tightened rule must not have closed the front door. An EAN-8 with the
    # clear space it is entitled to still has to read, or the fix traded a
    # misread for a whole symbology.
    # core/barcode.py draws EAN-13 only, so the eight-digit symbol is assembled
    # here from the same shared tables the decoder reads.
    _e8 = "96385074"
    _e8_bits = "".join(
        [bc_mod.GUARD]
        + [bc_mod._LEFT_ODD[int(d)] for d in _e8[:4]]
        + [bc_mod.CENTRE]
        + [bc_mod._RIGHT[int(d)] for d in _e8[4:]]
        + [bc_mod.GUARD])
    _e8_ok = 0
    for _px in (3, 4, 6, 10):
        band, w = _render(_e8_bits, px=_px, quiet=10)
        if barcode_decode.decode_band(band, w, 32).get("code") == _e8:
            _e8_ok += 1
    check("  and a properly quiet EAN-8 still reads",
          _e8_ok == 4, f"{_e8_ok}/4 at 3, 4, 6 and 10 px per module")

    # The other half of the same rule, and the cost of it stated out loud. An
    # EAN-8 whose trailing quiet zone is cut away by the edge of the band is
    # REFUSED, not guessed. That is the deliberate trade: the left-hand version
    # of this allowance was returning well-formed wrong product numbers, so
    # neither side gets it. If someone restores the allowance to make cropped
    # labels read, this check fails and makes them argue for it.
    band, w = _render(_e8_bits, px=5, quiet=10)
    _tail = 10 * 5                       # exactly the trailing quiet zone
    _rows = [band[y * w:(y + 1) * w][:w - _tail] for y in range(32)]
    _cropped = barcode_decode.decode_band(b"".join(_rows), w - _tail, 32)
    check("  while an EAN-8 cropped at the trailing edge is refused, not guessed",
          _cropped.get("code") is None, str(_cropped.get("code") or "refused"))

    # Close-up frames used to be WORSE than distant ones. A 40-pixel threshold
    # block that fits inside one bar has no real contrast, but sensor noise
    # gives it an apparent spread wide enough to clear a fixed floor, so the
    # block invented a threshold from noise and shredded solid bars into
    # hundreds of phantom runs. Measured: a 61-run barcode became 493 runs.
    # The floor is a share of the scanline's own contrast now, so this band
    # must read at least as well as the coarse one.
    _band, _w = _render(_bits, px=14, blur=1, noise=24)
    _close = barcode_decode.decode_band(_band, _w, 32)
    check("  a close-up frame reads rather than shattering into noise",
          _close.get("code") == _code,
          f"{_close.get('code') or 'miss'} at {_close.get('module_pixels')} px/module")
    _band, _w = _render(_bits, px=20, blur=1, noise=18, tilt=0.3)
    check("  and so does a very close, noisy, unevenly lit one",
          barcode_decode.decode_band(_band, _w, 32).get("code") == _code)

    # A worn print head takes ink off every bar and gives it to every space, and
    # an over-inked one does the reverse. Scale-free matching does not see it --
    # the runs still total correctly -- so a [3,2,1,1] digit drifts toward
    # [2,2,2,1], which is a different digit. Measured before the correction:
    # digit acceptance fell from 500 attempts in 600 to 50 in 175 and the label
    # stopped reading. The bias belongs to the printing rather than the digit,
    # so it is measured once from the eleven runs that are one module wide by
    # definition, and removed.
    # Up to about four tenths of a module of bias, which is what
    # MAX_INK_BIAS_SHARE allows; past that the narrow bars are more gone than
    # present and no width correction can bring them back.
    _ink_reads = []
    for _bias in (-2, -1, 1, 2):                # pixels, at 10 px per module
        band, w = _render(_bits, px=10, blur=1, ink=_bias)
        _ink_reads.append(
            barcode_decode.decode_band(band, w, 32).get("code") == _code)
    check("  a label whose bars print thin or fat still reads",
          all(_ink_reads),
          "%d/4 at up to 0.4 module of printing bias, both directions"
          % sum(1 for r in _ink_reads if r))

    # And the correction must not invent a reading where there is none.
    _rnd2 = _random.Random(23)
    _invented = 0
    for _ in range(30):
        noise_band = bytes(_rnd2.randint(0, 255) for _ in range(700 * 10))
        if barcode_decode.decode_band(noise_band, 700, 10).get("code"):
            _invented += 1
    check("  and correcting for it still never invents a barcode",
          _invented == 0, f"{_invented}/30")

    # 11i3) Code 128: the symbology the shelf labels in labels/ actually use.
    from core import code128 as _c128
    from core import image as _image

    # The 107-row table is the whole decoder. One mistyped width in it would be
    # invisible in normal use and would misread one product number in a hundred,
    # so it is checked against the specification's own invariants instead of
    # being trusted: every symbol is six runs totalling eleven modules, the stop
    # is seven totalling thirteen, no two patterns are alike, and -- the one
    # that catches a single-digit typo -- the bars of every symbol sum to an
    # EVEN number of modules. That is Code 128's own self-checking property.
    _bad_rows = []
    for _value, _pattern in enumerate(_c128.PATTERNS):
        _want_len, _want_sum = (7, 13) if _value == _c128.STOP else (6, 11)
        if len(_pattern) != _want_len or sum(_pattern) != _want_sum:
            _bad_rows.append("%d: %s wrong shape" % (_value, _pattern))
        elif _value != _c128.STOP and sum(_pattern[0::2]) % 2:
            _bad_rows.append("%d: %s odd bar parity" % (_value, _pattern))
        elif min(_pattern) < 1 or max(_pattern) > 4:
            _bad_rows.append("%d: %s width out of range" % (_value, _pattern))
    check("the Code 128 table satisfies the specification's own invariants",
          len(_c128.PATTERNS) == 107 and not _bad_rows,
          "; ".join(_bad_rows[:3]) or "107 rows, all 11 modules, all bars even")
    check("  and no two symbols share a pattern",
          len({tuple(p) for p in _c128.PATTERNS}) == 107)

    # Ground truth, and the strongest test here: two label files nobody in this
    # project drew. The Code 128 one carries the same product number as the
    # EAN-13 one, which is what makes it a cross-check rather than a round trip.
    _c128_files = {}
    for _name, _want in (("martini-code128.png", "789076542345"),
                         ("ont-code128.png", "900001")):
        _path = os.path.join(base, "labels", _name)
        try:
            _px, _w, _h = _image.load_gray(_path)
            _c128_files[_name] = barcode_decode.decode_band(_px, _w, _h)
        except Exception as _e:                  # noqa: BLE001
            _c128_files[_name] = {"error": str(_e)}
    _martini = _c128_files.get("martini-code128.png", {})
    check("a real Code 128 label file decodes",
          _martini.get("code") == "789076542345"
          and _martini.get("symbology") == "CODE-128",
          f"{_martini.get('code')} at {_martini.get('module_pixels')} px/module")
    check("  and carries the same product number as the EAN-13 label beside it",
          _martini.get("code") == _normalise("7890765423458")[:-1],
          "Code 128 says %s; EAN-13 says %s"
          % (_martini.get("code"), _normalise("7890765423458")))
    _ont = _c128_files.get("ont-code128.png", {})
    check("  and the second real label decodes to a known product number",
          _ont.get("code") == "900001", str(_ont.get("code")))

    # Round trip through the renderer, including the subsets and the digit pair
    # encoding, which is a different code path from the letters.
    _c128_round = []
    for _text in ("SHB011", "WIL001", "ONT-4421", "900001", "012345678905"):
        band, w = _render(_c128.modules(_text, quiet=10), px=6)
        _got = barcode_decode.decode_band(band, w, 32)
        _c128_round.append((_text, _got.get("code"), _got.get("symbology")))
    check("  Code 128 round-trips letters, digits and punctuation",
          all(t == g and sym == "CODE-128" for t, g, sym in _c128_round),
          "; ".join("%s->%s" % (t, g) for t, g, _ in _c128_round if t != g)
          or "5/5")

    # The checksum is the only thing standing between a corrupted reading and a
    # wrong product number, so it has to actually reject.
    _sym = _c128.values("SHB011")
    check("  the Code 128 checksum accepts a correct symbol run",
          _c128.checksum_ok(_sym[:-1]))
    _broken = list(_sym[:-1])
    _broken[2] = (_broken[2] + 1) % 103
    check("  and rejects one with a symbol changed",
          not _c128.checksum_ok(_broken))

    # Variable length means a fragment of a long Code 128 can wear the shape of
    # a short one, exactly as an EAN-8 does inside an EAN-13. The band edge is
    # therefore not allowed to stand in for a quiet zone.
    _c128_bits = _c128.modules("WAREHOUSE-4421", quiet=10)
    _frag_wrong = []
    for _cut in (11, 22, 33, 44):
        band, w = _render(_c128_bits, px=5)
        _rows = [band[y * w:(y + 1) * w] for y in range(32)]
        for _side in ("left", "right"):
            _trim = ([r[_cut * 5:] for r in _rows] if _side == "left"
                     else [r[:w - _cut * 5] for r in _rows])
            if len(_trim[0]) < 120:
                continue
            _got = barcode_decode.decode_band(
                b"".join(_trim), len(_trim[0]), 32).get("code")
            if _got and _got != "WAREHOUSE-4421":
                _frag_wrong.append("%s@%d->%s" % (_side, _cut, _got))
    check("  and a cut Code 128 is refused rather than read short",
          not _frag_wrong, "; ".join(_frag_wrong[:3]) or "8 cut frames, none misread")

    # The rule that does that work, pinned directly: with the symbol running to
    # the very edge of the band there is no clear space to observe, and the edge
    # is not allowed to stand in for it. Three modules is enough; two is not.
    # _render adds a quiet zone of its own, so it is told not to: the point is
    # to control the clear space exactly, not to have it supplied twice.
    _quiet_reads = {}
    for _q in (3, 0):
        band, w = _render(_c128.modules("SHB011", quiet=_q), px=6, quiet=0)
        _quiet_reads[_q] = barcode_decode.decode_band(band, w, 32).get("code")
    check("  a Code 128 with clear space either side reads",
          _quiet_reads[3] == "SHB011", str(_quiet_reads[3]))
    check("  and one running to the edge of the band is refused, not guessed",
          _quiet_reads[0] is None, str(_quiet_reads[0] or "refused"))

    # This one pins an intention rather than a behaviour, and says so. The
    # raised agreement count for Code 128 is a probabilistic defence against a
    # checksum that is weaker than EAN-13's structure; no single frame proves it
    # works, so there is no test that fails when it is lowered. What CAN be
    # asserted is that Code 128 is still held to a higher bar than EAN-13, which
    # is the decision someone might undo without realising what it was for.
    check("  Code 128 is held to more agreeing scanlines than EAN-13",
          barcode_decode.MIN_AGREEING_LINES_CODE128
          > barcode_decode.MIN_AGREEING_LINES,
          "%d vs %d" % (barcode_decode.MIN_AGREEING_LINES_CODE128,
                        barcode_decode.MIN_AGREEING_LINES))

    _rnd3 = _random.Random(5)
    _c128_invented = 0
    for _ in range(40):
        _noise = bytes(_rnd3.randint(0, 255) for _ in range(900 * 12))
        if barcode_decode.decode_band(_noise, 900, 12).get("code"):
            _c128_invented += 1
    check("  and random noise still never produces a barcode of any symbology",
          _c128_invented == 0, f"{_c128_invented}/40")

    # 11j) cameras: registration, roles, ordering and measurement.
    #
    # This whole subsystem had a store, eight routes and no tests at all, which
    # is exactly the state golden rule 10 exists to prevent.
    STN = "stn-selftest"
    ok, msg, cam_a = camera_store.add_camera(
        STN, "Built-in webcam", device_id="dev-a", device_label="Integrated Camera",
        role="primary", station_label="Self-test bench", actor=actor)
    check("a camera can be registered against a station", ok and cam_a["role"] == "primary", msg)

    ok, msg, cam_b = camera_store.add_camera(
        STN, "USB scanner cam", device_id="dev-b", device_label="HD Pro Webcam",
        role="backup", actor=actor)
    check("  a second camera registers as the backup", ok and cam_b["role"] == "backup", msg)

    ok, msg, _ = camera_store.add_camera(STN, "Duplicate", device_id="dev-a", actor=actor)
    check("  the same device cannot be registered twice", not ok, msg)

    ok, msg, _ = camera_store.add_camera(STN, "No id", device_id="", actor=actor)
    check("  a device camera without an id is refused", not ok, msg)

    ok, msg, _ = camera_store.add_camera(
        STN, "IP cam", kind="network", stream_url="rtsp://192.168.1.9/stream", actor=actor)
    check("  an rtsp:// stream is refused, because no browser can play one", not ok, msg)

    ok, msg, cam_net = camera_store.add_camera(
        STN, "Dock camera", kind="network",
        stream_url="http://192.168.1.9/snapshot.jpg", actor=actor)
    check("  an http:// network camera is accepted", ok, msg)

    # Only one primary per station: promoting the second must demote the first.
    ok, msg, _ = camera_store.update_camera(cam_b["id"], role="primary", actor=actor)
    roles = {c["name"]: c["role"] for c in camera_store.list_cameras(STN)}
    check("promoting a camera demotes the previous primary",
          ok and roles["USB scanner cam"] == "primary"
          and roles["Built-in webcam"] == "backup", str(roles))
    camera_store.update_camera(cam_a["id"], role="primary", actor=actor)

    # A camera edit now records who made it. It used to accept an actor and
    # throw it away, making it the one write in the system with no name on it.
    edited = camera_store.get_camera(cam_a["id"])
    check("  a camera edit records who made it", edited["updated_by"] == actor["username"],
          edited["updated_by"] or "(nobody)")

    # Deliberately give the BACKUP the lower position, so the primary can only
    # come first if the role itself is what orders them. Previously the primary
    # was also at position 0, and the check passed with the role term removed.
    camera_store.update_camera(cam_b["id"], position=0, actor=actor)
    camera_store.update_camera(cam_a["id"], position=50, actor=actor)
    order = camera_store.scanner_order(STN)
    check("the scanner order puts the primary first, even when placed last",
          order and order[0]["name"] == "Built-in webcam"
          and order[0]["position"] > order[1]["position"],
          " -> ".join("%s(pos %d)" % (c["name"], c["position"]) for c in order))

    camera_store.update_camera(cam_net["id"], role="disabled", actor=actor)
    order = camera_store.scanner_order(STN)
    excluded = camera_store.excluded(STN)
    check("  a disabled camera leaves the scan order",
          all(c["name"] != "Dock camera" for c in order) and len(excluded) == 1,
          f"{len(order)} in order, {len(excluded)} excluded")
    check("  but is still reported, so the browser does not re-offer it",
          excluded[0]["name"] == "Dock camera", excluded[0]["name"])

    # Scoring: the grade has to reflect what a camera can actually do.
    good_score, good_grade = camera_store.score_result(1920, 1080, 15, 0.60, 800)
    bad_score, bad_grade = camera_store.score_result(640, 480, 5, 0.0, None)
    check("a sharp camera that decodes scores well",
          good_grade == "excellent" and good_score >= 80, f"{good_score}/100 {good_grade}")
    check("  one that never decodes is graded unusable",
          bad_grade == "unusable" and bad_score < 35, f"{bad_score}/100 {bad_grade}")

    ok, msg, result = camera_store.record_test(cam_b["id"], {
        "ok": True, "width": 1280, "height": 720, "fps": 12,
        "frames": 100, "decodes": 45, "first_ms": 900,
        "formats": ["EAN_13"], "engine": "html5-qrcode",
    }, actor=actor)
    check("a camera measurement is scored and stored",
          ok and result["decode_rate"] == 0.45
          # 1280x720 -> resolution 0.75, decode 0.45/0.60 -> 0.75, speed 0.967,
          # fps 12/15 -> 0.8. Asserting the number, not merely that a grade
          # exists: "grade in GRADES" was true whatever the scorer returned.
          and result["score"] == 79 and result["grade"] == "good",
          f"{result['score']}/100 {result['grade']}")

    # A client that miscounts must not be able to score a perfect camera.
    ok, _, impossible = camera_store.record_test(cam_b["id"], {
        "ok": True, "width": 1920, "height": 1080, "fps": 15,
        "frames": 10, "decodes": 60, "first_ms": 500,
    }, actor=actor)
    check("a decode rate over 100% is impossible, not a perfect score",
          ok and impossible["decode_rate"] <= 1.0 and impossible["frames"] >= 60,
          f"rate {impossible['decode_rate']}, frames {impossible['frames']}")

    ok, _, failed = camera_store.record_test(cam_b["id"], {
        "ok": False, "error": "NotReadableError"}, actor=actor)
    check("  a camera that would not open scores zero",
          ok and failed["score"] == 0 and failed["grade"] == "unusable")
    check("  and the earlier results are kept, not overwritten",
          len(camera_store.test_history(cam_b["id"])) == 3,
          f"{len(camera_store.test_history(cam_b['id']))} results")

    summary_now = camera_store.summary(STN)
    check("the station summary reports a primary and a backup",
          summary_now["has_primary"] and summary_now["has_backup"],
          str({k: summary_now[k] for k in ("total", "enabled", "tested", "usable")}))

    # A station only ever sees its own cameras: a deviceId from another machine
    # identifies nothing here, which is the whole reason for the station column.
    camera_store.add_camera("stn-other", "Someone else's camera",
                            device_id="dev-a", actor=actor)
    check("cameras are scoped to the machine that can see them",
          len(camera_store.list_cameras(STN)) == 3
          and len(camera_store.list_cameras("stn-other")) == 1,
          f"{len(camera_store.list_cameras(STN))} here")

    # 11k) the Vision Agent decides failover, and now knows about roles.
    vision = agent_reg.get("Vision Agent")
    two = [{"label": "Built-in", "role": "primary", "grade": "marginal"},
           {"label": "USB cam", "role": "backup", "grade": "excellent"}]

    d = vision.run({"symptom": "healthy", "cameras": two, "active_index": 0})
    check("a healthy camera is left alone", d.data["action"] == "keep")

    d = vision.run({"symptom": "no_decode", "cameras": two, "active_index": 0,
                    "idle_seconds": 3, "patience": 12})
    check("  a short pause is not treated as a failure",
          d.data["action"] == "keep", f"{d.confidence}")

    d = vision.run({"symptom": "track_ended", "cameras": two, "active_index": 0,
                    "idle_seconds": 1})
    check("an unplugged camera fails over at once",
          d.data["action"] == "switch" and d.data["target"] == 1,
          d.rationale[0] if d.rationale else "")

    # The designated backup wins even when a better-graded camera is listed
    # earlier -- that is what the designation is for.
    three = [{"label": "Built-in", "role": "primary"},
             {"label": "Spare", "role": "", "grade": "excellent"},
             {"label": "USB cam", "role": "backup", "grade": "good"}]
    d = vision.run({"symptom": "start_failed", "cameras": three, "active_index": 0})
    check("the camera marked as backup is preferred",
          d.data["action"] == "switch" and d.data["target_label"] == "USB cam",
          d.data.get("target_label"))

    # A camera that is not plugged in is never proposed.
    absent = [{"label": "Built-in", "role": "primary"},
              {"label": "USB cam", "role": "backup", "attached": False}]
    d = vision.run({"symptom": "track_ended", "cameras": absent, "active_index": 0})
    check("  a configured but unplugged backup is not proposed",
          d.data["action"] == "fallback",
          " ".join(d.rationale)[:70])

    d = vision.run({"symptom": "track_ended", "cameras": two, "active_index": 0,
                    "tried": [1]})
    check("  a camera that already failed is not recommended twice",
          d.data["action"] == "fallback")

    # A camera switched off in the settings must never be proposed, and the
    # reason must say so rather than claiming everything was tried.
    off = [{"label": "Main", "role": "primary"},
           {"label": "Spare", "role": "disabled"}]
    d = vision.run({"symptom": "track_ended", "cameras": off, "active_index": 0})
    check("a camera switched off is never proposed",
          d.data["action"] == "fallback"
          and any("switched off" in r for r in d.rationale),
          " ".join(d.rationale)[:80])

    d = vision.run({"symptom": "start_failed", "cameras": [{"label": "Only one"}],
                    "active_index": 0})
    check("  with one camera it falls back to photo and manual entry",
          d.data["action"] == "fallback" and d.data["advice"] == "switch_input")

    # The decode-stall path, past the patience window. Every earlier case used
    # track_ended or start_failed, which are FATAL and skip the patience gate
    # entirely -- so the symptom the watchdog actually raises was never once
    # tested through to a switch.
    d = vision.run({"symptom": "no_decode", "cameras": two, "active_index": 0,
                    "idle_seconds": 30, "patience": 12, "decodes": 0})
    check("a camera that decodes nothing past the patience window fails over",
          d.data["action"] == "switch" and d.data["target"] == 1,
          " ".join(d.rationale)[:80])
    check("  and says it has never decoded, rather than that it stopped",
          any("never decoded" in r for r in d.rationale))

    d = vision.run({"symptom": "stalled", "cameras": two, "active_index": 0,
                    "idle_seconds": 30, "patience": 12})
    check("  a stalled camera past the window also fails over",
          d.data["action"] == "switch")

    # A designated primary must outrank a camera nobody registered. It used to
    # sort last, so recovering the primary lost to an unregistered IR sensor.
    recovered = [{"label": "USB backup", "role": "backup"},
                 {"label": "IR sensor", "role": "", "grade": "unusable"},
                 {"label": "Main camera", "role": "primary", "grade": "excellent"}]
    d = vision.run({"symptom": "track_ended", "cameras": recovered, "active_index": 0})
    check("a registered primary is preferred over an unregistered camera",
          d.data["target_label"] == "Main camera", d.data.get("target_label"))

    # A network camera cannot be opened by any browser, so the advice must not
    # be "plug it back in".
    net = [{"label": "Main camera", "role": "primary"},
           {"label": "Dock camera", "role": "backup", "attached": False, "kind": "network"}]
    d = vision.run({"symptom": "track_ended", "cameras": net, "active_index": 0})
    check("  an IP camera is not described as unplugged",
          d.data["action"] == "fallback"
          and any("network camera" in r for r in d.rationale)
          and not any("Reconnecting" in r for r in d.rationale),
          " ".join(d.rationale)[-90:])

    # 11l) the market comparison: measured for us, attributed for everyone else.
    import re as _re_market
    import market
    mkt = market.market_comparison(None)
    check("the market comparison is assembled",
          len(mkt["dimensions"]) >= 20 and len(mkt["tiers"]) >= 5,
          f"{len(mkt['dimensions'])} dimensions across {len(mkt['tiers'])} tiers")
    check("  it reports losses as well as wins",
          mkt["headline"]["losses"] >= 4 and mkt["headline"]["wins"] > 0,
          f"{mkt['headline']['wins']} ahead, {mkt['headline']['losses']} behind, "
          f"{mkt['headline']['scope']} scope")
    check("  every dimension covers every tier",
          all(set(d["tiers"]) == {t["key"] for t in mkt["tiers"]}
              for d in mkt["dimensions"]))
    check("  every dimension cites its evidence and says why it matters",
          all(d["ours_evidence"] and d["why_it_matters"] for d in mkt["dimensions"]))
    check("  the agent count comes from the registry, not a literal",
          mkt["headline"]["agents"] == len(roster()),
          f"{mkt['headline']['agents']} agents")
    # These two were silently wrong. `strategies` sat behind a bare except that
    # swallowed an AttributeError and fell back to the number we hoped for, and
    # a check count was typed in and drifted the day a check was added.
    check("  the strategy count comes from the agent, not a fallback literal",
          mkt["headline"]["strategies"]
          == len(agent_reg.get("Recovery Agent").STRATEGIES),
          f"{mkt['headline']['strategies']} strategies")
    check("  no check count is hard-coded into the comparison",
          not _re_market.search(r"\b\d+ checks\b",
                                open(os.path.join(base, "market.py"),
                                     encoding="utf-8").read()),
          "market.py states no check total")

    # Documented counts must match reality; they had all drifted.
    #
    # Both of these used to be incapable of failing. The agent one searched for
    # a pattern whose \b escapes had been written into a non-raw string and
    # were stored as literal backspace bytes, so it matched nothing ever and
    # `not any(...)` was permanently True. The route one asked whether the
    # number appeared ANYWHERE in the document, and a bare "64" turns up in a
    # byte count or an asset hash often enough that it passed for route counts
    # of 60, 70 and 80 against unmodified docs. Both now read the figure the
    # documentation actually states and compare it to the live one.
    from api import router as _router
    from agents import roster as _roster
    import re as _re
    # Anchored to `base`, not the working directory: every other file access in
    # this script already is, and this was the sole exception -- so running
    # `python verify.py` from anywhere but the project root skipped these.
    # Whatever markdown is actually shipped, discovered rather than listed.
    # Naming the files meant the self-test carried filenames that need not
    # exist, and a packaged copy without them would have died on the first
    # open() rather than on anything it was testing.
    docs = {name: open(os.path.join(base, name), encoding="utf-8").read()
            for name in sorted(os.listdir(base)) if name.endswith(".md")}
    n_agents, n_routes = len(_roster()), len(_router._routes)

    def _stated(pattern):
        """Every distinct count the documentation states, per file."""
        found = {}
        for doc_name, text in docs.items():
            hits = {int(m) for m in _re.findall(pattern, text)}
            if hits:
                found[doc_name] = hits
        return found

    agent_counts = _stated(r"(\d+) agents\b")
    check("documented agent count matches the registry",
          not docs or (bool(agent_counts)
                       and all(hits == {n_agents} for hits in agent_counts.values())),
          f"{n_agents} registered; docs say "
          + str({k: sorted(v) for k, v in agent_counts.items()}))

    route_counts = _stated(r"(\d+) (?:HTTP )?routes\b")
    check("documented route count matches the router",
          not docs or (bool(route_counts)
                       and all(hits == {n_routes} for hits in route_counts.values())),
          f"{n_routes} registered; docs say "
          + str({k: sorted(v) for k, v in route_counts.items()}))

    # The repair strategies are counted from the tuple decide() iterates, so a
    # strategy added without updating the docs is caught here.
    n_strategies = len(agent_reg.get("Recovery Agent").STRATEGIES)
    words = {7: "seven"}
    stated_strategies = _stated(r"(\d+) (?:ordered )?repair strateg")
    check("  documented repair-strategy count matches the agent",
          not docs or (
              bool(stated_strategies)
              and all(hits == {n_strategies} for hits in stated_strategies.values())
              # MVP.md spells it out in prose, so check the word too.
              and all(words.get(n_strategies, "") in t
                      for name, t in docs.items()
                      if "repair strateg" in t and str(n_strategies) not in t)),
          f"{n_strategies} strategies; docs say "
          + str({k: sorted(v) for k, v in stated_strategies.items()}))

    # 12) live HTTP smoke test on an ephemeral port, through real authentication
    try:
        import json
        import threading
        import urllib.request
        from http.server import ThreadingHTTPServer
        import app as appmod

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), appmod.Handler)
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base_url = f"http://127.0.0.1:{port}"

        def call(path, payload=None, cookie=None, method=None):
            data = json.dumps(payload).encode() if payload is not None else None
            headers = {"Content-Type": "application/json"}
            if cookie:
                headers["Cookie"] = cookie
            req = urllib.request.Request(base_url + path, data=data,
                                         headers=headers, method=method)
            try:
                resp = urllib.request.urlopen(req, timeout=8)
                return resp.status, json.loads(resp.read()), resp.headers
            except urllib.error.HTTPError as e:
                try:
                    return e.code, json.loads(e.read() or b"{}"), e.headers
                except ValueError:
                    return e.code, {}, e.headers
            except Exception as e:           # noqa: BLE001
                # A timeout, a reset, or a non-JSON body. Report it as this
                # request's failure rather than letting it collapse every
                # remaining HTTP check into one unattributable error.
                return 0, {"error": "%s: %s" % (e.__class__.__name__, e)}, {}

        status, _, _ = call("/api/scan", {"code": "ONT,B,900001", "mode": "IN"})
        check("an unauthenticated scan is refused", status == 401, f"HTTP {status}")

        status, body, headers = call("/api/auth/login",
                                     {"username": "admin", "password": "Warehouse#Admin1"})
        check("HTTP sign-in succeeds", status == 200 and body.get("ok"), f"HTTP {status}")
        cookie = (headers.get("Set-Cookie") or "").split(";")[0]
        check("  a session cookie is issued and is HttpOnly",
              cookie.startswith("aw_session=") and
              "HttpOnly" in (headers.get("Set-Cookie") or ""))

        status, body, _ = call("/api/scan",
                               {"code": "IPTV Device,B,900200", "mode": "IN"}, cookie)
        check("authenticated HTTP /api/scan -> IN",
              status == 200 and body.get("final") == "IN", body.get("category"))
        check("  the scan is attributed to the signed-in user",
              body.get("actor") == "admin", body.get("actor"))

        # The server-side barcode read, over real HTTP. The decoder itself was
        # covered above, but the route wrapping it was not exercised at all --
        # and it is the only route in the application that takes a raw body
        # rather than JSON, with its geometry in the query string, so nothing
        # else tests that path.
        def call_raw(path, blob, cookie=None):
            req = urllib.request.Request(
                base_url + path, data=blob, method="POST",
                headers={"Content-Type": "application/octet-stream",
                         **({"Cookie": cookie} if cookie else {})})
            try:
                resp = urllib.request.urlopen(req, timeout=8)
                return resp.status, json.loads(resp.read())
            except urllib.error.HTTPError as e:
                try:
                    return e.code, json.loads(e.read() or b"{}")
                except ValueError:
                    return e.code, {}
            except Exception as e:           # noqa: BLE001
                return 0, {"error": "%s: %s" % (e.__class__.__name__, e)}

        _hband, _hw = _render(_bits, px=5)
        status, _ = call_raw(f"/api/scan/decode-image?w={_hw}&h=32", _hband)
        check("an unauthenticated frame decode is refused", status == 401,
              f"HTTP {status}")

        status, body = call_raw(f"/api/scan/decode-image?w={_hw}&h=32", _hband, cookie)
        check("HTTP /api/scan/decode-image reads a barcode from a raw frame",
              status == 200 and body.get("decoded") and body.get("code") == _code,
              f"HTTP {status}: {body.get('code')} at {body.get('module_pixels')} px/module")
        check("  and names the engine that read it",
              body.get("engine") == "core.barcode_decode", str(body.get("engine")))

        _c128_band, _c128_w = _render(_c128.modules("SHB011", quiet=10), px=6)
        status, body = call_raw(
            f"/api/scan/decode-image?w={_c128_w}&h=32", _c128_band, cookie)
        check("  and reads a Code 128 over the same route",
              status == 200 and body.get("code") == "SHB011"
              and body.get("symbology") == "CODE-128",
              f"HTTP {status}: {body.get('code')} ({body.get('symbology')})")

        status, body = call_raw("/api/scan/decode-image", _hband, cookie)
        check("  a frame sent without its geometry is refused",
              status == 400, f"HTTP {status}")

        status, body = call_raw(f"/api/scan/decode-image?w={_hw}&h=999", _hband, cookie)
        check("  and a frame smaller than the geometry it claims is refused",
              status == 400, f"HTTP {status}")

        status, body, _ = call("/api/staff", cookie=cookie)
        check("HTTP staff list is reachable by an admin",
              status == 200 and body.get("ok"), f"{len(body.get('staff', []))} accounts")

        status, body, _ = call("/api/agents", cookie=cookie)
        check("HTTP agent roster is served",
              status == 200 and len(body.get("agents", [])) >= 13,
              f"{len(body.get('agents', []))} agents")

        status, body, _ = call("/api/scan/recover",
                               {"code": "  8901234567890\r\n"}, cookie)
        check("HTTP recovery endpoint answers", status == 200 and "candidates" in body,
              body.get("strategy"))

        status, body, _ = call("/api/report/comparison", cookie=cookie)
        check("HTTP system-comparison report is served",
              status == 200 and "headline" in body.get("comparison", {}),
              f"{len(body.get('comparison', {}).get('dimensions', []))} dimensions")

        status, body, _ = call("/api/report/market", cookie=cookie)
        market_body = body.get("comparison", {})
        check("HTTP market-comparison report is served",
              status == 200 and market_body.get("headline", {}).get("losses", 0) > 0,
              f"{len(market_body.get('dimensions', []))} dimensions, "
              f"{market_body.get('headline', {}).get('losses')} recorded as losses")

        # The camera routes: the store and the API existed with no test and no
        # caller at all, so these are the first thing that has ever exercised
        # them over HTTP.
        status, body, _ = call("/api/cameras?station=stn-selftest", cookie=cookie)
        check("HTTP camera list is served for a station",
              status == 200 and len(body.get("cameras", [])) == 3,
              f"{len(body.get('cameras', []))} cameras")
        check("  with a summary that knows a backup exists",
              body.get("summary", {}).get("has_backup") is True)

        status, body, _ = call("/api/cameras/order?station=stn-selftest", cookie=cookie)
        check("HTTP scanner order is served, primary first",
              status == 200 and body["cameras"][0]["role"] == "primary",
              " -> ".join(c["name"] for c in body.get("cameras", [])))
        check("  and names the cameras deliberately turned off",
              len(body.get("excluded", [])) == 1,
              f"{len(body.get('excluded', []))} excluded")

        status, body, _ = call("/api/cameras/order", cookie=cookie)
        check("  a camera order without a station is refused",
              status == 400, f"HTTP {status}")

        status, body, _ = call("/api/cameras",
                               {"station": "stn-http", "name": "HTTP test cam",
                                "device_id": "dev-http", "role": "primary"}, cookie)
        new_cam = body.get("camera", {})
        check("HTTP camera registration works", status == 200 and new_cam.get("id"),
              body.get("message"))

        status, body, _ = call(f"/api/cameras/{new_cam.get('id')}/test",
                               {"ok": True, "width": 1920, "height": 1080, "fps": 15,
                                "frames": 60, "decodes": 40, "first_ms": 700,
                                "formats": ["QR_CODE"]}, cookie)
        check("  a measurement posted from the browser is scored server-side",
              status == 200 and body.get("result", {}).get("grade") == "excellent",
              body.get("message"))

        status, body, _ = call(f"/api/cameras/{new_cam.get('id')}/tests", cookie=cookie)
        check("  and is kept in the camera's history",
              status == 200 and len(body.get("tests", [])) == 1)

        status, body, _ = call("/api/vision/failover",
                               {"symptom": "track_ended",
                                "cameras": [{"label": "A", "role": "primary"},
                                            {"label": "B", "role": "backup"}],
                                "active_index": 0}, cookie)
        check("HTTP vision failover returns an agent decision",
              status == 200 and body.get("action") == "switch"
              and body.get("target_label") == "B",
              (body.get("reasons") or [""])[0][:60])

        status, body, _ = call("/api/products", cookie=cookie)
        check("HTTP product index is served",
              status == 200 and body.get("products"),
              f"{len(body.get('products', []))} products")

        status, body, _ = call("/api/products/900700", cookie=cookie)
        check("HTTP product detail is served",
              status == 200 and body["product"]["name"] == "Network Switch",
              body.get("product", {}).get("name"))
        check("  it carries the agents' forecast and reorder view",
              "forecast" in body["product"])

        status, body, _ = call("/api/reports/daily?days=14", cookie=cookie)
        check("HTTP daily report is served",
              status == 200 and len(body["report"]["series"]) == 14,
              f"{len(body.get('report', {}).get('series', []))} days")

        # A staff account may scan but must not manage the catalogue.
        _, _, sh = call("/api/auth/login",
                        {"username": "picker01", "password": "Warehouse#1"})
        scookie = (sh.get("Set-Cookie") or "").split(";")[0]
        status, _, _ = call("/api/products", {"name": "X", "productno": "1"}, scookie)
        check("a staff account cannot create products", status == 403, f"HTTP {status}")
        status, _, _ = call("/api/staff", cookie=scookie)
        check("  nor read the staff list", status == 403, f"HTTP {status}")
        status, _, _ = call("/api/state", cookie=scookie)
        check("  but can read inventory", status == 200, f"HTTP {status}")

        # Cameras split the same way: anyone who scans must be able to read the
        # list, because the Scanner page cannot open a camera without it, but
        # only an administrator may change the configuration.
        status, _, _ = call("/api/cameras?station=stn-selftest", cookie=scookie)
        check("  a staff account can read the camera list", status == 200, f"HTTP {status}")
        status, _, _ = call("/api/cameras",
                            {"station": "stn-selftest", "name": "Sneaky",
                             "device_id": "dev-sneaky"}, scookie)
        check("  but cannot configure a camera", status == 403, f"HTTP {status}")

        # The phone-pairing page. Public on purpose -- it is what someone opens
        # when the phone will not connect, so needing a session would make it
        # useless at exactly the moment it is needed.
        try:
            page = urllib.request.urlopen(base_url + "/connect", timeout=8)
            html = page.read().decode("utf-8", "replace")
            check("the connect page is served without signing in",
                  page.status == 200 and "Connect a phone" in html,
                  f"HTTP {page.status}, {len(html)} bytes")
            check("  it carries an inlined QR rather than a fetched image",
                  "<svg" in html and "<img" not in html)
            # Golden rule 2 applies hardest here: this page is read when the
            # network is the thing that is broken, so it must fetch nothing.
            external = _re.findall(r'(?:src|href)="(https?://[^"]+)"', html)
            check("  and fetches nothing from an external host",
                  not external, ", ".join(external[:3]) or "no external assets")
        except Exception as e:               # noqa: BLE001
            check("the connect page is served without signing in", False, repr(e))

        status, body, _ = call("/api/auth/logout", {}, cookie)
        status, _, _ = call("/api/state", cookie=cookie)
        check("signing out invalidates the session", status == 401, f"HTTP {status}")

        httpd.shutdown()
    except Exception as e:               # noqa: BLE001
        check("live HTTP checks", False, repr(e))

    # 13) the model bake-off: five classifiers, cross-validated and compared
    from ml import registry as ml_registry, dataset as ml_dataset
    stats = ml_dataset.dataset_stats()
    check("training corpus is large enough to evaluate",
          stats["total"] >= 100 and stats["classes"] >= 4,
          f"{stats['total']} samples, {stats['classes']} classes")
    comparison = ml_registry.train_all()
    check("all five models train and are compared",
          comparison["ok"] and len(comparison["models"]) == 5,
          f"{len(comparison.get('models', []))} models")

    # Compare the documentation against the fresh-install measurement taken
    # before this file created anything.
    fresh_best = fresh_comparison["models"][0]
    # Every shipped document that quotes an accuracy must quote the same one.
    documented = {name: text for name, text in docs.items() if "%" in text}
    headline = "%.1f%%" % (fresh_best["cv_accuracy"] * 100)
    check("the published accuracy is reproducible from a fresh install",
          all(headline in t for t in documented.values()
              if "cross-validation" in t or "CV accuracy" in t),
          f"{fresh_best['name']} at {headline} on {fresh_stats['total']} samples")
    check("  and the published sample count matches it",
          all(str(fresh_stats["total"]) in t for t in documented.values()
              if "cross-validation" in t or "CV accuracy" in t),
          f"{fresh_stats['total']} samples, {fresh_stats['classes']} classes")
    check("  filing products only ever grows the corpus",
          stats["total"] >= fresh_stats["total"],
          f"{fresh_stats['total']} at install -> {stats['total']} after this run")
    best = comparison["models"][0]
    check("  the selected model beats the original 70% baseline",
          best["cv_accuracy"] > 0.70,
          f"{best['name']} at {best['cv_accuracy']*100:.1f}%")
    check("  every category is scored, none is ignored",
          all(m["support"] > 0 and m["f1"] > 0 for m in best["per_class"].values()),
          str({k: round(v["f1"], 2) for k, v in best["per_class"].items()}))
    check("  a confusion matrix is produced",
          set(best["confusion"]["labels"]) == set(comparison["labels"]))
    check("  models are ranked by the published score",
          [m["score"] for m in comparison["models"]] ==
          sorted((m["score"] for m in comparison["models"]), reverse=True))

    print(f"[INFO]  model bake-off ({stats['total']} samples, {stats['classes']} classes):")
    for m in comparison["models"]:
        print(f"[INFO]    {m['name']:<32} cv={m['cv_accuracy']*100:5.1f}%  "
              f"macroF1={m['macro_f1']*100:5.1f}%  score={m['score']:.4f}")
    b = comparison["baseline"]
    print(f"[INFO]  baseline {b['previous']['accuracy']*100:.0f}% "
          f"({b['previous']['training_samples']} samples) -> "
          f"{b['current']['accuracy']*100:.1f}% "
          f"({b['current']['training_samples']} samples), "
          f"{b['absolute_gain']*100:+.1f} points, "
          f"{b['error_reduction']*100:.0f}% fewer errors")

    # cleanup temp db
    for suf in ("", "-wal", "-shm"):
        try:
            os.remove(tmp + suf)
        except OSError:
            pass

    # Last, because it counts everything above it, including itself.
    check_documented_total(os.path.dirname(os.path.abspath(__file__)))

    summary_and_exit()


if __name__ == "__main__":
    main()
