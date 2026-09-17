"""
Camera configuration
====================
Which cameras this warehouse scans with, how they are ordered, and how well each
one actually performs.

Why this is not in the settings table
-------------------------------------
:mod:`store.settings` holds one typed scalar per key. A warehouse has a *list*
of cameras, each with its own identity, ordering and test history, so it needs
rows of its own.

The thing that shapes this whole module
---------------------------------------
**A browser ``deviceId`` is meaningless on another machine.** It is generated
per origin *and* per device, so the id for the USB camera on the goods-in laptop
identifies nothing on the phone in the yard, and it can change when the browser
storage is cleared. A single global camera list would therefore be wrong on
every machine but the one that created it.

So every camera is registered against a **station** — a stable identifier the
browser keeps for itself. Cameras are configured, listed and chosen per station,
and ``device_label`` is kept as a second way to recognise the same physical
camera if its id is reissued.

Camera kinds
------------
``device``   a camera the browser can open directly: built-in, USB (wired), or a
             phone's front/back camera. Reached through ``getUserMedia``.
``network``  an IP camera reachable over HTTP as MJPEG or as a still-image
             snapshot URL. Shown as an image, not a MediaStream, because a
             browser cannot open an RTSP stream at all.
"""

import json

from core import dbcore

KINDS = ("device", "network")

#: Addresses this server answers on, filled in by ``app.main``. Used to refuse a
#: "network camera" whose URL is really the warehouse server itself -- an easy
#: mistake to make, because that address is the one printed on every screen and
#: on the pairing page, so it is the address closest to hand when a field asks
#: for a URL. Left empty the check simply does not fire.
SERVER_ORIGINS = set()

#: What a camera is for. ``primary`` is tried first, ``backup`` takes over when
#: it fails, ``disabled`` is never opened. Exactly one primary per station.
ROLES = ("primary", "backup", "disabled")

#: Grades a test result can earn. Ordered worst to best.
GRADES = ("unusable", "marginal", "good", "excellent")

SCHEMA = """
CREATE TABLE IF NOT EXISTS cameras (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    station       TEXT NOT NULL,               -- which browser/machine sees it
    station_label TEXT NOT NULL DEFAULT '',    -- human name for that machine
    name          TEXT NOT NULL,               -- what staff call it
    kind          TEXT NOT NULL DEFAULT 'device',
    device_id     TEXT NOT NULL DEFAULT '',    -- browser deviceId (station-scoped)
    device_label  TEXT NOT NULL DEFAULT '',    -- label reported at registration
    group_id      TEXT NOT NULL DEFAULT '',
    facing        TEXT NOT NULL DEFAULT '',    -- environment | user | ''
    stream_url    TEXT NOT NULL DEFAULT '',    -- network cameras only
    role          TEXT NOT NULL DEFAULT 'backup',   -- primary | backup | disabled
    position      INTEGER NOT NULL DEFAULT 100,     -- lower is tried first
    want_width    INTEGER NOT NULL DEFAULT 1920,
    want_height   INTEGER NOT NULL DEFAULT 1080,
    want_fps      INTEGER NOT NULL DEFAULT 15,
    notes         TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL,
    updated_at    TEXT,
    created_by    TEXT NOT NULL DEFAULT '',
    updated_by    TEXT NOT NULL DEFAULT '',   -- who last changed it
    UNIQUE(station, device_id, stream_url)
);

CREATE INDEX IF NOT EXISTS idx_cameras_station ON cameras(station);

-- One row per test run. Kept rather than overwritten: a camera that used to
-- pass and now does not is the single most useful thing this table can show.
CREATE TABLE IF NOT EXISTS camera_tests (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    camera_id      INTEGER NOT NULL,
    ts             TEXT NOT NULL,
    ok             INTEGER NOT NULL DEFAULT 0,
    width          INTEGER NOT NULL DEFAULT 0,
    height         INTEGER NOT NULL DEFAULT 0,
    fps            REAL NOT NULL DEFAULT 0,
    frames         INTEGER NOT NULL DEFAULT 0,
    decodes        INTEGER NOT NULL DEFAULT 0,
    first_ms       REAL,                       -- time to first successful decode
    decode_rate    REAL NOT NULL DEFAULT 0,    -- decodes / frames
    formats        TEXT NOT NULL DEFAULT '[]', -- JSON: symbologies decoded
    capabilities   TEXT NOT NULL DEFAULT '{}', -- JSON: zoom/torch/focus support
    score          INTEGER NOT NULL DEFAULT 0, -- 0-100
    grade          TEXT NOT NULL DEFAULT 'unusable',
    engine         TEXT NOT NULL DEFAULT '',   -- native BarcodeDetector or wasm
    error          TEXT NOT NULL DEFAULT '',
    username       TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (camera_id) REFERENCES cameras(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_camera_tests_camera ON camera_tests(camera_id, id);
"""


