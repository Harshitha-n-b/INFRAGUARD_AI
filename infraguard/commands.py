"""
infraguard/commands.py — Natural-Language Command Parser

Parses incoming text commands for the InfraGuard agent.
Uses simple keyword matching — no paid LLM required.

Supported command patterns:
  - "what happens if <component> fails?"
  - "fail <component>"
  - "activate backup generator" / "activate <backup>"
  - "check route from <source> to <target>"
  - "which critical services are affected?"
  - "recover <component>"
  - "reset" / "reset simulation"
  - "status" / "show status"
  - "compare" / "resilience twin"
  - "help"
"""

import re
from typing import Optional

from .simulation import InfraGuardSimulation
from .routing import check_route, get_route_summary
from .recovery import (
    activate_backup,
    recover_component,
    get_available_backups,
    get_recovery_summary,
)


# All known component names (lowercase → proper case)
COMPONENT_NAMES = {
    "main power station": "Main Power Station",
    "main power supply": "Main Power Station",
    "power station": "Main Power Station",
    "power grid": "Main Power Station",
    "power plant": "Main Power Station",
    "main power": "Main Power Station",
    "backup generator": "Backup Generator",
    "generator": "Backup Generator",
    "backup power": "Backup Generator",
    "hospital": "Hospital",
    "water treatment plant": "Water Treatment Plant",
    "water plant": "Water Treatment Plant",
    "water treatment": "Water Treatment Plant",
    "telecom tower": "Telecom Tower",
    "telecom": "Telecom Tower",
    "cell tower": "Telecom Tower",
    "transport hub": "Transport Hub",
    "transport": "Transport Hub",
    "emergency response center": "Emergency Response Center",
    "emergency center": "Emergency Response Center",
    "erc": "Emergency Response Center",
    "alternative transport route": "Alternative Transport Route",
    "alternative route": "Alternative Transport Route",
    "alt route": "Alternative Transport Route",
}


def _match_component(text: str) -> Optional[str]:
    """
    Try to find a component name in the given text.
    Returns the proper-case component name or None.
    """
    text_lower = text.lower()
    # Try longest match first
    for key in sorted(COMPONENT_NAMES.keys(), key=len, reverse=True):
        if key in text_lower:
            return COMPONENT_NAMES[key]
    return None


def _match_two_components(text: str) -> tuple[Optional[str], Optional[str]]:
    """
    Try to find two component names in text (for route checking).
    Uses 'from X to Y' pattern first, then falls back to finding any two.
    """
    text_lower = text.lower()

    # Try "from X to Y" pattern
    route_match = re.search(r"from\s+(.+?)\s+to\s+(.+?)(?:\?|$|\.|!)", text_lower)
    if route_match:
        src = _match_component(route_match.group(1))
        tgt = _match_component(route_match.group(2))
        if src and tgt:
            return src, tgt

    # Fallback: find all component mentions in order
    found = []
    for key in sorted(COMPONENT_NAMES.keys(), key=len, reverse=True):
        idx = text_lower.find(key)
        if idx >= 0:
            found.append((idx, COMPONENT_NAMES[key]))
            # Remove the found key to avoid overlapping matches
            text_lower = text_lower[:idx] + ("_" * len(key)) + text_lower[idx + len(key):]

    found.sort(key=lambda x: x[0])
    if len(found) >= 2:
        return found[0][1], found[1][1]

    return None, None


