"""
infraguard/infrastructure.py — Infrastructure Graph Definition

Defines the directed dependency graph for the InfraGuard simulation.

EDGE SEMANTICS:
  An edge (A → B) with type="power" means "A supplies power to B".
  An edge (A → B) with type="water" means "A supplies water to B".
  An edge (A → B) with type="comm" means "A supplies communications to B".
  An edge (A → B) with type="transport" means "A is connected to B via transport route".
  An edge (A → B) with type="backup_power" means "A can supply backup power to B
     when A is operational AND explicitly activated".

NODE ATTRIBUTES:
  - kind: "power", "backup_power", "medical", "water", "telecom", "transport", "emergency"
  - critical: True if the facility is a critical service (used in severity scoring)
  - state: "operational", "failed", "affected", "restored"

SYNTHETIC ASSUMPTIONS (educational model):
  - The Main Power Station supplies power to Hospital, Water Treatment Plant,
    Telecom Tower, Transport Hub, and Emergency Response Center.
  - The Backup Generator can supply backup power to Hospital and Emergency
    Response Center when explicitly activated.
  - The Water Treatment Plant supplies water to Hospital.
  - The Telecom Tower supplies communications to Emergency Response Center.
  - Transport Hub connects to Emergency Response Center and Alternative
    Transport Route via transport edges.
  - Alternative Transport Route connects to Emergency Response Center.
  - The Backup Generator does NOT automatically activate when power fails.
    It must be explicitly activated as a recovery action.
"""

import networkx as nx
from copy import deepcopy


# ---------------------------------------------------------------------------
# Node definitions
# ---------------------------------------------------------------------------
NODES = {
    "Main Power Station": {
        "kind": "power",
        "critical": True,
        "state": "operational",
    },
    "Backup Generator": {
        "kind": "backup_power",
        "critical": False,
        "state": "operational",
    },
    "Hospital": {
        "kind": "medical",
        "critical": True,
        "state": "operational",
    },
    "Water Treatment Plant": {
        "kind": "water",
        "critical": True,
        "state": "operational",
    },
    "Telecom Tower": {
        "kind": "telecom",
        "critical": True,
        "state": "operational",
    },
    "Transport Hub": {
        "kind": "transport",
        "critical": False,
        "state": "operational",
    },
    "Emergency Response Center": {
        "kind": "emergency",
        "critical": True,
        "state": "operational",
    },
    "Alternative Transport Route": {
        "kind": "transport",
        "critical": False,
        "state": "operational",
    },
}


# ---------------------------------------------------------------------------
# Edge definitions — (source, target, attributes)
# ---------------------------------------------------------------------------
EDGES = [
    # Power supply edges
    ("Main Power Station", "Hospital", {"type": "power", "label": "power supply"}),
    ("Main Power Station", "Water Treatment Plant", {"type": "power", "label": "power supply"}),
    ("Main Power Station", "Telecom Tower", {"type": "power", "label": "power supply"}),
    ("Main Power Station", "Transport Hub", {"type": "power", "label": "power supply"}),
    ("Main Power Station", "Emergency Response Center", {"type": "power", "label": "power supply"}),

    # Backup power edges (only activate explicitly)
    ("Backup Generator", "Hospital", {"type": "backup_power", "label": "backup power"}),
    ("Backup Generator", "Emergency Response Center", {"type": "backup_power", "label": "backup power"}),

    # Water supply
    ("Water Treatment Plant", "Hospital", {"type": "water", "label": "water supply"}),

    # Communications
    ("Telecom Tower", "Emergency Response Center", {"type": "comm", "label": "communications"}),

    # Transport connections (bidirectional logically, but modeled as directed pairs)
    ("Transport Hub", "Emergency Response Center", {"type": "transport", "label": "transport route"}),
    ("Transport Hub", "Alternative Transport Route", {"type": "transport", "label": "transport route"}),
    ("Alternative Transport Route", "Emergency Response Center", {"type": "transport", "label": "alt transport route"}),
]


# Critical service names (used in severity calculation)
CRITICAL_SERVICES = [name for name, attrs in NODES.items() if attrs.get("critical")]


def build_infrastructure_graph() -> nx.DiGraph:
    """
    Construct and return a fresh infrastructure dependency graph.

    Returns a new DiGraph each time so that mutations do not affect
    the template. All nodes start in 'operational' state.
    """
    G = nx.DiGraph()
    for name, attrs in NODES.items():
        G.add_node(name, **deepcopy(attrs))
    for src, tgt, attrs in EDGES:
        G.add_edge(src, tgt, **deepcopy(attrs))
    return G
