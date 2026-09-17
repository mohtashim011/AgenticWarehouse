"""
Authentication Agent
====================
Decides whether a sign-in attempt should be granted, and how much to trust it.

Credential checking itself is arithmetic — the password hash either matches or
it does not, and that lives in :mod:`store.users`. What makes this an agent is
everything around that: it scores the *context* of the attempt (time of day,
address, how the account has been behaving) and can accept a correct password
while still flagging the session as unusual for an administrator to review.

Risk signals
------------
* repeated failures against the account in the recent past
* a first-ever sign-in from a new address
* an attempt far outside the account's usual hours
* an administrator signing in, which is always worth recording
* an account still carrying its initial password
"""

from datetime import datetime, timezone

from core import dbcore
from store import users
from agents.base import Agent, Decision, ACCEPT, REJECT, FLAG, register


@register
class AuthenticationAgent(Agent):
    name = "Authentication Agent"
    role = "Grants or refuses access, and scores how unusual each sign-in is."
    method = "credential verification + contextual risk scoring"
    layer = "security"

    # An attempt scoring at or above this is worth surfacing to an admin.
    RISK_THRESHOLD = 0.5

    def decide(self, context):
        username = (context.get("username") or "").strip()
        password = context.get("password") or ""
        ip = context.get("ip", "")
        user_agent = context.get("user_agent", "")

        history = self._recent_history(username)
        user, reason = users.authenticate(username, password, ip, user_agent)

        if user is None:
            d = Decision(self.name, REJECT, 1.0, method=self.method)
            d.data = {"granted": False, "message": reason, "user": None}
            d.note("Sign-in refused for '%s'." % (username or "(blank)"))
            d.note(reason)
            if history["failures"] >= 3:
                d.note("This account has failed %d times recently — possible "
                       "password guessing." % history["failures"])
                d.data["alert"] = True
            return d

        risk, signals = self._score(user, ip, history)

        d = Decision(self.name, FLAG if risk >= self.RISK_THRESHOLD else ACCEPT,
                     confidence=round(1.0 - risk, 3), method=self.method)
        d.data = {
            "granted": True,
            "message": "Signed in.",
            "user": user,
            "risk": round(risk, 2),
            "signals": signals,
        }
        d.note("Credentials verified for '%s' (%s)." % (user["username"], user["role_label"]))
        for s in signals:
            d.note(s)
        if not signals:
            d.note("Nothing unusual about this sign-in.")
        if user.get("must_change_pw"):
            d.note("This account is still on its initial password and must change it.")
        return d

    # -- risk scoring ----------------------------------------------------
    def _score(self, user, ip, history):
        risk = 0.0
        signals = []

        if history["failures"] >= 2:
            risk += 0.3
            signals.append(
                "Signed in after %d failed attempt(s) — worth a glance."
                % history["failures"])

        if ip and ip not in history["known_ips"] and history["known_ips"]:
            risk += 0.25
            signals.append("First sign-in seen from address %s." % ip)

        hour = datetime.now(timezone.utc).hour
        if hour < 5 or hour >= 22:
            risk += 0.2
            signals.append("Outside normal working hours (%02d:00 UTC)." % hour)

        if user.get("role") == "admin":
            risk += 0.15
            signals.append("Administrator access — recorded for the audit trail.")

        if user.get("must_change_pw"):
            risk += 0.2
            signals.append("Account is still using its initial password.")

        return min(risk, 1.0), signals

    def _recent_history(self, username):
        """What this account has been doing lately."""
        if not username:
            return {"failures": 0, "known_ips": set()}
        with dbcore.lock(), dbcore.connect() as conn:
            rows = conn.execute(
                """SELECT event, ip FROM user_events
                    WHERE username = ? COLLATE NOCASE
                 ORDER BY id DESC LIMIT 40""",
                (username,),
            ).fetchall()
        failures = 0
        for r in rows:
            # Count only the unbroken run of failures since the last success.
            if r["event"] == "login":
                break
            if r["event"] == "login_failed":
                failures += 1
        known = {r["ip"] for r in rows if r["event"] == "login" and r["ip"]}
        return {"failures": failures, "known_ips": known}

    def fallback(self, context, error):
        """Never let a scoring bug hand out access.

        The risk model is a nice-to-have; the credential check is not. If
        anything in here breaks, the safe answer is to refuse.
        """
        d = Decision(self.name, REJECT, 0.0, method="fail-closed", degraded=True)
        d.data = {"granted": False, "user": None,
                  "message": "Sign-in is temporarily unavailable. Try again shortly."}
        d.note("The authentication agent failed (%s)." % error.__class__.__name__)
        d.note("Access was refused rather than granted — this agent fails closed.")
        return d


@register
class AuthorisationAgent(Agent):
    """Decides whether an already-identified user may perform an action.

    Separate from authentication on purpose: knowing *who* someone is and
    deciding *what they may do* are different questions, and keeping them apart
    means a change to the permission matrix cannot weaken the login path.
    """

    name = "Authorisation Agent"
    role = "Decides whether the signed-in user may perform the requested action."
    method = "role capability matrix"
    layer = "security"

    def decide(self, context):
        user = context.get("user")
        capability = context.get("capability", "")

        if user is None:
            d = Decision(self.name, REJECT, 1.0, method=self.method)
            d.data = {"allowed": False, "message": "Please sign in first."}
            d.note("No signed-in user for a request needing '%s'." % capability)
            return d

        allowed = users.can(user, capability)
        d = Decision(self.name, ACCEPT if allowed else REJECT, 1.0, method=self.method)
        d.data = {
            "allowed": allowed,
            "message": "" if allowed else (
                "Your role (%s) does not include this action." % user.get("role_label")),
        }
        if allowed:
            d.note("%s holds '%s'." % (user.get("role_label"), capability))
        else:
            d.note("%s does not hold '%s'." % (user.get("role_label"), capability))
            d.note("Roles that do: %s." % ", ".join(
                users.ROLE_LABELS[r] for r in users.ROLES
                if capability in users.CAPABILITIES[r]) or "none")
        return d

    def fallback(self, context, error):
        d = Decision(self.name, REJECT, 0.0, method="fail-closed", degraded=True)
        d.data = {"allowed": False, "message": "Permission check unavailable."}
        d.note("Refused by default because the check could not run.")
        return d
