"""
infraguard/simulation.py — Core Simulation Engine

Provides the InfraGuardSimulation class that manages infrastructure state,
failure propagation, backup activation, recovery, severity scoring,
and the Resilience Twin scenario comparison.

SEVERITY FORMULA (deterministic, educational):
  severity_score = (affected_critical_count / total_critical_count) * 100
  Categories:
    0        → "NORMAL"
    1–39     → "LOW"
    40–59    → "MODERATE"
    60–79    → "HIGH"
    80–100   → "CRITICAL"

MULTIPLE SIMULTANEOUS FAILURES:
  Each fail_component() call propagates impact from the current state.
  A second failure propagates only its *additional* downstream effects;
  already-failed nodes stay failed. No double-counting occurs.

BACKUP ACTIVATION:
  activate_backup(component) changes the backup node's state to 'operational'
  (it already is by default) and then re-evaluates each node that has a
  backup_power edge from that component. If that backup edge is the only
  missing supply type AND the backup is operational, the downstream node
  is marked 'restored'. This is an explicit action, not automatic.

RECOVERY:
  recover_component(name) marks the node as 'operational' and then
  re-propagates to see which downstream nodes can be restored.

RESET:
  Rebuilds the entire graph from the template.
"""

from copy import deepcopy
from typing import Optional

import networkx as nx

from .infrastructure import build_infrastructure_graph, CRITICAL_SERVICES