def parse_and_execute(sim: InfraGuardSimulation, text: str) -> str:
    """
    Parse a natural-language command and execute it against the simulation.

    Returns a human-readable response string.
    """
    # Strip any leading @mentions (e.g. "@infraguard", "@infraguard_ai", "@agent1...")
    text_clean = re.sub(r"^@\S+\s*", "", text.strip()).strip('\'"` ')
    if not text_clean:
        return "Please enter a command. Type 'help' for available commands."

    text_lower = text_clean.lower()

    # --- Greetings ---
    if text_lower in ("hi", "hello", "hey", "greetings", "start"):
        return (
            "👋 Hello! I am InfraGuard AI — your infrastructure resilience agent.\n\n"
            "Try these commands:\n"
            "• 'What happens if the Main Power Station fails?'\n"
            "• 'Activate Backup Generator'\n"
            "• 'Check route from Transport Hub to Emergency Response Center'\n"
            "• 'Status' or 'Reset'"
        )

    # --- Help ---
    if "help" in text_lower or text_lower in ("commands", "?", "what can you do"):
        return _help_text()

    # --- Reset ---
    if "reset" in text_lower or text_lower == "clear":
        result = sim.reset()
        return f"✓ {result['message']}\nSeverity: {result['severity']['level']} (0%)"

    # --- Connected nodes / dependencies ---
    if any(k in text_lower for k in ("connected", "supplies", "depends", "dependency", "links", "incoming", "outgoing")):
        comp = _match_component(text_clean)
        if comp:
            successors = list(sim.graph.successors(comp))
            predecessors = list(sim.graph.predecessors(comp))
            lines = [f"Connections for {comp}:"]
            if successors:
                lines.append(f"\nSupplies / Connects downstream to ({len(successors)}):")
                for s in successors:
                    edge = sim.graph.edges[comp, s]
                    lines.append(f"  → {s} ({edge.get('label', edge.get('type', 'dependency'))})")
            if predecessors:
                lines.append(f"\nReceives supply from ({len(predecessors)}):")
                for p in predecessors:
                    edge = sim.graph.edges[p, comp]
                    lines.append(f"  ← {p} ({edge.get('label', edge.get('type', 'dependency'))})")
            return "\n".join(lines)

    # --- Status ---
    if text_lower in ("status", "show status", "current status", "state"):
        return _format_status(sim)

    # --- Critical services ---
    if "critical" in text_lower and ("service" in text_lower or "affected" in text_lower):
        affected = sim.get_affected_critical_services()
        if not affected:
            return "All critical services are currently operational."
        return (
            f"Affected critical services ({len(affected)}/{len(sim.get_critical_services())}):\n"
            + "\n".join(f"  ⚠ {s}" for s in affected)
        )

    # --- Route check ---
    if "route" in text_lower or "path" in text_lower:
        src, tgt = _match_two_components(text_clean)
        if src and tgt:
            return get_route_summary(sim, src, tgt)
        return ("Please specify source and target, e.g.:\n"
                "  'Check route from Transport Hub to Emergency Response Center'")

    # --- Activate backup ---
    if "activate" in text_lower:
        comp = _match_component(text_clean)
        if comp:
            result = activate_backup(sim, comp)
            if "error" in result:
                node_state = sim.graph.nodes.get(comp, {}).get("state", "unknown")
                if node_state in ("failed", "affected"):
                    return (
                        f"✗ '{comp}' is currently {node_state.upper()} from an earlier failure simulation.\n"
                        f"👉 To use it, run: 'Recover {comp}' or 'Reset' first to restore the grid to operational state."
                    )
                return f"✗ {result['error']}\n💡 Tip: Say 'Status' to check grid state or 'Reset' to restore all systems."
            restored = result.get("restored_services", [])
            sev = result["severity"]
            resp = f"✓ {comp} activated."
            if restored:
                resp += f"\nRestored services: {', '.join(restored)}"
            resp += f"\nSeverity: {sev['level']} ({sev['score']}%)"
            return resp
        return "Please specify which backup to activate, e.g.: 'Activate Backup Generator'"

    # --- Recover ---
    if "recover" in text_lower or "repair" in text_lower or "restore" in text_lower:
        comp = _match_component(text_clean)
        if comp:
            result = recover_component(sim, comp)
            if "error" in result:
                return f"✗ {result['error']}"
            restored = result.get("restored_services", [])
            sev = result["severity"]
            resp = f"✓ {comp} recovered."
            if restored:
                resp += f"\nDownstream services restored: {', '.join(restored)}"
            resp += f"\nSeverity: {sev['level']} ({sev['score']}%)"
            return resp
        return "Please specify which component to recover, e.g.: 'Recover Main Power Station'"

    # --- Fail / What happens if ---
    if ("fail" in text_lower or "what happens" in text_lower or
            "simulate" in text_lower or "knock out" in text_lower):
        comp = _match_component(text_clean)
        if comp:
            result = sim.fail_component(comp)
            if "error" in result:
                return f"✗ {result['error']}"
            return _format_failure_report(result)
        return ("Please specify a component, e.g.:\n"
                "  'What happens if the Main Power Station fails?'\n"
                "  'Fail Hospital'")

    # --- Compare / Resilience Twin ---
    if "compare" in text_lower or "resilience twin" in text_lower or "twin" in text_lower:
        return _format_comparison_help(sim)

    # --- Recommendations ---
    if "recommend" in text_lower or "suggestion" in text_lower:
        recs = sim._generate_recommendations()
        if not recs:
            return "No recommendations — all systems are operational."
        return "Recovery Recommendations:\n" + "\n".join(f"  {i}. {r}" for i, r in enumerate(recs, 1))

    # --- Fallback ---
    return (
        f"I didn't understand that command. Type 'help' to see supported commands.\n"
        f"You said: \"{text_clean}\""
    )


