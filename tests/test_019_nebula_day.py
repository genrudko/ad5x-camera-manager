import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class NebulaDayModeTests(unittest.TestCase):
    def test_verified_xu_contract_is_preserved(self):
        helper = (ROOT / "drivers" / "nebula_day_mode.py").read_text()
        self.assertIn("UVCIOC_CTRL_QUERY = 0xC00C7521", helper)
        self.assertIn("UNIT = 6", helper)
        self.assertIn("SELECTOR = 16", helper)
        self.assertIn("CONTROL_SIZE = 60", helper)
        self.assertIn("DAY = 0", helper)
        self.assertIn("NIGHT = 1", helper)
        self.assertIn("AUTO = 2", helper)
        self.assertIn('"ensure-day"', helper)

    def test_manager_has_persistent_day_watchdog(self):
        app = (ROOT / "app.py").read_text()
        self.assertIn("'nebula_force_day'", app)
        self.assertIn("next_policy=now+60.0", app)
        self.assertIn("runtime.enforce_periodic_sensor_policy(p)", app)
        self.assertIn("a108", app)
        self.assertIn("2231", app)

    def test_update_installs_nebula_helper(self):
        update = (ROOT / "update.sh").read_text()
        self.assertIn("nebula_day_mode.py", update)


if __name__ == "__main__":
    unittest.main()
