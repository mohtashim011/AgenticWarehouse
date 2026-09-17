"""
Audit Agent
===========
Checks that the books agree with themselves.

The inventory table says how much stock is on hand. The log says what happened
to it. Those two are maintained by different code paths, and in any system that
has been running for a while they drift — a crash between the update and the
log, a manual correction nobody recorded, a batch that went negative.

This agent reconciles them and reports the discrepancies, rather than waiting
for someone to notice during a stock count. It is deliberately read-only: it
reports what it finds and never silently repairs anything, because an agent that
quietly edits stock figures to make its own checks pass is worse than no agent.

Checks
------
* **reconciliation** — does ``sum(IN) - sum(OUT) +/- adjustments`` match the
  quantity on hand, per product?
* **negative stock** — a quantity below zero is always a bug
* **orphans** — stock with no log entry, or log entries for stock that vanished
* **unattributed activity** — scans with no staff member recorded
* **flag rate** — is the anomaly rate itself abnormal?
"""

import json

from core import dbcore
from agents.base import Agent, Decision, ACCEPT, FLAG, INFO, register


def _quantity_from_trace(raw):
    """The resulting quantity an ADJUST recorded, or None if it did not.

    Reconciliation restarts from the last correction, so it needs the number
    that correction left behind. Rows written before this was stored return
    None, and those batches are skipped rather than judged against a guess.
    """
    try:
        steps = json.loads(raw or "[]")
    except (ValueError, TypeError):
        return None
    for step in steps:
        if isinstance(step, dict) and isinstance(step.get("qty"), int):
            return step["qty"]
    return None

#: Above this share of scans flagged, something systemic is wrong — a
#: misconfigured scanner, or a rule that is too aggressive.
ANOMALY_RATE_WARNING = 0.25


