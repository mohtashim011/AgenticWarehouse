"""
Agent framework
===============
Every component of this system is an agent: it observes a context, reaches its
own decision, explains why, and reports how confident it is. The orchestrator
coordinates them but never decides for them — that separation is the whole
argument of the research proposal.

What an agent is
----------------
A subclass of :class:`Agent` that implements ``decide(context)`` and returns a
:class:`Decision`. In exchange the base class gives it, for free:

* **Timing and health.** Every call is timed and counted, so the dashboard can
  show which agents are slow or failing.
* **Failure containment.** If ``decide`` raises, the agent returns a DEGRADED
  decision instead of taking the whole pipeline down with it. A warehouse that
  stops scanning because the forecast agent hit a divide-by-zero is worse than
  one that scans without a forecast.
* **A fallback path.** An agent may implement ``fallback(context, error)`` to
  answer with a reduced method when its primary one fails. This is what makes
  the backup-scanner requirement work: degrade, never stop.
"""

import threading
import time
import traceback

from core import dbcore

# Decision verdicts. Kept as plain strings so they survive JSON round-trips
# and read clearly in the audit trail.
ACCEPT = "ACCEPT"
REJECT = "REJECT"
FLAG = "FLAG"
INFO = "INFO"
DEGRADED = "DEGRADED"


class Decision:
    """One agent's answer, with its reasoning attached.

    The reasoning is not decoration: it is what makes the multi-agent pipeline
    auditable. Every decision the system takes can be traced back to the agent
    that took it and the evidence it used.
    """

    def __init__(self, agent, verdict=INFO, confidence=1.0, rationale=None,
                 data=None, method="", degraded=False):
        self.agent = agent
        self.verdict = verdict
        self.confidence = round(max(0.0, min(1.0, float(confidence))), 3)
        self.rationale = list(rationale or [])
        self.data = dict(data or {})
        self.method = method
        self.degraded = degraded
        self.elapsed_ms = 0.0
        self.ts = dbcore.now_iso()

    def note(self, text):
        """Add a line of reasoning. Returns self so calls can be chained."""
        if text:
            self.rationale.append(text)
        return self

    def to_dict(self):
        d = {
            "agent": self.agent,
            "verdict": self.verdict,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "method": self.method,
            "degraded": self.degraded,
            "elapsed_ms": round(self.elapsed_ms, 2),
            "ts": self.ts,
        }
        # The agent's own payload is merged in at the top level so existing
        # consumers that read e.g. step["category"] keep working unchanged.
        d.update(self.data)
        return d

    def __repr__(self):
        return "<Decision %s %s conf=%.2f>" % (self.agent, self.verdict, self.confidence)


class AgentError(Exception):
    """Raised inside an agent when it cannot reach a decision at all."""


