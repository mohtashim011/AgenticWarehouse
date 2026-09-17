"""
Database core
=============
One place that owns the SQLite file: where it lives, how it is opened, and the
lock that keeps concurrent HTTP handlers from colliding on writes.

Every data module (inventory, users, staff, model metrics) opens its connection
through here, so pointing the whole application at a throwaway database — which
is exactly what ``verify.py`` does — is a single call to :func:`set_db_path`.

Standard library only (``sqlite3``, ``threading``).
"""

import os
import sqlite3
import threading
from datetime import datetime, timezone

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The live database. Changed only through set_db_path() so that every module
# sees the same file — a stale copy of this string in another module was the
# obvious way for a test to write into real data by accident.
_state = {"path": os.path.join(_BASE, "data", "warehouse.db")}

# A single writer lock. SQLite itself serialises writes, but taking the lock in
# Python turns a lock-timeout error into a short wait instead of a failed scan.
_lock = threading.Lock()


def db_path():
    return _state["path"]


def set_db_path(path):
    """Point the whole application at another database file."""
    _state["path"] = path


def lock():
    """The shared write lock, for ``with dbcore.lock():`` blocks."""
    return _lock


def connect():
    """Open a connection with the settings every module expects."""
    conn = sqlite3.connect(db_path(), timeout=10.0)
    conn.row_factory = sqlite3.Row
    # WAL lets readers run while a write is in flight, which matters as soon as
    # several staff scan at once.
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def ensure_dir():
    os.makedirs(os.path.dirname(db_path()), exist_ok=True)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def table_columns(conn, table):
    """Column names of a table — the basis of every idempotent migration."""
    return {r["name"] for r in conn.execute("PRAGMA table_info(%s)" % table)}


def table_exists(conn, table):
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None
