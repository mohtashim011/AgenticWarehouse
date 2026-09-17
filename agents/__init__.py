"""
Multi-agent system for the Agentic Warehouse
============================================
Every component that reaches a decision is an agent with a single
responsibility. The orchestrator wires them together and records their
collaboration trace; it never decides on their behalf.

Importing this package registers every agent, which is what populates the roster
the dashboard displays. An agent that is not imported does not exist as far as
the system is concerned, so the imports below are the authoritative list.

Agents by layer
---------------
=============== ===================================================
security        Authentication, Authorisation
perception      Scanner, Vision (camera failover), Recovery, Classifier
operations      Inventory, Anomaly, Audit
planning        Forecast, Procurement
learning        Learning (trains and selects the models)
administration  Staff
assistance      Assistant (the optional LLM layer)
=============== ===================================================
"""

from agents.base import (          # noqa: F401  (re-exported for convenience)
    Agent, Decision, AgentRegistry, registry,
    ACCEPT, REJECT, FLAG, INFO, DEGRADED,
)

# Importing each module runs its @register decorator. Order here is the order
# they appear in the dashboard roster, so it follows the pipeline.
from agents import auth_agent          # noqa: F401,E402
from agents import scanner_agent       # noqa: F401,E402
from agents import vision_agent        # noqa: F401,E402
from agents import recovery_agent      # noqa: F401,E402
from agents import classifier_agent    # noqa: F401,E402
from agents import inventory_agent     # noqa: F401,E402
from agents import anomaly_agent       # noqa: F401,E402
from agents import audit_agent         # noqa: F401,E402
from agents import forecast_agent      # noqa: F401,E402
from agents import procurement_agent   # noqa: F401,E402
from agents import learning_agent      # noqa: F401,E402
from agents import staff_agent         # noqa: F401,E402
from agents import assistant_agent     # noqa: F401,E402


def roster():
    """Every registered agent with its health — powers the Agents screen."""
    return registry.health()


def summary():
    return registry.summary()
