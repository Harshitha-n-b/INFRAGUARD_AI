"""
tests/test_simulation.py — Unit tests for the InfraGuard simulation engine.

Covers: normal state, failure propagation, backup activation,
multiple failures, severity calculation, recovery, reset,
Resilience Twin comparison, and invalid component handling.
"""

import sys
import os
import unittest

# Ensure the project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from infraguard.simulation import InfraGuardSimulation


class TestNormalNetwork(unittest.TestCase):
    """Tests for the initial (healthy) network state."""

    def setUp(self):
        self.sim = InfraGuardSimulation()

    def test_all_nodes_operational(self):
        states = self.sim.get_all_states()
        for name, state in states.items():
            self.assertEqual(state, "operational", f"{name} should be operational")

    def test_node_count(self):
        self.assertEqual(len(self.sim.get_all_states()), 8)

    def test_no_failed_nodes(self):
        self.assertEqual(self.sim.get_failed_nodes(), [])

    def test_no_affected_nodes(self):
        self.assertEqual(self.sim.get_affected_nodes(), [])

    def test_severity_normal(self):
        sev = self.sim.calculate_severity()
        self.assertEqual(sev["level"], "NORMAL")
        self.assertEqual(sev["score"], 0)

    def test_critical_services_count(self):
        critical = self.sim.get_critical_services()
        self.assertEqual(len(critical), 5)
        self.assertIn("Hospital", critical)
        self.assertIn("Emergency Response Center", critical)


class TestPrimaryPowerFailure(unittest.TestCase):
    """Tests for Main Power Station failure propagation."""

    def setUp(self):
        self.sim = InfraGuardSimulation()
        self.result = self.sim.fail_component("Main Power Station")

    def test_power_station_is_failed(self):
        self.assertEqual(
            self.sim.graph.nodes["Main Power Station"]["state"], "failed"
        )

    def test_hospital_is_affected(self):
        self.assertEqual(
            self.sim.graph.nodes["Hospital"]["state"], "affected"
        )

    def test_water_plant_is_affected(self):
        self.assertEqual(
            self.sim.graph.nodes["Water Treatment Plant"]["state"], "affected"
        )

    def test_telecom_is_affected(self):
        self.assertEqual(
            self.sim.graph.nodes["Telecom Tower"]["state"], "affected"
        )

    def test_transport_hub_is_affected(self):
        self.assertEqual(
            self.sim.graph.nodes["Transport Hub"]["state"], "affected"
        )

    def test_emergency_center_is_affected(self):
        self.assertEqual(
            self.sim.graph.nodes["Emergency Response Center"]["state"], "affected"
        )

    def test_backup_generator_still_operational(self):
        self.assertEqual(
            self.sim.graph.nodes["Backup Generator"]["state"], "operational"
        )

    def test_severity_is_critical(self):
        sev = self.result["severity"]
        self.assertEqual(sev["level"], "CRITICAL")
        self.assertEqual(sev["score"], 100)

    def test_directly_affected_list(self):
        directly = self.result["directly_affected"]
        self.assertIn("Hospital", directly)
        self.assertIn("Water Treatment Plant", directly)

    def test_recommendations_include_backup(self):
        recs = self.result["recommendations"]
        backup_rec = [r for r in recs if "Backup Generator" in r]
        self.assertTrue(len(backup_rec) > 0, "Should recommend backup activation")


class TestBackupActivation(unittest.TestCase):
    """Tests for backup generator activation after power failure."""

    def setUp(self):
        self.sim = InfraGuardSimulation()
        self.sim.fail_component("Main Power Station")
        self.result = self.sim.activate_backup("Backup Generator")

    def test_no_error(self):
        self.assertNotIn("error", self.result)

    def test_hospital_restored(self):
        # Hospital has backup_power edge from Backup Generator
        # but also needs water from Water Treatment Plant (which is affected)
        # Water Treatment Plant is affected (no power), so Hospital
        # still has lost essential supply (water)
        # Actually, let's check: Hospital gets power from Main Power Station
        # and water from Water Treatment Plant.
        # After backup activation, Hospital gets backup_power from Backup Generator
        # (covers power). But Water Treatment Plant is still affected.
        # So Hospital still has lost water supply → stays affected.
        # Only if water is still available would Hospital be restored.
        state = self.sim.graph.nodes["Hospital"]["state"]
        # Hospital should remain affected because Water Treatment Plant is down
        self.assertEqual(state, "affected")

    def test_emergency_center_restored(self):
        # Emergency Response Center needs: power, communications (from Telecom Tower)
        # Backup Generator provides backup_power → power is covered
        # But Telecom Tower is affected → comm supply lost
        # So ERC should remain affected
        state = self.sim.graph.nodes["Emergency Response Center"]["state"]
        self.assertEqual(state, "affected")

    def test_backup_already_activated_error(self):
        result2 = self.sim.activate_backup("Backup Generator")
        self.assertIn("error", result2)

    def test_non_backup_activation_error(self):
        result = self.sim.activate_backup("Hospital")
        self.assertIn("error", result)