class Agent:
    """Base class for every agent in the system."""

    #: Display name, and the key used in traces.
    name = "Agent"
    #: One line on what this agent is responsible for.
    role = ""
    #: The technique it uses — shown in the model/agent report.
    method = "rules"
    #: Which pipeline it belongs to, for grouping in the UI.
    layer = "operations"
    #: Whether a failure here should stop the pipeline. Almost always False:
    #: a warehouse should keep receiving stock even if forecasting breaks.
    critical = False

    def __init__(self):
        self._lock = threading.Lock()
        self.calls = 0
        self.failures = 0
        self.degradations = 0
        self.total_ms = 0.0
        self.last_error = ""
        self.last_run_at = None

    # -- to be implemented by subclasses ---------------------------------
    def decide(self, context):
        """Reach a decision about ``context``. Must return a :class:`Decision`."""
        raise NotImplementedError

    def fallback(self, context, error):
        """Optional reduced-capability answer used when ``decide`` fails.

        Return None to accept a plain DEGRADED result.
        """
        return None

    # -- the public entry point ------------------------------------------
    def run(self, context):
        """Invoke the agent with timing, health tracking and containment."""
        started = time.perf_counter()
        try:
            decision = self.decide(context)
            if not isinstance(decision, Decision):
                raise AgentError(
                    "%s returned %s, not a Decision." % (self.name, type(decision).__name__))
            self._record(started, ok=True, degraded=decision.degraded)
            decision.elapsed_ms = (time.perf_counter() - started) * 1000
            return decision
        except Exception as e:                       # noqa: BLE001 - contained on purpose
            traceback.print_exc()
            decision = None
            try:
                decision = self.fallback(context, e)
            except Exception:                        # noqa: BLE001
                decision = None
            if decision is None:
                decision = Decision(
                    self.name, DEGRADED, 0.0,
                    ["%s could not complete: %s." % (self.name, e.__class__.__name__),
                     "The pipeline continued without it."],
                    method="unavailable", degraded=True,
                )
            decision.degraded = True
            decision.elapsed_ms = (time.perf_counter() - started) * 1000
            self._record(started, ok=False, degraded=True, error=repr(e))
            if self.critical:
                raise
            return decision

    def _record(self, started, ok, degraded=False, error=""):
        with self._lock:
            self.calls += 1
            self.total_ms += (time.perf_counter() - started) * 1000
            self.last_run_at = dbcore.now_iso()
            if not ok:
                self.failures += 1
                self.last_error = error
            if degraded:
                self.degradations += 1

    # -- health ----------------------------------------------------------
    def health(self):
        """A snapshot for the agent-status screen."""
        with self._lock:
            calls = self.calls
            avg = (self.total_ms / calls) if calls else 0.0
            reliability = ((calls - self.failures) / calls) if calls else 1.0
            return {
                "name": self.name,
                "role": self.role,
                "method": self.method,
                "layer": self.layer,
                "critical": self.critical,
                "calls": calls,
                "failures": self.failures,
                "degradations": self.degradations,
                "avg_ms": round(avg, 2),
                "reliability": round(reliability, 4),
                "status": self._health_status(calls, reliability),
                "last_error": self.last_error,
                "last_run_at": self.last_run_at,
            }

    # Deliberately specific: a plain _status() would collide with a subclass
    # that has its own notion of "status", which is a very easy mistake to make.
    @staticmethod
    def _health_status(calls, reliability):
        if calls == 0:
            return "idle"
        if reliability >= 0.99:
            return "healthy"
        if reliability >= 0.90:
            return "degraded"
        return "failing"

    def reset_health(self):
        with self._lock:
            self.calls = self.failures = self.degradations = 0
            self.total_ms = 0.0
            self.last_error = ""


class AgentRegistry:
    """The roster of live agents.

    Everything that reaches a decision registers here, which is what lets the
    dashboard list the agents, show their health, and prove that the system
    really is a set of cooperating parts rather than one function with headings.
    """

    def __init__(self):
        self._agents = {}
        self._order = []

    def register(self, agent):
        if agent.name in self._agents:
            return self._agents[agent.name]
        self._agents[agent.name] = agent
        self._order.append(agent.name)
        return agent

    def get(self, name):
        return self._agents.get(name)

    def all(self):
        return [self._agents[n] for n in self._order]

    def health(self):
        return [a.health() for a in self.all()]

    def summary(self):
        rows = self.health()
        calls = sum(r["calls"] for r in rows)
        failures = sum(r["failures"] for r in rows)
        return {
            "agents": len(rows),
            "total_calls": calls,
            "total_failures": failures,
            "reliability": round(((calls - failures) / calls) if calls else 1.0, 4),
            "healthy": sum(1 for r in rows if r["status"] in ("healthy", "idle")),
            "by_layer": _count_by(rows, "layer"),
        }


def _count_by(rows, key):
    out = {}
    for r in rows:
        out[r[key]] = out.get(r[key], 0) + 1
    return out


#: The process-wide registry every agent module registers into on import.
registry = AgentRegistry()


def register(agent_cls):
    """Class decorator: instantiate an agent and add it to the registry."""
    instance = agent_cls()
    registry.register(instance)
    agent_cls.instance = instance
    return agent_cls