def _help_text() -> str:
    return """InfraGuard AI — Available Commands:

• "What happens if [component] fails?"
  Simulate a failure and see the impact.

• "Activate Backup Generator"
  Activate a backup to restore affected services.

• "Check route from [source] to [target]"
  Check if a transport/connectivity route is available.

• "Which critical services are affected?"
  List critical services that are down.

• "Recover [component]"
  Recover/repair a failed component.

• "Status"
  Show current system status.

• "Recommendations"
  Get recovery recommendations.

• "Reset"
  Reset the simulation to its initial state.

• "Help"
  Show this help message.

Components: Main Power Station, Backup Generator, Hospital,
Water Treatment Plant, Telecom Tower, Transport Hub,
Emergency Response Center, Alternative Transport Route"""


def _format_status(sim: InfraGuardSimulation) -> str:
    """Format the current system status."""
    states = sim.get_all_states()
    severity = sim.calculate_severity()

    lines = ["=== InfraGuard System Status ===", ""]

    state_icons = {
        "operational": "🟢",
        "failed": "🔴",
        "affected": "🟡",
        "restored": "🔵",
    }

    for name, state in sorted(states.items()):
        icon = state_icons.get(state, "⚪")
        critical = " [CRITICAL]" if sim.graph.nodes[name].get("critical") else ""
        lines.append(f"  {icon} {name}: {state.upper()}{critical}")

    lines.append("")
    lines.append(f"Severity: {severity['level']} ({severity['score']}%)")
    lines.append(f"  {severity['description']}")

    backups = get_available_backups(sim)
    if backups:
        lines.append(f"\nAvailable backups: {', '.join(backups)}")

    return "\n".join(lines)


def _format_failure_report(result: dict) -> str:
    """Format a failure report."""
    lines = [f"⚡ FAILURE REPORT: {result['component']}", ""]

    if result["directly_affected"]:
        lines.append(f"Directly affected ({len(result['directly_affected'])}):")
        for a in result["directly_affected"]:
            lines.append(f"  ⚠ {a}")
    else:
        lines.append("No downstream services directly affected.")

    lines.append("")
    sev = result["severity"]
    lines.append(f"Severity: {sev['level']} ({sev['score']}%)")
    lines.append(f"  {sev['description']}")

    if result["recommendations"]:
        lines.append("\nRecommendations:")
        for i, rec in enumerate(result["recommendations"], 1):
            lines.append(f"  {i}. {rec}")

    return "\n".join(lines)


def _format_comparison_help(sim: InfraGuardSimulation) -> str:
    """Show help for the Resilience Twin feature."""
    lines = [
        "=== Resilience Twin — Scenario Comparison ===",
        "",
        "To compare baseline vs. recovery scenarios:",
        "  1. Fail a component: 'Fail Main Power Station'",
        "  2. Note the baseline impact",
        "  3. Activate a backup: 'Activate Backup Generator'",
        "  4. Compare the before/after states",
        "",
        "Current state:",
    ]

    failed = sim.get_failed_nodes()
    affected = sim.get_affected_nodes()
    if not failed and not affected:
        lines.append("  All systems operational — fail a component first.")
    else:
        if failed:
            lines.append(f"  Failed: {', '.join(failed)}")
        if affected:
            lines.append(f"  Affected: {', '.join(affected)}")
        lines.append("")
        lines.append("  Available recovery actions:")
        backups = get_available_backups(sim)
        if backups:
            for b in backups:
                lines.append(f"    • Activate {b}")
        for f in failed:
            lines.append(f"    • Recover {f}")

    return "\n".join(lines)
