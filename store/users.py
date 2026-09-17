"""
Users, roles, sessions and the staff directory
==============================================
Who may use the system, what they are allowed to do, and a record of every
authentication event.

Design notes
------------
* **Passwords are never stored.** Only a PBKDF2 hash (see :mod:`core.security`).
* **Session tokens are never stored either** — the table keeps a SHA-256
  fingerprint, so a stolen database dump cannot be replayed as live sessions.
* **Lockout is per account, not per IP.** After a run of failed attempts the
  account pauses for a few minutes. This blunts password guessing without
  letting one attacker lock a whole warehouse out by hammering from one address.
* **The last active admin cannot be disabled or demoted.** Locking every
  administrator out of a system that only an administrator can fix is a hole
  that is very easy to fall into and very tedious to climb out of.
"""

import json

from core import dbcore, security

# ---------------------------------------------------------------------------
# Roles and capabilities
# ---------------------------------------------------------------------------
# Capabilities are checked by name throughout the API, so a route says what it
# needs ("staff.create") rather than which roles happen to have it today.
ROLES = ("admin", "manager", "staff", "viewer")

ROLE_LABELS = {
    "admin": "Administrator",
    "manager": "Warehouse Manager",
    "staff": "Warehouse Staff",
    "viewer": "Read Only",
}

ROLE_DESCRIPTIONS = {
    "admin": "Full control, including staff accounts, settings and model training.",
    "manager": "Runs the warehouse: scanning, corrections, categories and reorder levels.",
    "staff": "Scans stock in and out and reads the inventory.",
    "viewer": "Can see the dashboard and reports but cannot change anything.",
}

CAPABILITIES = {
    "admin": {
        "scan", "inventory.read", "inventory.adjust", "inventory.undo",
        "catalog.manage", "categories.manage", "reorder.manage",
        "staff.read", "staff.create", "staff.update", "staff.delete",
        "settings.manage", "models.read", "models.train",
        "reports.read", "audit.read", "assistant.use", "agents.read",
    },
    "manager": {
        "scan", "inventory.read", "inventory.adjust", "inventory.undo",
        "catalog.manage", "categories.manage", "reorder.manage",
        "staff.read", "models.read", "reports.read", "audit.read",
        "assistant.use", "agents.read",
    },
    "staff": {
        "scan", "inventory.read", "assistant.use", "agents.read",
        "reports.read",
    },
    "viewer": {
        "inventory.read", "reports.read", "models.read", "agents.read",
    },
}

# How long a session stays valid, and how hard the lockout bites.
SESSION_HOURS = 12
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 10

DEFAULT_ADMIN = {"username": "admin", "password": "admin12345", "full_name": "System Administrator"}


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    username       TEXT NOT NULL UNIQUE COLLATE NOCASE,
    full_name      TEXT NOT NULL DEFAULT '',
    email          TEXT NOT NULL DEFAULT '',
    phone          TEXT NOT NULL DEFAULT '',
    role           TEXT NOT NULL DEFAULT 'staff',
    password_hash  TEXT NOT NULL,
    active         INTEGER NOT NULL DEFAULT 1,
    must_change_pw INTEGER NOT NULL DEFAULT 0,
    shift          TEXT NOT NULL DEFAULT '',      -- free text: Day / Night / Weekend
    created_at     TEXT NOT NULL,
    created_by     INTEGER,
    updated_at     TEXT,
    last_login_at  TEXT,
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until   TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    token_fp     TEXT NOT NULL UNIQUE,     -- SHA-256 of the token, never the token
    user_id      INTEGER NOT NULL,
    created_at   TEXT NOT NULL,
    expires_at   TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    ip           TEXT NOT NULL DEFAULT '',
    user_agent   TEXT NOT NULL DEFAULT '',
    revoked      INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

