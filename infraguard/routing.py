"""
infraguard/routing.py — Route Analysis Module

Provides route-checking and alternative-route discovery utilities.
These functions operate on the simulation's graph and are also
called from the command parser and dashboard.
"""

from .simulation import InfraGuardSimulation


def check_route(sim: InfraGuardSimulation, source: str, target: str) -> dict:
    """
    Check route availability between two infrastructure nodes.

    Delegates to sim.check_route() and formats the result.
    """
    return sim.check_route(source, target)


def find_alternative_routes(sim: InfraGuardSimulation, source: str, target: str) -> list[list[str]]:
    """
    Find all simple paths between source and target, returning
    only those where every node is operational or restored.
    """
    all_routes = sim.find_all_routes(source, target)
    viable = []
    for route in all_routes:
        if all(sim.graph.nodes[n]["state"] in ("operational", "restored") for n in route):
            viable.append(route)
    return viable


def get_route_summary(sim: InfraGuardSimulation, source: str, target: str) -> str:
    """Return a human-readable route summary."""
    result = check_route(sim, source, target)

    if "error" in result:
        return result["error"]

    lines = [f"Route: {source} → {target}"]

    if result["direct_route_available"]:
        lines.append(f"  Status: AVAILABLE")
        lines.append(f"  Path: {' → '.join(result['path'])}")
    else:
        lines.append(f"  Status: BLOCKED")
        if result["path"]:
            lines.append(f"  Blocked path: {' → '.join(result['path'])}")
        if result["blocked_nodes"]:
            lines.append(f"  Blocked at: {', '.join(result['blocked_nodes'])}")
        if result["alternative_routes"]:
            for i, alt in enumerate(result["alternative_routes"], 1):
                lines.append(f"  Alternative {i}: {' → '.join(alt)}")
        else:
            lines.append(f"  No alternative routes available.")

    return "\n".join(lines)
