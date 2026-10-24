"""
infraguard/recovery.py — Recovery Action Module

Provides recovery and backup-activation utilities used by
the command parser, agent, and dashboard.
"""

from .simulation import InfraGuardSimulation


def activate_backup(sim: InfraGuardSimulation, backup_name: str) -> dict:
    """Activate a backup component and return results."""
    return sim.activate_backup(backup_name)


def recover_component(sim: InfraGuardSimulation, component_name: str) -> dict:
    """Recover a failed component and return results."""
    return sim.recover_component(component_name)


def get_available_backups(sim: InfraGuardSimulation) -> list[str]:
    """Return names of backup components that can be activated."""
    backups = []
    for name, data in sim.graph.nodes(data=True):
        if (data["kind"] == "backup_power" and
                name not in sim._backup_activated and
                data["state"] in ("operational", "restored")):
            backups.append(name)
    return backups


def get_recovery_summary(sim: InfraGuardSimulation) -> str:
    """Return a human-readable recovery status summary."""
    lines = ["=== Recovery Status ==="]

    failed = sim.get_failed_nodes()
    affected = sim.get_affected_nodes()
    restored = sim.get_restored_nodes()
    backups = get_available_backups(sim)

    if not failed and not affected:
        lines.append("All infrastructure components are operational.")
        return "\n".join(lines)

    if failed:
        lines.append(f"\nFailed components ({len(failed)}):")
        for f in failed:
            lines.append(f"  ✗ {f}")

    if affected:
        lines.append(f"\nAffected components ({len(affected)}):")
        for a in affected:
            lines.append(f"  ⚠ {a}")

    if restored:
        lines.append(f"\nRestored components ({len(restored)}):")
        for r in restored:
            lines.append(f"  ✓ {r}")

    if backups:
        lines.append(f"\nAvailable backups:")
        for b in backups:
            targets = [t for t in sim.graph.successors(b)
                      if sim.graph.edges[b, t]["type"].startswith("backup_")]
            lines.append(f"  ↻ {b} → can supply: {', '.join(targets)}")

    severity = sim.calculate_severity()
    lines.append(f"\nSeverity: {severity['level']} ({severity['score']}%)")
    lines.append(f"  {severity['description']}")

    return "\n".join(lines)