-- Every authentication-relevant event, kept apart from the inventory audit
-- trail so a security question can be answered without wading through scans.
CREATE TABLE IF NOT EXISTS user_events (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT NOT NULL,
    user_id   INTEGER,
    username  TEXT NOT NULL DEFAULT '',
    event     TEXT NOT NULL,         -- login | login_failed | logout | created | ...
    detail    TEXT NOT NULL DEFAULT '',
    ip        TEXT NOT NULL DEFAULT '',
    actor_id  INTEGER,               -- who performed it, when not the user
    meta      TEXT                   -- JSON, free-form
);

CREATE INDEX IF NOT EXISTS idx_user_events_ts ON user_events(ts);
"""


def init_auth():
    """Create the tables and make sure at least one administrator exists."""
    dbcore.ensure_dir()
    with dbcore.lock(), dbcore.connect() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)
        seeded = _seed_admin(conn)
    return seeded


def _migrate(conn):
    """Idempotent upgrades for databases created by an earlier version."""
    cols = dbcore.table_columns(conn, "users")
    for name, ddl in (
        ("phone", "ALTER TABLE users ADD COLUMN phone TEXT NOT NULL DEFAULT ''"),
        ("shift", "ALTER TABLE users ADD COLUMN shift TEXT NOT NULL DEFAULT ''"),
        ("must_change_pw", "ALTER TABLE users ADD COLUMN must_change_pw INTEGER NOT NULL DEFAULT 0"),
        ("updated_at", "ALTER TABLE users ADD COLUMN updated_at TEXT"),
    ):
        if name not in cols:
            conn.execute(ddl)


def _seed_admin(conn):
    """Create the default administrator on a fresh database.

    Flagged ``must_change_pw`` so the well-known starting password cannot quietly
    become the permanent one.
    """
    count = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
    if count:
        return None
    conn.execute(
        """INSERT INTO users(username, full_name, email, role, password_hash,
                             active, must_change_pw, created_at)
           VALUES (?, ?, '', 'admin', ?, 1, 1, ?)""",
        (DEFAULT_ADMIN["username"], DEFAULT_ADMIN["full_name"],
         security.hash_password(DEFAULT_ADMIN["password"]), dbcore.now_iso()),
    )
    conn.execute(
        """INSERT INTO user_events(ts, username, event, detail)
           VALUES (?, ?, 'created', 'Default administrator seeded on first run.')""",
        (dbcore.now_iso(), DEFAULT_ADMIN["username"]),
    )
    return dict(DEFAULT_ADMIN)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _public(row):
    """A user record safe to send to the browser — no hash, ever."""
    if row is None:
        return None
    d = dict(row)
    d.pop("password_hash", None)
    d["active"] = bool(d.get("active", 1))
    d["must_change_pw"] = bool(d.get("must_change_pw", 0))
    d["role_label"] = ROLE_LABELS.get(d.get("role"), d.get("role"))
    d["capabilities"] = sorted(CAPABILITIES.get(d.get("role"), set()))
    return d


#: What an account may still do while it is on its issued password. Enough to
#: sign in, see who it is, and change the password -- nothing that touches
#: stock. Enforcing this only in the browser meant the published default
#: password never actually had to be changed.
LOCKED_OUT_UNTIL_PASSWORD_SET = ("scan", "inventory.adjust", "inventory.undo",
                                 "catalog.manage", "categories.manage",
                                 "reorder.manage", "staff.create", "staff.update",
                                 "staff.delete", "settings.manage", "models.train")


def can(user, capability):
    """True when a user record holds a capability."""
    if not user or not user.get("active", True):
        return False
    if user.get("must_change_pw") and capability in LOCKED_OUT_UNTIL_PASSWORD_SET:
        return False
    return capability in CAPABILITIES.get(user.get("role"), set())


def log_event(conn, event, username="", user_id=None, detail="", ip="", actor_id=None, meta=None):
    conn.execute(
        """INSERT INTO user_events(ts, user_id, username, event, detail, ip, actor_id, meta)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (dbcore.now_iso(), user_id, username or "", event, detail, ip, actor_id,
         json.dumps(meta) if meta else None),
    )


