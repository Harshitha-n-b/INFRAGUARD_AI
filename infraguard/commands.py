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


import difflib

# Primary canonical component map with extensive aliases and keywords
COMPONENT_MAP = {
    "Main Power Station": [
        "main power station", "main power supply", "power station", "power supply",
        "power grid", "power plant", "main power", "power", "electricity", "electric grid"
    ],
    "Backup Generator": [
        "backup generator", "generator", "backup power", "standby generator",
        "auxiliary generator", "emergency generator", "backup"
    ],
    "Hospital": [
        "hospital", "medical center", "clinic", "healthcare", "emergency hospital", "medical"
    ],
    "Water Treatment Plant": [
        "water treatment plant", "water treatement plant", "water plant", "water treatment",
        "water supply", "water filtration", "water facility", "water"
    ],
    "Telecom Tower": [
        "telecom tower", "telecom", "cell tower", "cellular tower", "telecommunications",
        "antenna", "radio tower", "comm tower", "communications"
    ],
    "Transport Hub": [
        "transport hub", "transportation hub", "transport", "transit station",
        "train station", "transit hub", "logistics hub", "transit"
    ],
    "Emergency Response Center": [
        "emergency response center", "emergency center", "erc", "response center",
        "disaster management", "emergency response", "emergency dispatch"
    ],
    "Alternative Transport Route": [
        "alternative transport route", "alternative route", "alt route", "bypass",
        "secondary route", "alternate route", "detour", "alternative transport"
    ],
}


def _match_component(text: str) -> Optional[str]:
    """
    Find the best-matching infrastructure component in text using exact and fuzzy matching.
    """
    text_lower = text.lower()

    # 1. Exact alias match (longest alias first)
    all_aliases = []
    for comp, aliases in COMPONENT_MAP.items():
        for a in aliases:
            all_aliases.append((a, comp))
    all_aliases.sort(key=lambda x: len(x[0]), reverse=True)

    for alias, comp in all_aliases:
        # Check whole words or substrings
        if alias in text_lower:
            return comp

    # 2. Fuzzy match word n-grams (handles typos like 'treatement')
    words = re.findall(r"\b[a-z]+\b", text_lower)
    for n in (4, 3, 2, 1):
        for i in range(len(words) - n + 1):
            ngram = " ".join(words[i:i + n])
            # Exclude very short stopwords
            if len(ngram) < 4:
                continue
            matches = difflib.get_close_matches(
                ngram, [a for a, _ in all_aliases], n=1, cutoff=0.75
            )
            if matches:
                matched_alias = matches[0]
                for a, comp in all_aliases:
                    if a == matched_alias:
                        return comp

    return None


def _match_two_components(text: str) -> tuple[Optional[str], Optional[str]]:
    """
    Try to find two component names in text (for route checking).
    Uses 'from X to Y' pattern first, then falls back to finding any two distinct components.
    """
    text_lower = text.lower()

    # Try "from X to Y" pattern
    route_match = re.search(r"(?:from|between)\s+(.+?)\s+(?:to|and)\s+(.+?)(?:\?|$|\.|!)", text_lower)
    if route_match:
        src = _match_component(route_match.group(1))
        tgt = _match_component(route_match.group(2))
        if src and tgt and src != tgt:
            return src, tgt

    # Fallback: scan for any two mentioned components
    found = []
    for comp in COMPONENT_MAP.keys():
        if _match_component_in_text(comp, text_lower):
            found.append(comp)

    if len(found) >= 2:
        return found[0], found[1]

    return None, None


