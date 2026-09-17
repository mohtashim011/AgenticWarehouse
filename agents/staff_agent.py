"""
Staff Agent
===========
Owns decisions about people: who may be created, promoted, disabled or removed,
and whether the resulting shape of the team is safe.

Creating a user is a database insert; deciding whether it *should* happen is
not. This agent applies the rules that keep an organisation out of trouble —
never leaving the system without an administrator, noticing when far too many
people hold administrative rights, refusing a role change that would let someone
quietly grant themselves more power than they were given.
"""

from store import users
from agents.base import Agent, Decision, ACCEPT, REJECT, FLAG, register


@register
class StaffAgent(Agent):
    name = "Staff Agent"
    role = "Decides whether a staff account change is safe to make."
    method = "organisational policy rules"
    layer = "administration"

    #: Above this share of administrators, privilege is too widely spread for
    #: the audit trail to mean much.
    ADMIN_SHARE_WARNING = 0.34

    def decide(self, context):
        action = context.get("action", "")
        actor = context.get("actor")
        target = context.get("target")          # existing user, for updates
        payload = context.get("payload", {})

        d = Decision(self.name, ACCEPT, 1.0, method=self.method)
        d.data = {"allowed": True, "message": "", "warnings": []}

        handler = {
            "create": self._create,
            "update": self._update,
            "delete": self._delete,
            "reset_password": self._reset_password,
        }.get(action)

        if handler is None:
            d.verdict = REJECT
            d.data["allowed"] = False
            d.data["message"] = "Unknown staff action '%s'." % action
            d.note(d.data["message"])
            return d

        handler(d, actor, target, payload)
        return d

    # -- individual decisions --------------------------------------------
    def _create(self, d, actor, target, payload):
        role = payload.get("role", "staff")
        username = (payload.get("username") or "").strip()

        if role == "admin" and (actor or {}).get("role") != "admin":
            self._refuse(d, "Only an administrator can create another administrator.")
            return

        d.note("Creating '%s' as %s." % (username, users.ROLE_LABELS.get(role, role)))
        d.note("Requested by %s." % self._who(actor))

        summary = users.staff_summary()
        if role == "admin":
            admins = summary["by_role"].get("admin", 0) + 1
            total = summary["active"] + 1
            if total >= 4 and admins / total > self.ADMIN_SHARE_WARNING:
                d.verdict = FLAG
                d.confidence = 0.7
                warning = ("%d of %d active accounts would be administrators. "
                           "Consider Warehouse Manager instead — it covers daily "
                           "operations without staff or settings access."
                           % (admins, total))
                d.data["warnings"].append(warning)
                d.note(warning)

        if payload.get("must_change_pw", True):
            d.note("The account starts with a temporary password it must change "
                   "at first sign-in.")

    def _update(self, d, actor, target, payload):
        if not target:
            self._refuse(d, "No such staff member.")
            return

        new_role = payload.get("role")
        setting_active = payload.get("active")
        is_self = actor and actor.get("id") == target.get("id")

        d.note("Updating '%s' (currently %s)."
               % (target.get("username"), target.get("role_label")))

        # Nobody edits their own privileges, however senior. The check exists so
        # that a compromised session cannot quietly widen its own reach.
        if is_self and new_role and new_role != target.get("role"):
            self._refuse(d, "You cannot change your own role. Ask another administrator.")
            return
        if is_self and setting_active in (0, False):
            self._refuse(d, "You cannot deactivate your own account.")
            return

        if new_role and new_role != target.get("role"):
            d.note("Role change: %s -> %s."
                   % (users.ROLE_LABELS.get(target.get("role")),
                      users.ROLE_LABELS.get(new_role, new_role)))
            if new_role == "admin" and (actor or {}).get("role") != "admin":
                self._refuse(d, "Only an administrator can promote someone to administrator.")
                return
            gained = users.CAPABILITIES.get(new_role, set()) - users.CAPABILITIES.get(
                target.get("role"), set())
            lost = users.CAPABILITIES.get(target.get("role"), set()) - users.CAPABILITIES.get(
                new_role, set())
            if gained:
                d.note("Gains: %s." % ", ".join(sorted(gained)))
            if lost:
                d.note("Loses: %s." % ", ".join(sorted(lost)))

        # The store enforces the last-administrator rule too; saying it here as
        # well means the person gets the reason before the button does anything.
        if target.get("role") == "admin" and (
                setting_active in (0, False) or (new_role and new_role != "admin")):
            if users.staff_summary()["by_role"].get("admin", 0) <= 1:
                self._refuse(d, "This is the last active administrator. Promote "
                                "someone else first.")
                return

        if setting_active in (0, False):
            d.verdict = FLAG if d.verdict == ACCEPT else d.verdict
            d.note("Deactivating an account also ends its live sessions immediately.")

    def _delete(self, d, actor, target, payload):
        if not target:
            self._refuse(d, "No such staff member.")
            return
        if actor and actor.get("id") == target.get("id"):
            self._refuse(d, "You cannot delete your own account.")
            return
        if (actor or {}).get("role") != "admin":
            self._refuse(d, "Only an administrator can remove a staff account.")
            return
        d.note("Removing '%s'." % target.get("username"))
        d.note("Their entries in the audit trail are kept — a log that forgets "
               "who acted is not an audit trail.")
        d.verdict = FLAG
        d.confidence = 0.9
        d.data["warnings"].append(
            "Deactivating instead of deleting keeps the account's history "
            "attributable and can be reversed.")

    def _reset_password(self, d, actor, target, payload):
        if not target:
            self._refuse(d, "No such staff member.")
            return
        is_self = actor and actor.get("id") == target.get("id")
        if not is_self and (actor or {}).get("role") != "admin":
            self._refuse(d, "Only an administrator can reset someone else's password.")
            return
        if is_self:
            d.note("Self-service password change; the current password is required.")
        else:
            d.note("Administrator reset for '%s'." % target.get("username"))
            d.note("The account must choose a new password at its next sign-in.")
            d.note("All of its existing sessions are ended.")

    # -- helpers ---------------------------------------------------------
    def _refuse(self, d, message):
        d.verdict = REJECT
        d.confidence = 1.0
        d.data["allowed"] = False
        d.data["message"] = message
        d.note(message)

    @staticmethod
    def _who(actor):
        if not actor:
            return "the system"
        return "%s (%s)" % (actor.get("username"), actor.get("role_label", actor.get("role")))

    def fallback(self, context, error):
        d = Decision(self.name, REJECT, 0.0, method="fail-closed", degraded=True)
        d.data = {"allowed": False, "warnings": [],
                  "message": "Staff policy check unavailable; the change was not made."}
        d.note("Refused by default because the policy check could not run.")
        return d