def _admin_count(conn, exclude_id=None):
    sql = "SELECT COUNT(*) AS c FROM users WHERE role = 'admin' AND active = 1"
    params = []
    if exclude_id is not None:
        sql += " AND id <> ?"
        params.append(exclude_id)
    return conn.execute(sql, params).fetchone()["c"]


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
def authenticate(username, password, ip="", user_agent=""):
    """Check credentials.

    Returns ``(user_or_None, reason)``. ``reason`` is a message safe to show the
    person trying to log in — deliberately vague about *which* half was wrong,
    so the form cannot be used to discover valid usernames.
    """
    username = (username or "").strip()
    if not username or not password:
        return None, "Enter both a username and a password."

    with dbcore.lock(), dbcore.connect() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ? COLLATE NOCASE", (username,)
        ).fetchone()

        if row is None:
            # Still spend time hashing, so a missing user does not answer faster
            # than a wrong password and reveal which usernames exist.
            security.verify_password(password, security.hash_password("dummy"))
            log_event(conn, "login_failed", username=username, ip=ip,
                      detail="No such user.")
            return None, "Incorrect username or password."

        user = dict(row)

        if not user["active"]:
            log_event(conn, "login_failed", username=username, user_id=user["id"],
                      ip=ip, detail="Account is disabled.")
            return None, "That account has been disabled. Ask an administrator."

        locked = user.get("locked_until")
        if locked and locked > dbcore.now_iso():
            log_event(conn, "login_failed", username=username, user_id=user["id"],
                      ip=ip, detail="Account temporarily locked.")
            return None, ("Too many failed attempts. Try again in a few minutes, "
                          "or ask an administrator to unlock the account.")

        ok, needs_upgrade = security.verify_password(password, user["password_hash"])
        if not ok:
            attempts = user["failed_attempts"] + 1
            lock_until = None
            if attempts >= MAX_FAILED_ATTEMPTS:
                lock_until = _in_minutes(LOCKOUT_MINUTES)
            conn.execute(
                "UPDATE users SET failed_attempts = ?, locked_until = ? WHERE id = ?",
                (attempts, lock_until, user["id"]),
            )
            log_event(conn, "login_failed", username=username, user_id=user["id"],
                      ip=ip, detail="Wrong password (attempt %d)." % attempts)
            if lock_until:
                return None, ("Too many failed attempts. The account is locked for "
                              "%d minutes." % LOCKOUT_MINUTES)
            # Deliberately the same sentence a missing username gets. Counting
            # down the remaining attempts only happens for accounts that exist,
            # so it told an attacker which usernames were real -- undoing the
            # constant-time hashing three lines above.
            return None, "Incorrect username or password."

        # Success: clear the counters, and quietly re-hash if the cost has risen.
        if needs_upgrade:
            conn.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                         (security.hash_password(password), user["id"]))
        conn.execute(
            """UPDATE users SET failed_attempts = 0, locked_until = NULL,
                                last_login_at = ? WHERE id = ?""",
            (dbcore.now_iso(), user["id"]),
        )
        log_event(conn, "login", username=username, user_id=user["id"], ip=ip,
                  detail="Signed in.", meta={"user_agent": user_agent[:200]})
        user["last_login_at"] = dbcore.now_iso()
        return _public(user), ""


def _in_minutes(minutes):
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()