def _match_component_in_text(comp: str, text_lower: str) -> bool:
    for a in COMPONENT_MAP.get(comp, []):
        if a in text_lower:
            return True
    return False


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

    # --- Reset / Restart ---
    if any(k in text_lower for k in ("reset", "restart", "clear", "reboot", "start over")):
        result = sim.reset()
        return f"✓ {result['message']}\nSeverity: {result['severity']['level']} (0%)"

    # --- Fail / What happens if (Failure Simulation) ---
    failure_keywords = (
        "fail", "fails", "failure", "what happens", "what if", "affected if",
        "stops working", "stop working", "stopped working", "breaks down",
        "shut down", "shutdown", "goes down", "went down", "is down",
        "outage", "blackout", "knock out", "knocked out", "offline", "simulate",
        "disrupt", "impact of"
    )
    if any(k in text_lower for k in failure_keywords):
        comp = _match_component(text_clean)
        if comp:
            result = sim.fail_component(comp)
            if "error" in result:
                # If already failed, provide the current impact report instead of a cold error
                if "already failed" in result["error"].lower():
                    affected = [n for n in sim.graph.nodes if sim.graph.nodes[n]["state"] in ("failed", "affected") and n != comp]
                    sev = sim.calculate_severity()
                    recs = sim._generate_recommendations()
                    lines = [
                        f"⚠ '{comp}' is already offline / in a failed state.\n",
                        f"⚡ CURRENT IMPACT REPORT: {comp}",
                    ]
                    if affected:
                        lines.append(f"\nDirectly & indirectly affected ({len(affected)}):")
                        for a in affected:
                            lines.append(f"  ⚠ {a}")
                    lines.append(f"\nSeverity: {sev['level']} ({sev['score']}%)")
                    lines.append(f"  {sev['description']}")
                    if recs:
                        lines.append("\nRecommendations:")
                        for i, r in enumerate(recs, 1):
                            lines.append(f"  {i}. {r}")
                    lines.append(f"\n💡 Tip: Say 'Recover {comp}' to repair it, or 'Reset' to clear all failures.")
                    return "\n".join(lines)
                return f"✗ {result['error']}"
            return _format_failure_report(result)
        return ("Please specify a component, e.g.:\n"
                "  'What happens if the Main Power Station fails?'\n"
                "  'What if the Water Treatment Plant stops working?'")

    # --- Connected nodes / dependencies ---
    if any(k in text_lower for k in ("connected to", "connected", "supplies to", "supplies", "depends on", "dependency", "links", "incoming", "outgoing", "who uses", "feeds")):
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
    if any(k in text_lower for k in ("status", "show status", "current status", "state", "health", "overview")):
        return _format_status(sim)

    # --- Critical services ---
    if "critical" in text_lower and ("service" in text_lower or "affected" in text_lower or "down" in text_lower):
        affected = sim.get_affected_critical_services()
        if not affected:
            return "All critical services are currently operational."
        return (
            f"Affected critical services ({len(affected)}/{len(sim.get_critical_services())}):\n"
            + "\n".join(f"  ⚠ {s}" for s in affected)
        )

    # --- Route check ---
    if any(k in text_lower for k in ("route", "path", "reach", "navigate", "access")):
        src, tgt = _match_two_components(text_clean)
        if src and tgt:
            return get_route_summary(sim, src, tgt)
        return ("Please specify source and target, e.g.:\n"
                "  'Check route from Transport Hub to Emergency Response Center'")

    # --- Activate backup ---
    if any(k in text_lower for k in ("activate", "turn on", "switch on", "engage", "start backup", "run generator")):
        comp = _match_component(text_clean) or "Backup Generator"
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

    # --- Recover ---
    if any(k in text_lower for k in ("recover", "repair", "restore", "fix", "restart component", "bring back")):
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

    # --- Compare / Resilience Twin ---
    if any(k in text_lower for k in ("compare", "resilience twin", "twin")):
        return _format_comparison_help(sim)

    # --- Recommendations ---
    if any(k in text_lower for k in ("recommend", "suggestion", "what should i do", "how to fix", "how to recover")):
        recs = sim._generate_recommendations()
        if not recs:
            return "No recommendations — all systems are operational."
        return "Recovery Recommendations:\n" + "\n".join(f"  {i}. {r}" for i, r in enumerate(recs, 1))

    # --- Fallback: Single component inquiry ---
    comp = _match_component(text_clean)
    if comp:
        state = sim.graph.nodes[comp]["state"]
        return (
            f"Component '{comp}' is currently {state.upper()}.\n\n"
            f"You can ask:\n"
            f"• 'What happens if {comp} fails?'\n"
            f"• 'What nodes are connected to {comp}?'\n"
            f"• 'Recover {comp}' (if failed)\n"
            f"• 'Status'"
        )

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
