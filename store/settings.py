"""
Settings
========
System-wide preferences, stored as typed key/value rows.

Kept in the database rather than a config file so a manager can change them from
the Settings screen without touching the server, and so every change lands in
the audit trail with a name against it.
"""

import json

from core import dbcore

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    updated_by TEXT NOT NULL DEFAULT ''
);
"""

#: Every setting, its default, and what it means. The UI is generated from this,
#: so adding a setting here is all that is needed to expose it.
DEFINITIONS = {
    "warehouse_name": {
        "default": "Agentic Warehouse",
        "type": "text",
        "group": "General",
        "label": "Warehouse name",
        "help": "Shown in the sidebar and on exported reports.",
    },
    "lead_time_days": {
        "default": 7,
        "type": "number",
        "group": "Procurement",
        "label": "Supplier lead time (days)",
        "help": "How long a replacement order takes to arrive. Drives the "
                "reorder point the Procurement Agent calculates.",
    },
    "low_stock_default": {
        "default": 0,
        "type": "number",
        "group": "Procurement",
        "label": "Default reorder level for new products",
        "help": "0 means no alert until someone sets one.",
    },
    "double_read_window": {
        "default": 2.0,
        "type": "number",
        "group": "Scanning",
        "label": "Same-item delay (seconds)",
        "help": "A camera reads a label many times a second. Two reads of the "
                "same product closer together than this count as one item, so "
                "holding a box under the lens adds one unit and not a dozen. "
                "Present the same product again after this delay to add another. "
                "Typing a code in, or using a sample chip, is never delayed.",
    },
    "recovery_auto_apply": {
        "default": 0.80,
        "type": "number",
        "group": "Scanning",
        "label": "Auto-apply threshold for scan recovery",
        "help": "A repaired scan at or above this confidence is applied without "
                "asking. Below it, the operator confirms.",
    },
    "camera_failover_seconds": {
        "default": 12,
        "type": "number",
        "group": "Scanning",
        "label": "Camera failover timeout (seconds)",
        "help": "How long the primary camera may go without decoding before the "
                "system switches to the backup camera.",
    },
    "session_hours": {
        "default": 12,
        "type": "number",
        "group": "Security",
        "label": "Session length (hours)",
        "help": "How long a sign-in lasts before it must be repeated.",
    },
    "retrain_threshold": {
        "default": 3,
        "type": "number",
        "group": "Models",
        "label": "Retrain after this many new categorisations",
        "help": "The Learning Agent retrains once this many products have been "
                "filed since the last run.",
    },
    "auto_retrain": {
        "default": True,
        "type": "boolean",
        "group": "Models",
        "label": "Retrain automatically",
        "help": "Retrain in the background when enough new examples accumulate.",
    },
}


def init_settings():
    dbcore.ensure_dir()
    with dbcore.lock(), dbcore.connect() as conn:
        conn.executescript(SCHEMA)


def _coerce(key, raw):
    """Read a stored string back as the type the definition declares."""
    spec = DEFINITIONS.get(key)
    if spec is None:
        return raw
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        value = raw
    if spec["type"] == "number":
        try:
            value = float(value)
            return int(value) if value == int(value) else value
        except (TypeError, ValueError):
            return spec["default"]
    if spec["type"] == "boolean":
        return bool(value)
    return str(value)


def all_settings():
    """Every setting, with its stored value or its default."""
    with dbcore.lock(), dbcore.connect() as conn:
        stored = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM settings")}
    out = {}
    for key, spec in DEFINITIONS.items():
        out[key] = _coerce(key, stored[key]) if key in stored else spec["default"]
    return out


def get(key, default=None):
    """One setting's value, falling back to its declared default.

    Tolerates the table not existing yet. A setting is a preference, and no
    preference is worth failing a request over — an agent that cannot read its
    lead time should use the default lead time, not return a 500.
    """
    import sqlite3

    spec = DEFINITIONS.get(key, {})
    fallback = spec.get("default", default)
    try:
        with dbcore.lock(), dbcore.connect() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    except sqlite3.OperationalError:
        return fallback
    if row is None:
        return fallback
    return _coerce(key, row["value"])


def set_many(values, actor=None):
    """Update settings. Unknown keys are refused rather than silently stored."""
    unknown = [k for k in values if k not in DEFINITIONS]
    if unknown:
        return False, "Unknown setting(s): %s." % ", ".join(sorted(unknown))

    changed = []
    with dbcore.lock(), dbcore.connect() as conn:
        for key, value in values.items():
            spec = DEFINITIONS[key]
            if spec["type"] == "number":
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    return False, "'%s' must be a number." % spec["label"]
                if value < 0:
                    return False, "'%s' cannot be negative." % spec["label"]
            elif spec["type"] == "boolean":
                value = bool(value)
            else:
                value = str(value).strip()
                if not value:
                    return False, "'%s' cannot be empty." % spec["label"]
            conn.execute(
                """INSERT INTO settings(key, value, updated_at, updated_by)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET value = excluded.value,
                       updated_at = excluded.updated_at,
                       updated_by = excluded.updated_by""",
                (key, json.dumps(value), dbcore.now_iso(),
                 (actor or {}).get("username", "")),
            )
            changed.append(spec["label"])
    return True, "Updated: %s." % ", ".join(changed)


def described():
    """Definitions plus current values, grouped — the Settings screen reads this."""
    values = all_settings()
    groups = {}
    for key, spec in DEFINITIONS.items():
        groups.setdefault(spec["group"], []).append({
            "key": key,
            "label": spec["label"],
            "help": spec["help"],
            "type": spec["type"],
            "value": values[key],
            "default": spec["default"],
        })
    return [{"group": g, "settings": s} for g, s in sorted(groups.items())]
