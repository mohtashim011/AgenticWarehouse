"""
Vision Agent
============
Decides what to do when a camera stops being useful.

Only the browser can *see* a camera, so detection has to happen there. Deciding
what to do about it does not — and that is the part that belongs to an agent.
The browser reports symptoms; this agent weighs them against the cameras
available and returns a decision with its reasoning, which the scanner then
shows to the operator.

That split matters. A camera failing over silently is indistinguishable from a
camera that was never working, and an operator who cannot tell the difference
keeps presenting labels to a dead lens.

Symptoms it is asked about
--------------------------
``start_failed``  the camera would not open at all (in use, or refused)
``track_ended``   the stream ended by itself — the usual sign of an unplugged
                  USB camera or a device the OS took away
``no_decode``     the camera is running and producing frames, but nothing has
                  decoded for a while. The hardest case: no error is raised
                  anywhere, so only a timer can catch it
``stalled``       frames stopped arriving although the track is still live

What it weighs
--------------
* whether a backup camera exists at all
* whether that backup has already been tried and failed this session
* whether it is actually attached to this machine right now
* what role a manager gave it, and how well it scored when it was last measured
* how long the symptom has persisted against the configured patience
* whether the operator is even trying to scan right now

Choosing *which* camera to switch to
------------------------------------
Picking the next one in the list was enough while the browser was the only
thing that knew about cameras. It is not enough now that a manager can register
them: a station may have a good USB scanner marked ``backup`` and an infrared
sensor the browser happens to list first. So candidates are ranked — the
designated backup first, then whatever measured best, then list order — and the
reason names the camera and says why it was chosen.

Cameras that are configured but not attached are never proposed. Switching to a
camera that is not plugged in wastes the operator's time and then fails anyway.
"""

from agents.base import Agent, Decision, ACCEPT, FLAG, REJECT, register

#: A camera that has produced nothing for this long, while someone is trying to
#: scan, is not working — whatever it claims about itself.
DEFAULT_PATIENCE = 12.0

SYMPTOMS = ("start_failed", "track_ended", "no_decode", "stalled", "healthy")

#: Symptoms where the camera is definitively gone. No point waiting.
FATAL = ("start_failed", "track_ended")

#: How much each grade is worth when ranking candidates. An untested camera
#: sits between "marginal" and "good": it might be excellent, but a camera
#: measured as good is a better bet than an unknown one.
GRADE_RANK = {"excellent": 4, "good": 3, "untested": 2, "marginal": 1, "unusable": 0}


def _rank(camera, index):
    """Sort key for a switch candidate. Lower is tried first.

    A camera the manager marked as the backup wins outright — that is what the
    designation is *for*, and overriding it with a measurement would make the
    setting meaningless. Below that, measured quality decides, and list order
    breaks the remaining ties so the choice is stable.
    """
    role = (camera.get("role") or "").lower()
    # backup first, then the primary, then anything a manager never registered.
    #
    # The primary used to sort *last* — behind unregistered cameras — so when
    # the backup was the active camera and it failed, the agent preferred an
    # unregistered infrared sensor over the primary that had just recovered.
    # A camera somebody deliberately configured always beats one nobody did.
    role_rank = {"backup": 0, "primary": 1}.get(role, 2)
    grade = (camera.get("grade") or "untested").lower()
    return (role_rank, -GRADE_RANK.get(grade, 2), index)


def _describe(camera, name):
    """Name a camera the way an operator would recognise it."""
    bits = []
    role = (camera.get("role") or "").lower()
    if role in ("primary", "backup"):
        bits.append("the designated %s" % role)
    grade = (camera.get("grade") or "").lower()
    if grade:
        bits.append("last measured %s" % grade)
    elif camera.get("configured"):
        bits.append("not yet measured")
    return "%s (%s)" % (name, ", ".join(bits)) if bits else name