class InfraGuardSimulation:
    """Stateful infrastructure resilience simulation."""

    def __init__(self):
        self.graph: nx.DiGraph = build_infrastructure_graph()
        self.event_log: list[str] = []
        self._failed_components: set[str] = set()
        self._backup_activated: set[str] = set()

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------

    def get_all_states(self) -> dict[str, str]:
        """Return {node_name: state} for every node."""
        return {n: self.graph.nodes[n]["state"] for n in self.graph.nodes}

    def get_node_info(self, name: str) -> Optional[dict]:
        """Return full attribute dict for a node, or None if not found."""
        if name in self.graph.nodes:
            return dict(self.graph.nodes[name])
        return None

    def get_operational_nodes(self) -> list[str]:
        return [n for n, d in self.graph.nodes(data=True)
                if d["state"] in ("operational", "restored")]

    def get_failed_nodes(self) -> list[str]:
        return [n for n, d in self.graph.nodes(data=True)
                if d["state"] == "failed"]

    def get_affected_nodes(self) -> list[str]:
        return [n for n, d in self.graph.nodes(data=True)
                if d["state"] == "affected"]

    def get_restored_nodes(self) -> list[str]:
        return [n for n, d in self.graph.nodes(data=True)
                if d["state"] == "restored"]

    def get_critical_services(self) -> list[str]:
        """Return the list of critical service names."""
        return list(CRITICAL_SERVICES)

    def get_affected_critical_services(self) -> list[str]:
        """Return critical services that are failed or affected."""
        return [n for n in CRITICAL_SERVICES
                if self.graph.nodes[n]["state"] in ("failed", "affected")]

    def node_exists(self, name: str) -> bool:
        return name in self.graph.nodes

    # ------------------------------------------------------------------
    # Severity
    # ------------------------------------------------------------------

    def calculate_severity(self) -> dict:
        """
        Calculate incident severity based on affected critical services.

        Returns:
            dict with keys: score (int 0-100), level (str), affected_critical (list),
            total_critical (int), description (str)
        """
        affected = self.get_affected_critical_services()
        total = len(CRITICAL_SERVICES)
        if total == 0:
            score = 0
        else:
            score = int((len(affected) / total) * 100)

        if score == 0:
            level = "NORMAL"
            desc = "All critical services operational."
        elif score < 40:
            level = "LOW"
            desc = f"{len(affected)} of {total} critical services impacted."
        elif score < 60:
            level = "MODERATE"
            desc = f"{len(affected)} of {total} critical services impacted. Situation requires attention."
        elif score < 80:
            level = "HIGH"
            desc = f"{len(affected)} of {total} critical services impacted. Significant disruption."
        else:
            level = "CRITICAL"
            desc = f"{len(affected)} of {total} critical services impacted. Widespread infrastructure failure."

        return {
            "score": score,
            "level": level,
            "affected_critical": affected,
            "total_critical": total,
            "description": desc,
        }

    # ------------------------------------------------------------------
    # Failure propagation
    # ------------------------------------------------------------------

    def fail_component(self, name: str) -> dict:
        """
        Simulate failure of a component and propagate downstream impact.

        Returns:
            dict with keys: component, directly_affected, all_affected,
            severity, recommendations
        """
        if not self.node_exists(name):
            return {"error": f"Component '{name}' not found in the infrastructure model."}

        if self.graph.nodes[name]["state"] == "failed":
            return {"error": f"Component '{name}' has already failed."}

        # Mark the component as failed
        self.graph.nodes[name]["state"] = "failed"
        self._failed_components.add(name)
        self._log(f"FAILURE: {name} has failed.")

        # Propagate downstream impact
        directly_affected = self._propagate_failure(name)
        all_affected = self.get_affected_nodes() + self.get_failed_nodes()
        severity = self.calculate_severity()
        recommendations = self._generate_recommendations()

        return {
            "component": name,
            "directly_affected": directly_affected,
            "all_affected": all_affected,
            "severity": severity,
            "recommendations": recommendations,
        }

    def _propagate_failure(self, failed_node: str) -> list[str]:
        """
        Propagate failure from a node to its dependents.

        Uses BFS to avoid infinite loops. A downstream node becomes
        'affected' if ALL of its supply edges of a required type are
        from failed/affected sources.

        A node with a backup_power edge from an activated backup remains
        unaffected even if its primary power source fails.

        Returns list of directly affected node names.
        """
        directly_affected = []
        visited = set()
        queue = [failed_node]

        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)

            # Check all successors (nodes that depend on `current`)
            for successor in self.graph.successors(current):
                if successor in visited:
                    continue
                if self.graph.nodes[successor]["state"] in ("failed",):
                    continue

                # Determine if this successor has lost essential supply
                if self._has_lost_essential_supply(successor):
                    if self.graph.nodes[successor]["state"] != "affected":
                        self.graph.nodes[successor]["state"] = "affected"
                        directly_affected.append(successor)
                        self._log(f"AFFECTED: {successor} — lost essential supply.")
                    queue.append(successor)

        return directly_affected

    def _has_lost_essential_supply(self, node: str) -> bool:
        """
        Check if a node has lost essential supply from its predecessors.

        A node is considered to have lost supply if ANY supply-type
        predecessor (power, water, comm) is failed/affected AND there
        is no activated backup covering that supply type.

        Transport edges do not constitute essential supply dependencies.
        """
        supply_types = ("power", "water", "comm")

        for supply_type in supply_types:
            # Find all incoming edges of this supply type
            suppliers = []
            for pred in self.graph.predecessors(node):
                edge_data = self.graph.edges[pred, node]
                if edge_data["type"] == supply_type:
                    suppliers.append(pred)

            if not suppliers:
                continue  # This node doesn't need this supply type

            # Check if all suppliers of this type are down
            all_down = all(
                self.graph.nodes[s]["state"] in ("failed", "affected")
                for s in suppliers
            )

            if all_down:
                # Check for activated backup covering this supply type
                has_backup = False
                for pred in self.graph.predecessors(node):
                    edge_data = self.graph.edges[pred, node]
                    if (edge_data["type"] == f"backup_{supply_type}" and
                            pred in self._backup_activated and
                            self.graph.nodes[pred]["state"] in ("operational", "restored")):
                        has_backup = True
                        break

                if not has_backup:
                    return True

        return False

    # ------------------------------------------------------------------
    # Backup activation
    # ------------------------------------------------------------------

    def activate_backup(self, backup_name: str) -> dict:
        """
        Explicitly activate a backup component.

        This marks the backup as activated and re-evaluates downstream
        nodes that have backup edges from this component.

        Returns dict with activation results.
        """
        if not self.node_exists(backup_name):
            return {"error": f"Component '{backup_name}' not found."}

        node_info = self.graph.nodes[backup_name]
        if node_info["kind"] != "backup_power":
            return {"error": f"'{backup_name}' is not a backup component."}

        if node_info["state"] in ("failed", "affected"):
            return {"error": f"'{backup_name}' is not operational and cannot be activated."}

        if backup_name in self._backup_activated:
            return {"error": f"'{backup_name}' is already activated."}

        self._backup_activated.add(backup_name)
        self._log(f"BACKUP ACTIVATED: {backup_name}")

        # Re-evaluate downstream nodes
        restored = self._re_evaluate_after_backup(backup_name)

        return {
            "backup": backup_name,
            "restored_services": restored,
            "severity": self.calculate_severity(),
        }

    def _re_evaluate_after_backup(self, backup_name: str) -> list[str]:
        """Re-evaluate nodes after a backup is activated."""
        restored = []
        # Check all successors of the backup
        for successor in self.graph.successors(backup_name):
            edge_data = self.graph.edges[backup_name, successor]
            if edge_data["type"].startswith("backup_"):
                if self.graph.nodes[successor]["state"] == "affected":
                    if not self._has_lost_essential_supply(successor):
                        self.graph.nodes[successor]["state"] = "restored"
                        restored.append(successor)
                        self._log(f"RESTORED: {successor} — via {backup_name}.")

                        # Cascade restoration to dependents
                        restored.extend(self._cascade_restoration(successor))

        return restored

    def _cascade_restoration(self, restored_node: str) -> list[str]:
        """
        After a node is restored, check if its dependents can also be restored.
        """
        cascade_restored = []
        for successor in self.graph.successors(restored_node):
            if self.graph.nodes[successor]["state"] == "affected":
                if not self._has_lost_essential_supply(successor):
                    self.graph.nodes[successor]["state"] = "restored"
                    cascade_restored.append(successor)
                    self._log(f"RESTORED (cascade): {successor} — supply restored.")
                    cascade_restored.extend(self._cascade_restoration(successor))
        return cascade_restored

    # ------------------------------------------------------------------
    # Recovery
    # ------------------------------------------------------------------

    def recover_component(self, name: str) -> dict:
        """
        Recover (repair) a failed component and re-evaluate downstream.

        Returns dict with recovery results.
        """
        if not self.node_exists(name):
            return {"error": f"Component '{name}' not found."}

        state = self.graph.nodes[name]["state"]
        if state == "operational":
            return {"error": f"'{name}' is already operational."}

        self.graph.nodes[name]["state"] = "operational"
        self._failed_components.discard(name)
        self._log(f"RECOVERED: {name} has been restored to operational.")

        # Re-evaluate all downstream nodes in topological order
        restored = []
        desc = nx.descendants(self.graph, name)
        topo_order = [n for n in nx.topological_sort(self.graph) if n in desc]
        for successor in topo_order:
            if self.graph.nodes[successor]["state"] == "affected":
                if not self._has_lost_essential_supply(successor):
                    self.graph.nodes[successor]["state"] = "restored"
                    restored.append(successor)
                    self._log(f"RESTORED: {successor} — supply from {name} recovered.")

        return {
            "component": name,
            "restored_services": restored,
            "severity": self.calculate_severity(),
        }

    # ------------------------------------------------------------------
    # Recommendations
    # ------------------------------------------------------------------

    def _generate_recommendations(self) -> list[str]:
        """Generate recovery recommendations based on current graph state."""
        recs = []
        affected = self.get_affected_nodes()
        failed = self.get_failed_nodes()

        # Recommend recovering failed components
        for comp in failed:
            recs.append(f"Recover '{comp}' to restore its downstream services.")

        # Recommend backup activation if available and not yet activated
        for comp in affected:
            for pred in self.graph.predecessors(comp):
                edge_data = self.graph.edges[pred, comp]
                if (edge_data["type"].startswith("backup_") and
                        pred not in self._backup_activated and
                        self.graph.nodes[pred]["state"] in ("operational", "restored")):
                    rec = f"Activate '{pred}' to provide backup supply to '{comp}'."
                    if rec not in recs:
                        recs.append(rec)

        # Recommend alternative routes if transport is affected
        for comp in affected + failed:
            if self.graph.nodes[comp].get("kind") == "transport":
                alt_routes = self._find_alternative_routes_for(comp)
                for route in alt_routes:
                    rec = f"Use alternative route: {' → '.join(route)}."
                    if rec not in recs:
                        recs.append(rec)

        return recs

    def _find_alternative_routes_for(self, blocked: str) -> list[list[str]]:
        """Find alternative transport routes bypassing a blocked node."""
        routes = []
        transport_nodes = [n for n in self.graph.nodes
                          if self.graph.nodes[n].get("kind") == "transport"
                          and n != blocked
                          and self.graph.nodes[n]["state"] in ("operational", "restored")]

        for t_node in transport_nodes:
            # Check if this node can reach Emergency Response Center
            try:
                temp_graph = self.graph.copy()
                if blocked in temp_graph:
                    temp_graph.remove_node(blocked)
                if nx.has_path(temp_graph, t_node, "Emergency Response Center"):
                    path = nx.shortest_path(temp_graph, t_node, "Emergency Response Center")
                    routes.append(path)
            except (nx.NetworkXError, nx.NodeNotFound):
                continue
        return routes

    # ------------------------------------------------------------------
    # Route checking
    # ------------------------------------------------------------------

    def check_route(self, source: str, target: str) -> dict:
        """
        Check if a transport/connectivity route exists between two nodes.

        Returns dict with route availability, path, and alternative routes.
        """
        if not self.node_exists(source):
            return {"error": f"Component '{source}' not found."}
        if not self.node_exists(target):
            return {"error": f"Component '{target}' not found."}

        result = {
            "source": source,
            "target": target,
            "direct_route_available": False,
            "path": [],
            "blocked_nodes": [],
            "alternative_routes": [],
        }

        # Check direct path
        try:
            if nx.has_path(self.graph, source, target):
                path = nx.shortest_path(self.graph, source, target)
                # Check if any node on the path is failed/affected
                blocked = [n for n in path
                          if self.graph.nodes[n]["state"] in ("failed", "affected")]
                if blocked:
                    result["blocked_nodes"] = blocked
                    result["direct_route_available"] = False
                    result["path"] = path
                else:
                    result["direct_route_available"] = True
                    result["path"] = path
            else:
                result["direct_route_available"] = False
        except nx.NetworkXError:
            result["direct_route_available"] = False

        # Find alternative routes avoiding blocked nodes
        if not result["direct_route_available"]:
            blocked_set = set(result["blocked_nodes"])
            temp_graph = self.graph.copy()
            for b in blocked_set:
                if b in temp_graph and b not in (source, target):
                    temp_graph.remove_node(b)
            try:
                if nx.has_path(temp_graph, source, target):
                    alt_path = nx.shortest_path(temp_graph, source, target)
                    # Verify all nodes on the alternative path are operational
                    alt_blocked = [n for n in alt_path
                                  if self.graph.nodes[n]["state"] in ("failed", "affected")]
                    if not alt_blocked:
                        result["alternative_routes"].append(alt_path)
            except (nx.NetworkXError, nx.NodeNotFound):
                pass

        return result

    def find_all_routes(self, source: str, target: str) -> list[list[str]]:
        """Find all simple paths between source and target."""
        if not self.node_exists(source) or not self.node_exists(target):
            return []
        try:
            return list(nx.all_simple_paths(self.graph, source, target))
        except nx.NetworkXError:
            return []

    # ------------------------------------------------------------------
    # Resilience Twin (scenario comparison)
    # ------------------------------------------------------------------

    def create_snapshot(self) -> dict:
        """Create a snapshot of the current simulation state."""
        return {
            "states": self.get_all_states(),
            "severity": self.calculate_severity(),
            "operational": self.get_operational_nodes(),
            "failed": self.get_failed_nodes(),
            "affected": self.get_affected_nodes(),
            "restored": self.get_restored_nodes(),
            "affected_critical": self.get_affected_critical_services(),
            "backup_activated": list(self._backup_activated),
        }

    def compare_scenarios(self, baseline: dict, recovery: dict) -> dict:
        """
        Compare a baseline failure scenario with a recovery scenario.

        Both arguments should be snapshots from create_snapshot().

        Returns comparison dict.
        """
        baseline_down = set(baseline["failed"] + baseline["affected"])
        recovery_down = set(recovery["failed"] + recovery["affected"])

        still_affected = baseline_down & recovery_down
        recovered_services = baseline_down - recovery_down
        newly_operational = set(recovery["operational"] + recovery["restored"]) - set(baseline["operational"])

        return {
            "baseline_severity": baseline["severity"],
            "recovery_severity": recovery["severity"],
            "baseline_down_count": len(baseline_down),
            "recovery_down_count": len(recovery_down),
            "services_recovered": sorted(recovered_services),
            "still_affected": sorted(still_affected),
            "newly_operational": sorted(newly_operational),
            "improvement_score": baseline["severity"]["score"] - recovery["severity"]["score"],
            "baseline_affected_critical": baseline["affected_critical"],
            "recovery_affected_critical": recovery["affected_critical"],
        }

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def reset(self) -> dict:
        """Reset the simulation to its initial state."""
        self.graph = build_infrastructure_graph()
        self._failed_components.clear()
        self._backup_activated.clear()
        self._log("RESET: Simulation reset to initial state.")
        return {
            "status": "reset",
            "severity": self.calculate_severity(),
            "message": "Simulation has been reset. All components are operational.",
        }

    # ------------------------------------------------------------------
    # Event log
    # ------------------------------------------------------------------

    def _log(self, message: str):
        """Append a timestamped message to the event log."""
        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        self.event_log.append(f"[{ts}] {message}")

    def get_event_log(self) -> list[str]:
        """Return the full event log."""
        return list(self.event_log)

    # ------------------------------------------------------------------
    # Graph metadata for visualization
    # ------------------------------------------------------------------

    def get_graph_data(self) -> dict:
        """Return node and edge data suitable for visualization."""
        nodes = []
        for name, data in self.graph.nodes(data=True):
            nodes.append({
                "name": name,
                "kind": data["kind"],
                "critical": data.get("critical", False),
                "state": data["state"],
            })

        edges = []
        for src, tgt, data in self.graph.edges(data=True):
            edges.append({
                "source": src,
                "target": tgt,
                "type": data["type"],
                "label": data.get("label", ""),
            })

        return {"nodes": nodes, "edges": edges}