def init_cameras():
    dbcore.ensure_dir()
    with dbcore.lock(), dbcore.connect() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)


def _migrate(conn):
    """Idempotent upgrades for databases made by an earlier version."""
    if not dbcore.table_exists(conn, "cameras"):
        return
    cols = dbcore.table_columns(conn, "cameras")
    for name, ddl in (
        ("station_label", "ALTER TABLE cameras ADD COLUMN station_label TEXT NOT NULL DEFAULT ''"),
        ("notes", "ALTER TABLE cameras ADD COLUMN notes TEXT NOT NULL DEFAULT ''"),
        ("want_fps", "ALTER TABLE cameras ADD COLUMN want_fps INTEGER NOT NULL DEFAULT 15"),
        ("updated_by", "ALTER TABLE cameras ADD COLUMN updated_by TEXT NOT NULL DEFAULT ''"),
    ):
        if name not in cols:
            conn.execute(ddl)


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------
def _row(r, last_test=None):
    d = dict(r)
    d["enabled"] = d["role"] != "disabled"
    d["last_test"] = last_test
    return d


def _latest_test(conn, camera_id):
    row = conn.execute(
        "SELECT * FROM camera_tests WHERE camera_id = ? ORDER BY id DESC LIMIT 1",
        (camera_id,),
    ).fetchone()
    return _test_row(row) if row else None


def _test_row(row):
    d = dict(row)
    for key in ("formats", "capabilities"):
        try:
            d[key] = json.loads(d[key])
        except (ValueError, TypeError):
            d[key] = [] if key == "formats" else {}
    d["ok"] = bool(d["ok"])
    return d


def list_cameras(station=None):
    """Every configured camera, newest station first.

    ``station`` filters to one machine — which is what the scanner wants, since
    a camera on another machine is not something it can open.
    """
    sql = "SELECT * FROM cameras"
    params = []
    if station:
        sql += " WHERE station = ?"
        params.append(station)
    sql += " ORDER BY position, id"
    with dbcore.lock(), dbcore.connect() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [_row(r, _latest_test(conn, r["id"])) for r in rows]


def get_camera(camera_id):
    with dbcore.lock(), dbcore.connect() as conn:
        row = conn.execute("SELECT * FROM cameras WHERE id = ?", (camera_id,)).fetchone()
        return _row(row, _latest_test(conn, camera_id)) if row else None


def stations():
    """The machines that have registered a camera."""
    with dbcore.lock(), dbcore.connect() as conn:
        rows = conn.execute(
            """SELECT station, MAX(station_label) AS label, COUNT(*) AS cameras,
                      MAX(created_at) AS last_seen
                 FROM cameras GROUP BY station ORDER BY last_seen DESC"""
        ).fetchall()
        return [dict(r) for r in rows]


def test_history(camera_id, limit=20):
    with dbcore.lock(), dbcore.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM camera_tests WHERE camera_id = ? ORDER BY id DESC LIMIT ?",
            (camera_id, max(1, min(int(limit), 100))),
        ).fetchall()
        return [_test_row(r) for r in rows]


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------
def _validate(kind, device_id, stream_url):
    if kind not in KINDS:
        return "Unknown camera kind '%s'." % kind
    if kind == "device" and not device_id:
        return "A device camera needs the id the browser gave it."
    if kind == "network":
        url = (stream_url or "").strip()
        if not url:
            return "A network camera needs a stream or snapshot URL."
        if not url.lower().startswith(("http://", "https://")):
            return ("A browser can only open an http:// or https:// stream. RTSP "
                    "cannot be played by any browser without a converting server.")
        if _is_this_server(url):
            return ("That is this warehouse server's own address, not a camera. "
                    "A phone is not attached here as a camera: it opens the "
                    "warehouse itself and scans on its own screen. Use the "
                    "Connect a phone page instead. This field is for an IP "
                    "camera, whose address ends in something like "
                    "/snapshot.jpg or /video.")
    return None


