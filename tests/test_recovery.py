"""
tests/test_recovery.py — Unit tests for recovery and backup activation.
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from infraguard.simulation import InfraGuardSimulation
from infraguard.recovery import (
    activate_backup,
    recover_component,
    get_available_backups,
    get_recovery_summary,
)


class TestBackupDiscovery(unittest.TestCase):
    """Tests for finding available backups."""

    def setUp(self):
        self.sim = InfraGuardSimulation()

    def test_backup_available_initially(self):
        backups = get_available_backups(self.sim)
        self.assertIn("Backup Generator", backups)

    def test_backup_unavailable_after_activation(self):
        self.sim.fail_component("Main Power Station")
        activate_backup(self.sim, "Backup Generator")
        backups = get_available_backups(self.sim)
        self.assertNotIn("Backup Generator", backups)

    def test_backup_unavailable_if_failed(self):
        self.sim.fail_component("Backup Generator")
        backups = get_available_backups(self.sim)
        self.assertNotIn("Backup Generator", backups)


class TestRecoveryActions(unittest.TestCase):
    """Tests for recovery actions."""

    def setUp(self):
        self.sim = InfraGuardSimulation()
        self.sim.fail_component("Main Power Station")

    def test_recover_failed_component(self):
        result = recover_component(self.sim, "Main Power Station")
        self.assertNotIn("error", result)

    def test_recover_returns_restored_list(self):
        result = recover_component(self.sim, "Main Power Station")
        self.assertIn("restored_services", result)

    def test_recover_invalid_component(self):
        result = recover_component(self.sim, "Nonexistent")
        self.assertIn("error", result)

    def test_recovery_summary_format(self):
        summary = get_recovery_summary(self.sim)
        self.assertIn("Failed components", summary)
        self.assertIn("Main Power Station", summary)


class TestFullRecoveryScenario(unittest.TestCase):
    """Test a complete fail → backup → recover → verify cycle."""

    def setUp(self):
        self.sim = InfraGuardSimulation()

    def test_full_cycle(self):
        # 1. All operational
        sev0 = self.sim.calculate_severity()
        self.assertEqual(sev0["level"], "NORMAL")

        # 2. Fail power
        self.sim.fail_component("Main Power Station")
        sev1 = self.sim.calculate_severity()
        self.assertEqual(sev1["level"], "CRITICAL")

        # 3. Activate backup
        self.sim.activate_backup("Backup Generator")
        sev2 = self.sim.calculate_severity()
        # Backup only covers Hospital and ERC with backup_power
        # But Water Treatment Plant, Telecom Tower, Transport Hub remain affected
        # So severity is still high

        # 4. Recover power station
        self.sim.recover_component("Main Power Station")
        sev3 = self.sim.calculate_severity()
        self.assertEqual(sev3["level"], "NORMAL")

        # 5. Verify all operational
        for name, state in self.sim.get_all_states().items():
            self.assertIn(state, ("operational", "restored"),
                         f"{name} should be operational or restored after full recovery")


if __name__ == "__main__":
    unittest.main()
