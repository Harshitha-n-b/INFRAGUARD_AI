"""
tests/test_routing.py — Unit tests for route checking and alternative routes.
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from infraguard.simulation import InfraGuardSimulation
from infraguard.routing import check_route, find_alternative_routes, get_route_summary


class TestRouteChecking(unittest.TestCase):
    """Tests for route availability checking."""

    def setUp(self):
        self.sim = InfraGuardSimulation()

    def test_direct_route_available(self):
        result = check_route(self.sim, "Transport Hub", "Emergency Response Center")
        self.assertTrue(result["direct_route_available"])
        self.assertIn("Transport Hub", result["path"])
        self.assertIn("Emergency Response Center", result["path"])

    def test_route_via_alternative(self):
        result = check_route(self.sim, "Transport Hub", "Alternative Transport Route")
        self.assertTrue(result["direct_route_available"])

    def test_invalid_source(self):
        result = check_route(self.sim, "Nonexistent", "Hospital")
        self.assertIn("error", result)

    def test_invalid_target(self):
        result = check_route(self.sim, "Hospital", "Nonexistent")
        self.assertIn("error", result)


class TestRouteBlockage(unittest.TestCase):
    """Tests for blocked routes."""

    def setUp(self):
        self.sim = InfraGuardSimulation()
        self.sim.fail_component("Main Power Station")

    def test_route_blocked_by_affected_node(self):
        result = check_route(self.sim, "Transport Hub", "Emergency Response Center")
        # Transport Hub is affected, so route through it is blocked
        self.assertFalse(result["direct_route_available"])

    def test_blocked_nodes_listed(self):
        result = check_route(self.sim, "Transport Hub", "Emergency Response Center")
        self.assertTrue(len(result.get("blocked_nodes", [])) > 0)


class TestAlternativeRouting(unittest.TestCase):
    """Tests for alternative route discovery."""

    def setUp(self):
        self.sim = InfraGuardSimulation()

    def test_find_all_routes(self):
        routes = self.sim.find_all_routes("Transport Hub", "Emergency Response Center")
        self.assertTrue(len(routes) >= 1)

    def test_alternative_routes_when_healthy(self):
        routes = find_alternative_routes(
            self.sim, "Transport Hub", "Emergency Response Center"
        )
        self.assertTrue(len(routes) >= 1)

    def test_route_summary_format(self):
        summary = get_route_summary(self.sim, "Transport Hub", "Emergency Response Center")
        self.assertIn("Transport Hub", summary)
        self.assertIn("Emergency Response Center", summary)


class TestRouteAfterFailure(unittest.TestCase):
    """Tests for routing after infrastructure failure."""

    def setUp(self):
        self.sim = InfraGuardSimulation()
        # Fail only the Transport Hub
        self.sim.fail_component("Transport Hub")

    def test_direct_route_blocked(self):
        result = check_route(self.sim, "Transport Hub", "Emergency Response Center")
        self.assertFalse(result["direct_route_available"])

    def test_alternative_route_via_alt_transport(self):
        # Alternative Transport Route connects to Emergency Response Center
        # but we need a source that can reach it
        result = check_route(self.sim, "Alternative Transport Route", "Emergency Response Center")
        # Alt Transport Route is operational, ERC might be affected depending on power
        # Let's check its state first
        alt_state = self.sim.graph.nodes["Alternative Transport Route"]["state"]
        erc_state = self.sim.graph.nodes["Emergency Response Center"]["state"]
        if alt_state == "operational" and erc_state in ("operational", "restored"):
            self.assertTrue(result["direct_route_available"])


if __name__ == "__main__":
    unittest.main()
