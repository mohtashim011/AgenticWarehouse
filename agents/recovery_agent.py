"""
Recovery Agent  (the backup scanner)
====================================
Takes a scan that did not work and tries to work out what it was meant to be.

A warehouse scan fails in ordinary, repetitive ways: a wedge scanner appends a
carriage return, a phone camera clips the last digit of a long barcode, a
GS1 label arrives wrapped in application identifiers, someone types ``O`` where
the label prints ``0``. None of these are exotic, and every one of them
currently ends the same way — as an unknown item that a person has to fix by
hand later.

This agent sits behind the scanner and applies repair strategies in order of how
much they assume, stopping at the first that produces a code the warehouse
actually holds. It never silently rewrites a scan: every repair is reported with
the strategy that produced it and a confidence, and anything below
:data:`AUTO_ACCEPT` is offered as a suggestion for a person to confirm rather
than applied on its own.

Strategies, from safest to boldest
----------------------------------
1. **normalise** — trim, drop control characters and wedge artefacts
2. **gs1** — unwrap GS1 application identifiers into GTIN / batch / serial
3. **check-digit** — add, drop or correct an EAN/UPC check digit
4. **prefix** — a clipped read that is the start of exactly one known code
5. **confusion** — repair one OCR-style character confusion (O/0, I/1, S/5, B/8)
6. **transposition** — repair one adjacent swap
7. **fuzzy-name** — match a garbled QR product name against the catalogue
"""

import re

import db
from core.barcode import is_numeric as _is_numeric
from agents.base import Agent, Decision, ACCEPT, REJECT, INFO, register

#: A repaired code at or above this confidence is applied automatically.
#: Below it, the repair is returned as a suggestion for a human to confirm.
AUTO_ACCEPT = 0.80

# Control characters, and the prefixes wedge scanners and GS1 labels prepend.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WEDGE_PREFIXES = ("]C1", "]e0", "]d2", "]Q3", "]A0", "")
_GS1_AI = re.compile(r"\((\d{2,4})\)([^(]+)")

# Characters people and OCR routinely confuse for one another.
_CONFUSIONS = {
    "O": "0", "0": "O", "o": "0",
    "I": "1", "l": "1", "1": "I",
    "S": "5", "5": "S", "s": "5",
    "B": "8", "8": "B",
    "Z": "2", "2": "Z",
    "G": "6", "6": "G",
}