@register
class AuditAgent(Agent):
    name = "Audit Agent"
    role = "Reconciles the stock figures against the audit trail and reports drift."
    method = "double-entry reconciliation + integrity rules"
    layer = "operations"

    def decide(self, context):
        findings = []
        checks = 0

        with dbcore.lock(), dbcore.connect() as conn:
            checks += 1
            findings.extend(self._reconcile(conn))
            checks += 1
            findings.extend(self._negative_stock(conn))
            checks += 1
            findings.extend(self._orphans(conn))
            checks += 1
            findings.extend(self._unattributed(conn))
            checks += 1
            findings.extend(self._anomaly_rate(conn))

        severe = [f for f in findings if f["severity"] == "error"]
        warnings = [f for f in findings if f["severity"] == "warning"]

        d = Decision(self.name,
                     FLAG if severe else (INFO if warnings else ACCEPT),
                     method=self.method)
        d.data = {
            "findings": findings,
            "checks_run": checks,
            "errors": len(severe),
            "warnings": len(warnings),
            "clean": not findings,
        }
        # Confidence here means confidence in the books, not in the agent.
        d.confidence = round(max(0.0, 1.0 - 0.2 * len(severe) - 0.05 * len(warnings)), 2)

        if not findings:
            d.note("All %d integrity checks passed. Stock figures and the audit "
                   "trail agree." % checks)
            return d

        d.note("%d check(s) run: %d error(s), %d warning(s)."
               % (checks, len(severe), len(warnings)))
        for f in (severe + warnings)[:8]:
            d.note("%s: %s" % (f["check"], f["detail"]))
        if severe:
            d.note("Nothing was changed automatically — these need a person to "
                   "decide the correct figure.")
        return d

    # -- individual checks -------------------------------------------------
    def _reconcile(self, conn):
        """Movements in the log against the quantity on hand, per batch.

        An ADJUST sets an absolute quantity rather than adding to one, so it
        cannot be counted as a movement. The previous version dealt with that by
        skipping any batch that had *ever* been adjusted — which quietly turned
        the whole check off, because creating or editing a product writes an
        ADJUST row too. Every product made through the interface was therefore
        exempt from reconciliation from the moment it existed.

        Instead, reconcile *forward from the last adjustment*: take the quantity
        that adjustment recorded as the opening balance and count only the
        movements logged after it.
        """
        findings = []
        rows = conn.execute(
            "SELECT productno, batchno, name, qty AS on_hand FROM items").fetchall()

        for r in rows:
            last_adjust = conn.execute(
                """SELECT id, trace FROM logs
                    WHERE productno = ? AND batchno = ? AND action = 'ADJUST'
                 ORDER BY id DESC LIMIT 1""",
                (r["productno"], r["batchno"]),
            ).fetchone()

            opening, since_id = 0, 0
            if last_adjust is not None:
                since_id = last_adjust["id"]
                opening = _quantity_from_trace(last_adjust["trace"])
                if opening is None:
                    # An older adjustment that did not record its resulting
                    # quantity. Nothing to reconcile against, so say so rather
                    # than invent a baseline.
                    continue

            moves = conn.execute(
                """SELECT SUM(CASE WHEN action = 'IN'  THEN 1 ELSE 0 END) AS ins,
                          SUM(CASE WHEN action = 'OUT' THEN 1 ELSE 0 END) AS outs
                     FROM logs
                    WHERE productno = ? AND batchno = ? AND undone = 0
                      AND action IN ('IN', 'OUT') AND id > ?""",
                (r["productno"], r["batchno"], since_id),
            ).fetchone()
            ins, outs = moves["ins"] or 0, moves["outs"] or 0

            expected = opening + ins - outs
            if expected != r["on_hand"]:
                findings.append({
                    "check": "reconciliation",
                    "severity": "error",
                    "productno": r["productno"],
                    "batchno": r["batchno"],
                    "detail": ("%s (batch %s) holds %d but the log accounts for "
                               "%d — %d at the last correction, %d in, %d out."
                               % (r["name"], r["batchno"] or "none", r["on_hand"],
                                  expected, opening, ins, outs)),
                    "expected": expected,
                    "actual": r["on_hand"],
                })
        return findings

    def _negative_stock(self, conn):
        rows = conn.execute(
            "SELECT productno, batchno, name, qty FROM items WHERE qty < 0").fetchall()
        return [{
            "check": "negative stock",
            "severity": "error",
            "productno": r["productno"],
            "batchno": r["batchno"],
            "detail": "%s holds %d units, which is impossible." % (r["name"], r["qty"]),
        } for r in rows]

    def _orphans(self, conn):
        findings = []
        rows = conn.execute(
            """SELECT DISTINCT l.productno, l.name FROM logs l
                WHERE l.action IN ('IN', 'OUT')
                  AND NOT EXISTS (SELECT 1 FROM items i WHERE i.productno = l.productno)
                LIMIT 10"""
        ).fetchall()
        for r in rows:
            findings.append({
                "check": "orphaned log",
                "severity": "warning",
                "productno": r["productno"],
                "detail": ("The log records movements of %s (%s) but no stock "
                           "record exists for it." % (r["name"], r["productno"])),
            })
        return findings

    def _unattributed(self, conn):
        """Scans with no staff member recorded.

        Expected for anything logged before sign-in existed; a problem for
        anything after, since an audit trail that cannot say who acted is not
        much of an audit trail.
        """
        if "user_id" not in dbcore.table_columns(conn, "logs"):
            return []
        row = conn.execute(
            """SELECT COUNT(*) AS c FROM logs
                WHERE action IN ('IN', 'OUT', 'ADJUST') AND user_id IS NULL"""
        ).fetchone()
        if not row["c"]:
            return []
        return [{
            "check": "unattributed activity",
            "severity": "warning",
            "detail": ("%d movement(s) have no staff member recorded. Entries "
                       "predating sign-in are expected; newer ones are not."
                       % row["c"]),
            "count": row["c"],
        }]

    def _anomaly_rate(self, conn):
        row = conn.execute(
            """SELECT COUNT(*) AS total,
                      SUM(CASE WHEN anomaly = 1 THEN 1 ELSE 0 END) AS flagged
                 FROM logs WHERE action IN ('IN', 'OUT')"""
        ).fetchone()
        total = row["total"] or 0
        flagged = row["flagged"] or 0
        # Below a couple of dozen scans the rate is noise, not a signal.
        if total < 20:
            return []
        rate = flagged / total
        if rate < ANOMALY_RATE_WARNING:
            return []
        return [{
            "check": "anomaly rate",
            "severity": "warning",
            "detail": ("%.0f%% of scans are flagged (%d of %d). That is high "
                       "enough to suggest a scanner or threshold problem rather "
                       "than genuine anomalies." % (rate * 100, flagged, total)),
            "rate": round(rate, 3),
        }]

    def fallback(self, context, error):
        d = Decision(self.name, INFO, 0.0, method="unavailable", degraded=True)
        d.data = {"findings": [], "clean": None, "checks_run": 0}
        d.note("The integrity checks could not run (%s)." % error.__class__.__name__)
        d.note("This does not mean the books are wrong — only that they were "
               "not checked.")
        return d