@register
class VisionAgent(Agent):
    name = "Vision Agent"
    role = "Decides when a camera has failed and which one to switch to."
    method = "symptom severity + camera availability"
    layer = "perception"

    def decide(self, context):
        symptom = context.get("symptom", "healthy")
        cameras = context.get("cameras") or []
        active = context.get("active_index", 0)
        tried = set(context.get("tried") or [])
        idle = float(context.get("idle_seconds") or 0)
        decodes = int(context.get("decodes") or 0)
        patience = float(context.get("patience") or DEFAULT_PATIENCE)

        d = Decision(self.name, ACCEPT, 1.0, method=self.method)
        d.data = {"action": "keep", "target": active, "advice": "", "symptom": symptom}

        if symptom not in SYMPTOMS:
            d.note("Unrecognised symptom '%s'; leaving the camera alone." % symptom)
            return d

        if symptom == "healthy":
            d.note("Camera %d is decoding normally." % (active + 1))
            return d

        names = [c.get("label") or ("Camera %d" % (i + 1)) for i, c in enumerate(cameras)]
        current = names[active] if active < len(names) else "the camera"

        # Candidates: anything that is not the current camera, has not already
        # failed this session, and is actually plugged in. Retrying a camera
        # that just refused to open wastes the operator's time twice; proposing
        # one that is not attached wastes it and then fails anyway.
        #
        # `attached` is absent from older clients, which only ever sent id and
        # label. Missing means attached — a client that cannot tell us is a
        # client whose cameras were all attached by construction.
        candidates = [
            i for i, c in enumerate(cameras)
            if i != active
            and i not in tried
            and c.get("attached", True)
            and (c.get("role") or "") != "disabled"
        ]
        candidates.sort(key=lambda i: _rank(cameras[i], i))

        # --- is this actually a failure yet? --------------------------------
        if symptom in ("no_decode", "stalled") and idle < patience:
            d.note("%s has decoded nothing for %.0fs, under the %.0fs allowed."
                   % (current, idle, patience))
            d.note("Not switching yet — a pause between items looks exactly the "
                   "same as a broken camera until the wait is long enough.")
            d.confidence = 0.6
            return d

        # --- describe what went wrong ---------------------------------------
        if symptom == "start_failed":
            d.note("%s would not start. It is usually held by another "
                   "application, or permission was refused for that device." % current)
        elif symptom == "track_ended":
            d.note("%s stopped on its own — the device was disconnected or taken "
                   "by the operating system." % current)
        elif symptom == "stalled":
            d.note("%s is still open but has stopped delivering frames." % current)
        else:
            d.note("%s has been running for %.0fs without decoding anything."
                   % (current, idle))
            if decodes == 0:
                d.note("It has never decoded, so this is not a difficult label — "
                       "the camera cannot resolve codes at all.")
            else:
                d.note("It decoded %d time(s) earlier, so it worked and then "
                       "stopped." % decodes)

        # --- decide -----------------------------------------------------------
        if candidates:
            target = candidates[0]
            chosen = cameras[target]
            d.verdict = FLAG
            d.confidence = 0.9 if symptom in FATAL else 0.75
            d.data.update({
                "action": "switch",
                "target": target,
                "advice": "switch_camera",
                "target_label": names[target],
                "target_role": chosen.get("role") or "",
                "target_grade": chosen.get("grade") or "",
            })
            d.note("Switching to %s." % _describe(chosen, names[target]))
            if len(candidates) > 1:
                d.note("Chosen ahead of %d other camera(s) on this machine."
                       % (len(candidates) - 1))
            d.note("Scanning continues on the backup; nothing needs to be "
                   "re-presented that was already counted.")
            return d

        # No camera left to try.
        d.verdict = REJECT
        d.confidence = 1.0
        attached = [c for c in cameras if c.get("attached", True)]
        exhausted = len(attached) <= 1
        d.data.update({"action": "fallback", "advice": "switch_input", "target": active})
        if exhausted:
            d.note("There is no second camera attached to this machine, so "
                   "there is nothing to switch to.")
            missing = [c for c in cameras if not c.get("attached", True)]
            network = [c for c in missing if (c.get("kind") or "") == "network"]
            if len(missing) > len(network):
                d.note("A backup camera is configured here but is not plugged "
                       "in. Reconnecting it restores automatic failover.")
            elif network:
                # Telling someone to reconnect an IP camera would send them to
                # check a cable that was never the problem: a browser cannot
                # open an http stream as a live camera at all.
                d.note("The only other camera configured here is a network "
                       "camera, which a browser cannot open as a live camera. "
                       "Failover needs a second built-in or USB camera.")
        else:
            # Distinguish "all tried and all failed" from "the only ones left
            # are switched off". Saying every camera has failed when a working
            # one is merely disabled sends the operator looking for a hardware
            # fault that does not exist.
            skipped = [i for i, c in enumerate(cameras)
                       if i != active and i not in tried
                       and c.get("attached", True)
                       and (c.get("role") or "") == "disabled"]
            if skipped:
                d.note("%d other camera(s) attached here are switched off in the "
                       "camera settings, so they were not tried. Turning one on "
                       "restores automatic failover." % len(skipped))
            else:
                d.note("Every camera on this machine has now been tried and none "
                       "of them works.")
        d.note("Use 'Scan a photo' — a phone photo resolves bars a webcam "
               "cannot — or type the code in. Both still work.")
        return d

    def fallback(self, context, error):
        """A failure here must not strand the operator on a dead camera.

        The safe default is to keep going and tell them plainly, rather than to
        switch blindly to a camera that may be worse.
        """
        d = Decision(self.name, FLAG, 0.0, method="unavailable", degraded=True)
        d.data = {"action": "fallback", "advice": "switch_input",
                  "target": context.get("active_index", 0), "symptom": context.get("symptom")}
        d.note("The vision agent could not decide (%s)." % error.__class__.__name__)
        d.note("Switch camera by hand, or use a photo or manual entry.")
        return d