@register
class RecoveryAgent(Agent):
    name = "Recovery Agent"
    role = "Repairs a failed or garbled scan so a bad read does not stop the line."
    method = "ordered repair strategies + catalogue matching"
    layer = "perception"

    #: The repair strategies, in the order they are applied. Each name maps to a
    #: ``_<name>`` method, and ``decide`` iterates this tuple rather than an
    #: inline list — so anything that reports "seven strategies" is counting the
    #: same tuple the pipeline actually executes.
    #:
    #: ``fuzzy_name`` is last and is handled separately: it matches a garbled
    #: product *name* rather than a code, so it runs even when the earlier
    #: strategies already found something.
    STRATEGIES = ("normalise", "gs1", "check_digit", "prefix", "confusion",
                  "transposition", "fuzzy_name")

    def decide(self, context):
        raw = context.get("code") or ""
        reason = context.get("reason", "")
        known = self._known_codes()

        d = Decision(self.name, INFO, 0.0, method=self.method)
        d.data = {"repaired": None, "candidates": [], "strategy": None,
                  "auto_apply": False, "fields": {}}

        if not raw.strip():
            d.verdict = REJECT
            d.note("Nothing was decoded, so there is nothing to repair.")
            d.note("Use the second camera, a photo, or manual entry.")
            d.data["advice"] = "switch_input"
            return d

        d.note("Attempting recovery of %r%s." % (
            raw[:60], (" after: " + reason) if reason else ""))

        candidates = []
        # Ordered by how much each one assumes, from "the reader added noise" to
        # "two digits were swapped". The order is STRATEGIES, so the documented
        # count and the executed count cannot drift apart.
        for name in self.STRATEGIES[:-1]:
            for cand in getattr(self, "_" + name)(raw, known):
                if cand and cand not in candidates:
                    candidates.append(cand)
            # Stop as soon as a strategy produces something the warehouse holds.
            if any(c["known"] for c in candidates):
                break

        # A QR payload carries a name; a garbled name can be matched even when
        # the product number is a total loss.
        candidates.extend(self._fuzzy_name(raw))

        candidates.sort(key=lambda c: (-c["confidence"], c["strategy"]))
        d.data["candidates"] = candidates[:6]

        best = next((c for c in candidates if c["known"]), None) or (
            candidates[0] if candidates else None)

        if best is None:
            d.verdict = REJECT
            d.note("No repair strategy produced a code this warehouse holds.")
            d.note("Try the backup camera, a still photo, or type the number in.")
            d.data["advice"] = "switch_input"
            return d

        d.verdict = ACCEPT if best["known"] else INFO
        d.confidence = best["confidence"]
        d.data.update({
            "repaired": best["code"],
            "strategy": best["strategy"],
            "auto_apply": best["known"] and best["confidence"] >= AUTO_ACCEPT,
            "fields": best.get("fields", {}),
        })
        d.note("%s: %r -> %r." % (best["explanation"], raw[:40], best["code"]))
        if best["known"]:
            d.note("That code matches stock already on hand.")
        else:
            d.note("No stock matches it, so this is a suggestion only.")
        if not d.data["auto_apply"]:
            d.note("Confidence %.0f%% is below the %.0f%% needed to apply it "
                   "automatically — confirm before it is used."
                   % (best["confidence"] * 100, AUTO_ACCEPT * 100))
        return d

    # -- strategies ------------------------------------------------------
    def _normalise(self, raw, known):
        """Trim, strip control characters and remove wedge-scanner prefixes."""
        s = _CONTROL.sub("", raw).strip()
        for p in _WEDGE_PREFIXES:
            if s.startswith(p):
                s = s[len(p):].strip()
        if s and s != raw:
            return [self._cand(s, "normalise", 0.97,
                               "Removed control characters and scanner prefix", known)]
        return []

    def _gs1(self, raw, known):
        """Unwrap a GS1 label into its GTIN, batch and serial.

        A GS1-128 label carries several fields at once, e.g.
        ``(01)07890765423458(10)27020(21)0007`` — product, batch and serial.
        Read whole, it matches nothing; split, it is a perfectly ordinary scan.
        """
        pairs = _GS1_AI.findall(raw)
        if not pairs:
            return []
        fields = {ai: val.strip() for ai, val in pairs}
        gtin = fields.get("01") or fields.get("02")
        if not gtin:
            return []
        extra = {"batchno": fields.get("10", ""),
                 "serial": fields.get("21", ""),
                 "expiry": fields.get("17", "")}

        # A GTIN-14 is an EAN-13 with a packaging indicator in front, and the
        # warehouse may hold the number with or without its check digit — so
        # every spelling of the extracted GTIN has to be offered, not just the
        # literal one printed on the label.
        forms = [gtin, gtin.lstrip("0") or gtin]
        for form in list(forms):
            forms.extend(db._code_variants(form))

        out, seen = [], set()
        for code in forms:
            if not code or code in seen:
                continue
            seen.add(code)
            out.append(self._cand(
                code, "gs1", 0.95,
                "Unwrapped GS1 application identifiers", known, fields=extra))
        return out

    def _check_digit(self, raw, known):
        """Add, drop or correct an EAN/UPC check digit."""
        s = raw.strip()
        # is_numeric, not str.isdigit: the latter passes superscripts that int()
        # then refuses, and `body` below goes straight into a check-digit sum.
        if not _is_numeric(s):
            return []
        out = []
        for variant in db._code_variants(s):
            out.append(self._cand(
                variant, "check-digit", 0.92,
                "Adjusted the barcode check digit", known))
        # A wrong final digit: recompute what it should have been.
        if len(s) in (8, 12, 13, 14):
            body = s[:-1]
            fixed = body + db._ean_check_digit(body)
            if fixed != s:
                out.append(self._cand(
                    fixed, "check-digit", 0.85,
                    "Recomputed an invalid check digit", known))
        return out

    def _prefix(self, raw, known):
        """A clipped read that is the unambiguous start of one known code."""
        s = raw.strip()
        if len(s) < 5:
            return []
        matches = [k for k in known if k.startswith(s) and k != s]
        if len(matches) == 1:
            return [self._cand(
                matches[0], "prefix", 0.88,
                "Completed a truncated read (only one product starts this way)", known)]
        if len(matches) > 1:
            # Ambiguous: offer them, but never at a confidence that auto-applies.
            return [self._cand(m, "prefix", 0.45,
                               "Possible completion of a truncated read", known)
                    for m in matches[:3]]
        return []

    def _confusion(self, raw, known):
        """Repair a single OCR-style character confusion."""
        s = raw.strip()
        if len(s) > 20:
            return []
        out = []
        for i, ch in enumerate(s):
            swap = _CONFUSIONS.get(ch)
            if not swap:
                continue
            cand = s[:i] + swap + s[i + 1:]
            if cand in known:
                out.append(self._cand(
                    cand, "confusion", 0.86,
                    "Corrected '%s' read as '%s'" % (swap, ch), known))
        return out

    def _transposition(self, raw, known):
        """Repair a single adjacent swap, the classic typing slip."""
        s = raw.strip()
        if len(s) > 20:
            return []
        out = []
        for i in range(len(s) - 1):
            cand = s[:i] + s[i + 1] + s[i] + s[i + 2:]
            if cand != s and cand in known:
                out.append(self._cand(
                    cand, "transposition", 0.82,
                    "Undid a swap of two adjacent characters", known))
        return out

    def _fuzzy_name(self, raw):
        """Match a garbled QR product name against the catalogue."""
        if "," not in raw:
            return []
        name = raw.split(",")[0].strip()
        if len(name) < 4:
            return []
        best, score = None, 0.0
        for row in db.catalog_rows():
            s = _similarity(name.lower(), row["name"].lower())
            if s > score:
                best, score = row["name"], s
        if best and score >= 0.72 and best.lower() != name.lower():
            return [{
                "code": best,
                "strategy": "fuzzy-name",
                "confidence": round(score * 0.9, 2),
                "explanation": "Matched a garbled product name to '%s'" % best,
                "known": False,
                "kind": "name",
                "fields": {"name": best},
            }]
        return []

    # -- helpers ---------------------------------------------------------
    def _cand(self, code, strategy, confidence, explanation, known, fields=None):
        is_known = code in known
        return {
            "code": code,
            "strategy": strategy,
            # A repair that lands on real stock is worth far more than one that
            # merely produces a well-formed string.
            "confidence": round(confidence if is_known else confidence * 0.55, 2),
            "explanation": explanation,
            "known": is_known,
            "kind": "code",
            "fields": fields or {},
        }

    def _known_codes(self):
        """Every product number and alias the warehouse recognises."""
        codes = set()
        for row in db.inventory_summary()["rows"]:
            for b in row.get("batches", []):
                if b.get("productno"):
                    codes.add(str(b["productno"]))
        codes.update(db.alias_codes())
        return codes

    def fallback(self, context, error):
        d = Decision(self.name, INFO, 0.0, method="unavailable", degraded=True)
        d.data = {"repaired": None, "candidates": [], "auto_apply": False,
                  "advice": "switch_input"}
        d.note("Recovery could not run (%s)." % error.__class__.__name__)
        d.note("Fall back to the second camera, a photo, or manual entry.")
        return d


def _similarity(a, b):
    """Normalised Levenshtein similarity in [0, 1].

    Written out rather than imported from ``difflib`` because the ratio here
    needs to be edit-distance based: ``difflib`` scores by matching blocks and
    rates transpositions far more generously than a warehouse should.
    """
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return 1.0 - prev[-1] / max(len(a), len(b))