def _is_this_server(url):
    """Is this URL pointing back at the warehouse server?"""
    if not SERVER_ORIGINS:
        return False
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url.strip())
        host = (parsed.hostname or "").lower()
        if not host:
            return False
        # Any port on our own host counts: a camera does not live on the same
        # machine and port as the server, whatever port was typed.
        return host in SERVER_ORIGINS
    except Exception:                        # noqa: BLE001 - never block a save
        return False


def add_camera(station, name, kind="device", device_id="", device_label="",
               group_id="", facing="", stream_url="", role="backup",
               want_width=1920, want_height=1080, want_fps=15,
               station_label="", notes="", actor=None):
    """Register a camera against a station. Returns ``(ok, message, camera)``."""
    station = (station or "").strip()
    name = (name or "").strip()
    if not station:
        return False, "No station was supplied for this camera.", None
    if not name:
        return False, "Give the camera a name staff will recognise.", None
    if role not in ("primary", "backup", "disabled"):
        return False, "Unknown role '%s'." % role, None

    problem = _validate(kind, device_id, stream_url)
    if problem:
        return False, problem, None

    with dbcore.lock(), dbcore.connect() as conn:
        clash = conn.execute(
            """SELECT id, name FROM cameras
                WHERE station = ? AND device_id = ? AND stream_url = ?""",
            (station, device_id or "", (stream_url or "").strip()),
        ).fetchone()
        if clash:
            return False, ("That camera is already configured on this machine as "
                           "'%s'." % clash["name"]), None

        # Only one primary per station: the whole point of a primary is that
        # there is exactly one to start with.
        if role == "primary":
            conn.execute(
                "UPDATE cameras SET role = 'backup' WHERE station = ? AND role = 'primary'",
                (station,))

        position = conn.execute(
            "SELECT COALESCE(MAX(position), 0) + 10 AS p FROM cameras WHERE station = ?",
            (station,)).fetchone()["p"]
        if role == "primary":
            position = 0

        cur = conn.execute(
            """INSERT INTO cameras(station, station_label, name, kind, device_id,
                                   device_label, group_id, facing, stream_url, role,
                                   position, want_width, want_height, want_fps,
                                   notes, created_at, created_by)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (station, (station_label or "").strip(), name, kind, device_id or "",
             (device_label or "").strip(), group_id or "", facing or "",
             (stream_url or "").strip(), role, position,
             int(want_width or 0), int(want_height or 0), int(want_fps or 0),
             (notes or "").strip(), dbcore.now_iso(),
             (actor or {}).get("username", "")),
        )
        new_id = cur.lastrowid
        row = conn.execute("SELECT * FROM cameras WHERE id = ?", (new_id,)).fetchone()
    return True, "Camera '%s' configured." % name, _row(row)


def update_camera(camera_id, actor=None, **fields):
    allowed = {"name", "role", "position", "want_width", "want_height", "want_fps",
               "notes", "stream_url", "facing", "station_label"}
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not updates:
        return False, "Nothing to update.", None
    if "role" in updates and updates["role"] not in ("primary", "backup", "disabled"):
        return False, "Unknown role '%s'." % updates["role"], None

    with dbcore.lock(), dbcore.connect() as conn:
        row = conn.execute("SELECT * FROM cameras WHERE id = ?", (camera_id,)).fetchone()
        if row is None:
            return False, "No such camera.", None

        if updates.get("role") == "primary":
            conn.execute(
                """UPDATE cameras SET role = 'backup'
                    WHERE station = ? AND role = 'primary' AND id <> ?""",
                (row["station"], camera_id))
            updates.setdefault("position", 0)

        if "stream_url" in updates and row["kind"] == "network":
            problem = _validate("network", "", updates["stream_url"])
            if problem:
                return False, problem, None

        for key in ("want_width", "want_height", "want_fps", "position"):
            if key in updates:
                try:
                    updates[key] = int(updates[key])
                except (TypeError, ValueError):
                    return False, "'%s' must be a whole number." % key, None
                if updates[key] < 0:
                    return False, "'%s' cannot be negative." % key, None

        # Record who changed it. This used to accept ``actor`` and throw it
        # away, so a camera edit was the one write in the system with no name
        # against it — including the edit that disables the backup camera.
        sets = ", ".join("%s = ?" % k for k in updates)
        conn.execute(
            "UPDATE cameras SET %s, updated_at = ?, updated_by = ? WHERE id = ?" % sets,
            list(updates.values())
            + [dbcore.now_iso(), (actor or {}).get("username", ""), camera_id])
        updated = conn.execute("SELECT * FROM cameras WHERE id = ?", (camera_id,)).fetchone()
        return True, "Camera updated.", _row(updated, _latest_test(conn, camera_id))


def delete_camera(camera_id):
    with dbcore.lock(), dbcore.connect() as conn:
        row = conn.execute("SELECT name FROM cameras WHERE id = ?", (camera_id,)).fetchone()
        if row is None:
            return False, "No such camera."
        conn.execute("DELETE FROM camera_tests WHERE camera_id = ?", (camera_id,))
        conn.execute("DELETE FROM cameras WHERE id = ?", (camera_id,))
    return True, "Camera '%s' removed." % row["name"]


def reorder(station, ordered_ids, actor=None):
    """Set the order cameras are tried in, from a list of ids.

    Returns ``(ok, message)``. Ids belonging to another station are ignored by
    the WHERE clause rather than raising, because a stale browser tab is not a
    reason to refuse the whole reorder.
    """
    username = (actor or {}).get("username", "")
    with dbcore.lock(), dbcore.connect() as conn:
        for index, camera_id in enumerate(ordered_ids):
            # updated_by as well as updated_at. Bumping the timestamp alone left
            # the reorder attributed to whoever last *edited* the camera, which
            # is a worse record than none: it names the wrong person.
            conn.execute(
                """UPDATE cameras SET position = ?, updated_at = ?, updated_by = ?
                    WHERE id = ? AND station = ?""",
                (index * 10, dbcore.now_iso(), username, camera_id, station))
    return True, "Camera order saved."


# ---------------------------------------------------------------------------
# Test results
# ---------------------------------------------------------------------------
#: Weights for the quality score. Resolution and decode reliability dominate
#: because they are what actually decide whether a barcode reads; frame rate
#: matters, but a sharp 10fps camera beats a blurry 30fps one every time.
WEIGHT_DECODE = 0.45
WEIGHT_RESOLUTION = 0.30
WEIGHT_SPEED = 0.15
WEIGHT_FPS = 0.10


def score_result(width, height, fps, decode_rate, first_ms):
    """Turn measurements into a 0-100 score and a grade.

    The thresholds are chosen for 1-D barcode work, which is far more demanding
    than QR: a 1-D symbol needs roughly two pixels per narrow bar across the
    frame, so 1280 wide is the point below which thin bars start to fail.
    """
    # Decode reliability: the share of sampled frames that produced a read.
    decode = min(decode_rate / 0.60, 1.0)

    # Resolution: 640 is unusable for 1-D, 1280 acceptable, 1920 full marks.
    shortest = min(width or 0, height or 0)
    longest = max(width or 0, height or 0)
    if longest >= 1920:
        resolution = 1.0
    elif longest >= 1280:
        resolution = 0.75
    elif longest >= 960:
        resolution = 0.45
    elif longest >= 640:
        resolution = 0.2
    else:
        resolution = 0.0
    if shortest and shortest < 480:
        resolution *= 0.8

    # Time to first decode: under a second feels instant, over four is painful.
    if first_ms is None:
        speed = 0.0
    elif first_ms <= 1000:
        speed = 1.0
    elif first_ms >= 4000:
        speed = 0.0
    else:
        speed = 1.0 - (first_ms - 1000) / 3000.0

    frame_rate = min((fps or 0) / 15.0, 1.0)

    score = int(round(100 * (
        WEIGHT_DECODE * decode
        + WEIGHT_RESOLUTION * resolution
        + WEIGHT_SPEED * speed
        + WEIGHT_FPS * frame_rate
    )))

    if score >= 80:
        grade = "excellent"
    elif score >= 60:
        grade = "good"
    elif score >= 35:
        grade = "marginal"
    else:
        grade = "unusable"
    return score, grade


def record_test(camera_id, result, actor=None):
    """Store one test run. ``result`` comes from the browser, which is the only
    place that can actually measure a camera."""
    with dbcore.lock(), dbcore.connect() as conn:
        if conn.execute("SELECT 1 FROM cameras WHERE id = ?", (camera_id,)).fetchone() is None:
            return False, "No such camera.", None

    width = int(result.get("width") or 0)
    height = int(result.get("height") or 0)
    fps = float(result.get("fps") or 0)
    frames = int(result.get("frames") or 0)
    decodes = int(result.get("decodes") or 0)
    first_ms = result.get("first_ms")
    first_ms = float(first_ms) if first_ms not in (None, "") else None

    # A decoded frame is one of the frames examined, so decodes can never exceed
    # frames. A browser that counted only its *misses* sent decodes > frames and
    # produced a decode rate above 100% — which then sailed through scoring as a
    # perfect result. Trust the larger of the two and clamp, because a rate over
    # 1.0 is a client bug and silently scoring it is worse than correcting it.
    frames = max(int(frames), decodes)
    decode_rate = min((decodes / frames) if frames else 0.0, 1.0)
    error = (result.get("error") or "").strip()
    ok = bool(result.get("ok")) and not error

    if ok:
        score, grade = score_result(width, height, fps, decode_rate, first_ms)
    else:
        score, grade = 0, "unusable"

    with dbcore.lock(), dbcore.connect() as conn:
        cur = conn.execute(
            """INSERT INTO camera_tests(camera_id, ts, ok, width, height, fps, frames,
                                        decodes, first_ms, decode_rate, formats,
                                        capabilities, score, grade, engine, error, username)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (camera_id, dbcore.now_iso(), 1 if ok else 0, width, height, fps, frames,
             decodes, first_ms, round(decode_rate, 4),
             json.dumps(result.get("formats") or []),
             json.dumps(result.get("capabilities") or {}),
             score, grade, (result.get("engine") or "")[:60], error[:300],
             (actor or {}).get("username", "")),
        )
        row = conn.execute("SELECT * FROM camera_tests WHERE id = ?", (cur.lastrowid,)).fetchone()
    return True, "Test recorded: %s (%d/100)." % (grade, score), _test_row(row)