def _in_hours(hours):
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------
def create_session(user_id, ip="", user_agent=""):
    """Start a session and return the raw token (the only time it exists)."""
    token = security.new_token()
    with dbcore.lock(), dbcore.connect() as conn:
        conn.execute(
            """INSERT INTO sessions(token_fp, user_id, created_at, expires_at,
                                    last_seen_at, ip, user_agent)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (security.token_fingerprint(token), user_id, dbcore.now_iso(),
             _in_hours(SESSION_HOURS), dbcore.now_iso(), ip, user_agent[:300]),
        )
    return token


def session_user(token):
    """The user behind a session token, or None if it is missing or stale.

    Also slides ``last_seen_at`` forward, which is what makes the active-session
    list in the admin screen meaningful.
    """
    if not token:
        return None, None
    fp = security.token_fingerprint(token)
    with dbcore.lock(), dbcore.connect() as conn:
        row = conn.execute(
            """SELECT s.id AS session_id, s.expires_at, s.created_at AS session_started,
                      u.* FROM sessions s
                 JOIN users u ON u.id = s.user_id
                WHERE s.token_fp = ? AND s.revoked = 0""",
            (fp,),
        ).fetchone()
        if row is None:
            return None, None
        if row["expires_at"] <= dbcore.now_iso():
            conn.execute("UPDATE sessions SET revoked = 1 WHERE id = ?", (row["session_id"],))
            return None, None
        if not row["active"]:
            # Disabling an account must cut its live sessions too, or the person
            # keeps working until the token happens to expire.
            conn.execute("UPDATE sessions SET revoked = 1 WHERE user_id = ?", (row["id"],))
            return None, None
        conn.execute("UPDATE sessions SET last_seen_at = ? WHERE id = ?",
                     (dbcore.now_iso(), row["session_id"]))
        session = {
            "id": row["session_id"],
            "expires_at": row["expires_at"],
            "started": row["session_started"],
        }
        return _public(row), session


def revoke_session(token, actor=None):
    if not token:
        return False
    fp = security.token_fingerprint(token)
    with dbcore.lock(), dbcore.connect() as conn:
        row = conn.execute(
            "SELECT s.id, u.id AS uid, u.username FROM sessions s "
            "JOIN users u ON u.id = s.user_id WHERE s.token_fp = ?", (fp,)
        ).fetchone()
        if row is None:
            return False
        conn.execute("UPDATE sessions SET revoked = 1 WHERE id = ?", (row["id"],))
        log_event(conn, "logout", username=row["username"], user_id=row["uid"],
                  detail="Signed out.")
    return True


def revoke_all_sessions(user_id):
    with dbcore.lock(), dbcore.connect() as conn:
        cur = conn.execute(
            "UPDATE sessions SET revoked = 1 WHERE user_id = ? AND revoked = 0", (user_id,))
        return cur.rowcount


def active_sessions():
    """Live sessions, newest first — shown on the admin staff screen."""
    with dbcore.lock(), dbcore.connect() as conn:
        rows = conn.execute(
            """SELECT s.id, s.created_at, s.last_seen_at, s.expires_at, s.ip,
                      s.user_agent, u.username, u.full_name, u.role
                 FROM sessions s JOIN users u ON u.id = s.user_id
                WHERE s.revoked = 0 AND s.expires_at > ?
             ORDER BY s.last_seen_at DESC""",
            (dbcore.now_iso(),),
        ).fetchall()
        return [dict(r) for r in rows]


def purge_expired_sessions():
    """Drop sessions that expired more than a day ago. Housekeeping only."""
    from datetime import datetime, timedelta, timezone
    cutoff = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    with dbcore.lock(), dbcore.connect() as conn:
        cur = conn.execute("DELETE FROM sessions WHERE expires_at < ?", (cutoff,))
        return cur.rowcount


# ---------------------------------------------------------------------------
# Staff directory (CRUD)
# ---------------------------------------------------------------------------
def list_users(include_inactive=True):
    with dbcore.lock(), dbcore.connect() as conn:
        sql = """SELECT u.*,
                        (SELECT COUNT(*) FROM sessions s
                          WHERE s.user_id = u.id AND s.revoked = 0
                            AND s.expires_at > ?) AS live_sessions
                   FROM users u"""
        params = [dbcore.now_iso()]
        if not include_inactive:
            sql += " WHERE u.active = 1"
        sql += " ORDER BY u.active DESC, u.role, u.username"
        return [_public(r) for r in conn.execute(sql, params)]


def get_user(user_id):
    with dbcore.lock(), dbcore.connect() as conn:
        return _public(conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())


def create_user(username, password, full_name="", role="staff", email="", phone="",
                shift="", actor=None, must_change_pw=True):
    """Add a staff account. Returns ``(ok, message, user)``."""
    username = (username or "").strip()
    if not username:
        return False, "A username is required.", None
    if len(username) < 3:
        return False, "The username must be at least 3 characters.", None
    if not username.replace("_", "").replace(".", "").replace("-", "").isalnum():
        return False, "Use only letters, digits, dot, dash or underscore in a username.", None
    if role not in ROLES:
        return False, "Unknown role '%s'." % role, None
    problems = security.password_problems(password)
    if problems:
        return False, "The password " + ", and ".join(problems) + ".", None

    with dbcore.lock(), dbcore.connect() as conn:
        clash = conn.execute(
            "SELECT 1 FROM users WHERE username = ? COLLATE NOCASE", (username,)).fetchone()
        if clash:
            return False, "The username '%s' is already taken." % username, None
        cur = conn.execute(
            """INSERT INTO users(username, full_name, email, phone, role, password_hash,
                                 active, must_change_pw, shift, created_at, created_by)
               VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)""",
            (username, (full_name or "").strip(), (email or "").strip(),
             (phone or "").strip(), role, security.hash_password(password),
             1 if must_change_pw else 0, (shift or "").strip(),
             dbcore.now_iso(), actor and actor.get("id")),
        )
        new_id = cur.lastrowid
        log_event(conn, "created", username=username, user_id=new_id,
                  actor_id=actor and actor.get("id"),
                  detail="Account created with role %s." % ROLE_LABELS.get(role, role))
        row = conn.execute("SELECT * FROM users WHERE id = ?", (new_id,)).fetchone()
    return True, "Staff member '%s' created." % username, _public(row)


def update_user(user_id, actor=None, **fields):
    """Change a staff account. Only the named fields are touched."""
    allowed = {"full_name", "email", "phone", "role", "shift", "active"}
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not updates:
        return False, "Nothing to update.", None
    if "role" in updates and updates["role"] not in ROLES:
        return False, "Unknown role '%s'." % updates["role"], None

    with dbcore.lock(), dbcore.connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            return False, "No such staff member.", None
        current = dict(row)

        # Guard the last administrator, whether by demotion or by deactivation.
        losing_admin = (current["role"] == "admin" and current["active"] and
                        (updates.get("role", "admin") != "admin" or
                         updates.get("active", 1) in (0, False)))
        if losing_admin and _admin_count(conn, exclude_id=user_id) == 0:
            return False, ("This is the last active administrator. Promote someone "
                           "else to administrator first."), None

        if "active" in updates:
            updates["active"] = 1 if updates["active"] else 0

        sets = ", ".join("%s = ?" % k for k in updates)
        params = list(updates.values()) + [dbcore.now_iso(), user_id]
        conn.execute("UPDATE users SET %s, updated_at = ? WHERE id = ?" % sets, params)

        changed = ", ".join("%s -> %s" % (k, v) for k, v in updates.items())
        log_event(conn, "updated", username=current["username"], user_id=user_id,
                  actor_id=actor and actor.get("id"), detail=changed)

        # A disabled account must not keep working on an old token.
        if updates.get("active") == 0:
            conn.execute("UPDATE sessions SET revoked = 1 WHERE user_id = ?", (user_id,))

        updated = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return True, "Staff member updated.", _public(updated)


def set_password(user_id, new_password, actor=None, require_change=False):
    problems = security.password_problems(new_password)
    if problems:
        return False, "The password " + ", and ".join(problems) + "."
    with dbcore.lock(), dbcore.connect() as conn:
        row = conn.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            return False, "No such staff member."
        conn.execute(
            """UPDATE users SET password_hash = ?, must_change_pw = ?,
                                failed_attempts = 0, locked_until = NULL,
                                updated_at = ? WHERE id = ?""",
            (security.hash_password(new_password), 1 if require_change else 0,
             dbcore.now_iso(), user_id),
        )
        log_event(conn, "password_changed", username=row["username"], user_id=user_id,
                  actor_id=actor and actor.get("id"),
                  detail="Password reset by an administrator." if actor and
                         actor.get("id") != user_id else "Password changed.")
    return True, "Password updated."


def change_own_password(user_id, current_password, new_password):
    """Self-service change: the current password must be given as well."""
    with dbcore.lock(), dbcore.connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            return False, "No such account."
        ok, _ = security.verify_password(current_password, row["password_hash"])
    if not ok:
        return False, "Your current password is not correct."
    if current_password == new_password:
        return False, "The new password must be different from the current one."
    ok, message = set_password(user_id, new_password, actor={"id": user_id},
                               require_change=False)
    if ok:
        # Someone changing their password usually does so because they think it
        # is known. Leaving other sessions signed in defeats the point entirely.
        revoke_all_sessions(user_id)
    return ok, message


def delete_user(user_id, actor=None):
    """Remove a staff account.

    The account is deleted, but its rows in the audit trail stay — an audit log
    that forgets who did something is not an audit log.
    """
    with dbcore.lock(), dbcore.connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            return False, "No such staff member."
        if row["role"] == "admin" and _admin_count(conn, exclude_id=user_id) == 0:
            return False, "This is the last administrator and cannot be deleted."
        if actor and actor.get("id") == user_id:
            return False, "You cannot delete your own account."
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        log_event(conn, "deleted", username=row["username"], user_id=None,
                  actor_id=actor and actor.get("id"),
                  detail="Account deleted (was %s)." % row["role"])
    return True, "Staff member '%s' removed." % row["username"]


def unlock_user(user_id, actor=None):
    with dbcore.lock(), dbcore.connect() as conn:
        row = conn.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            return False, "No such staff member."
        conn.execute(
            "UPDATE users SET failed_attempts = 0, locked_until = NULL WHERE id = ?",
            (user_id,))
        log_event(conn, "unlocked", username=row["username"], user_id=user_id,
                  actor_id=actor and actor.get("id"), detail="Lockout cleared.")
    return True, "Account unlocked."


def recent_events(limit=100, event=None, username=None):
    sql = ["SELECT * FROM user_events WHERE 1=1"]
    params = []
    if event:
        sql.append("AND event = ?")
        params.append(event)
    if username:
        sql.append("AND username LIKE ?")
        params.append("%" + username + "%")
    sql.append("ORDER BY id DESC LIMIT ?")
    params.append(max(1, min(int(limit or 100), 500)))
    with dbcore.lock(), dbcore.connect() as conn:
        return [dict(r) for r in conn.execute(" ".join(sql), params)]


def staff_summary():
    """Headline numbers for the staff screen."""
    with dbcore.lock(), dbcore.connect() as conn:
        total = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
        active = conn.execute("SELECT COUNT(*) AS c FROM users WHERE active = 1").fetchone()["c"]
        by_role = {r["role"]: r["c"] for r in conn.execute(
            "SELECT role, COUNT(*) AS c FROM users WHERE active = 1 GROUP BY role")}
        online = conn.execute(
            "SELECT COUNT(DISTINCT user_id) AS c FROM sessions "
            "WHERE revoked = 0 AND expires_at > ?", (dbcore.now_iso(),)
        ).fetchone()["c"]
        locked = conn.execute(
            "SELECT COUNT(*) AS c FROM users WHERE locked_until > ?", (dbcore.now_iso(),)
        ).fetchone()["c"]
    return {
        "total": total, "active": active, "inactive": total - active,
        "online": online, "locked": locked,
        "by_role": {r: by_role.get(r, 0) for r in ROLES},
    }