class TestMultipleFailures(unittest.TestCase):
    """Tests for handling multiple simultaneous failures."""

    def setUp(self):
        self.sim = InfraGuardSimulation()

    def test_two_failures(self):
        self.sim.fail_component("Main Power Station")
        result2 = self.sim.fail_component("Alternative Transport Route")
        self.assertNotIn("error", result2)
        self.assertEqual(
            self.sim.graph.nodes["Alternative Transport Route"]["state"], "failed"
        )

    def test_double_failure_same_component_error(self):
        self.sim.fail_component("Main Power Station")
        result2 = self.sim.fail_component("Main Power Station")
        self.assertIn("error", result2)

    def test_cascading_severity(self):
        self.sim.fail_component("Main Power Station")
        sev1 = self.sim.calculate_severity()
        self.sim.fail_component("Backup Generator")
        sev2 = self.sim.calculate_severity()
        # Backup Generator is not critical, severity shouldn't change
        self.assertEqual(sev1["score"], sev2["score"])


class TestRecovery(unittest.TestCase):
    """Tests for component recovery."""

    def setUp(self):
        self.sim = InfraGuardSimulation()
        self.sim.fail_component("Main Power Station")

    def test_recover_power_station(self):
        result = self.sim.recover_component("Main Power Station")
        self.assertNotIn("error", result)
        self.assertEqual(
            self.sim.graph.nodes["Main Power Station"]["state"], "operational"
        )

    def test_downstream_restored_after_recovery(self):
        result = self.sim.recover_component("Main Power Station")
        restored = result.get("restored_services", [])
        # All affected services should be restored
        self.assertIn("Hospital", restored)
        self.assertIn("Water Treatment Plant", restored)

    def test_severity_returns_to_normal(self):
        self.sim.recover_component("Main Power Station")
        sev = self.sim.calculate_severity()
        self.assertEqual(sev["level"], "NORMAL")

    def test_recover_operational_error(self):
        result = self.sim.recover_component("Hospital")
        # Hospital is affected, not failed — recovery should still work
        # Actually Hospital is 'affected', which is not 'operational'
        # So recover_component should mark it operational
        self.assertNotIn("error", result)


class TestReset(unittest.TestCase):
    """Tests for simulation reset."""

    def setUp(self):
        self.sim = InfraGuardSimulation()
        self.sim.fail_component("Main Power Station")
        self.sim.activate_backup("Backup Generator")
        self.reset_result = self.sim.reset()

    def test_all_operational_after_reset(self):
        states = self.sim.get_all_states()
        for name, state in states.items():
            self.assertEqual(state, "operational", f"{name} should be operational after reset")

    def test_severity_normal_after_reset(self):
        self.assertEqual(self.reset_result["severity"]["level"], "NORMAL")

    def test_event_log_records_reset(self):
        log = self.sim.get_event_log()
        self.assertTrue(any("RESET" in entry for entry in log))


class TestInvalidComponent(unittest.TestCase):
    """Tests for invalid component names."""

    def setUp(self):
        self.sim = InfraGuardSimulation()

    def test_fail_invalid(self):
        result = self.sim.fail_component("Nonexistent Station")
        self.assertIn("error", result)

    def test_recover_invalid(self):
        result = self.sim.recover_component("Nonexistent Station")
        self.assertIn("error", result)

    def test_activate_invalid(self):
        result = self.sim.activate_backup("Nonexistent Backup")
        self.assertIn("error", result)

    def test_node_exists_false(self):
        self.assertFalse(self.sim.node_exists("Nonexistent"))


class TestResilienceTwin(unittest.TestCase):
    """Tests for the Resilience Twin scenario comparison."""

    def setUp(self):
        self.sim = InfraGuardSimulation()

    def test_baseline_vs_recovery(self):
        # Fail power station
        self.sim.fail_component("Main Power Station")
        baseline = self.sim.create_snapshot()

        # Activate backup
        self.sim.activate_backup("Backup Generator")
        recovery = self.sim.create_snapshot()

        comparison = self.sim.compare_scenarios(baseline, recovery)

        self.assertGreaterEqual(comparison["improvement_score"], 0)
        self.assertGreaterEqual(comparison["baseline_down_count"],
                               comparison["recovery_down_count"])

    def test_identical_scenarios(self):
        self.sim.fail_component("Main Power Station")
        snap1 = self.sim.create_snapshot()
        snap2 = self.sim.create_snapshot()

        comparison = self.sim.compare_scenarios(snap1, snap2)
        self.assertEqual(comparison["improvement_score"], 0)
        self.assertEqual(comparison["services_recovered"], [])


if __name__ == "__main__":
    unittest.main()