def summary(station=None):
    """Headline numbers for the configuration page."""
    cameras = list_cameras(station)
    tested = [c for c in cameras if c["last_test"]]
    usable = [c for c in tested if c["last_test"]["grade"] in ("good", "excellent")]
    return {
        "total": len(cameras),
        "enabled": sum(1 for c in cameras if c["enabled"]),
        "tested": len(tested),
        "untested": len(cameras) - len(tested),
        "usable": len(usable),
        "has_primary": any(c["role"] == "primary" for c in cameras),
        "has_backup": sum(1 for c in cameras if c["role"] == "backup" and c["enabled"]) > 0,
        "best_score": max((c["last_test"]["score"] for c in tested), default=0),
    }


def scanner_order(station):
    """The cameras the scanner should try, best first.

    Disabled cameras are left out. Within what remains the manager's order wins;
    an untested camera sorts after tested ones so a known-good camera is
    preferred over an unknown quantity.
    """
    cameras = [c for c in list_cameras(station) if c["enabled"]]
    cameras.sort(key=lambda c: (
        0 if c["role"] == "primary" else 1,
        c["position"],
        -(c["last_test"]["score"] if c["last_test"] else -1),
    ))
    return cameras


def excluded(station):
    """The cameras this station has deliberately turned off.

    The scanner needs these by name, not merely absent from
    :func:`scanner_order`. A camera that is attached but disabled looks exactly
    like a camera nobody has configured yet, and the browser would helpfully
    offer to scan on it — undoing the manager's decision every time.
    """
    return [c for c in list_cameras(station) if not c["enabled"]]
