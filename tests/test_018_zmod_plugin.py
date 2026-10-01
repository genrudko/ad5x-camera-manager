import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class ZModPluginLayoutTests(unittest.TestCase):
    def test_version_and_runtime_paths(self):
        app = (ROOT / "app.py").read_text()
        self.assertIn("APP_VERSION = '0.1.9-beta'", app)
        self.assertIn("/opt/config/mod_data/ad5x_camera_manager", app)
        self.assertNotIn("ad5x_custom/camera_manager", app)

    def test_native_plugin_cfg_exists(self):
        cfg = (ROOT / "ad5x_camera_manager.cfg").read_text()
        self.assertIn("[gcode_shell_command camera_manager]", cfg)
        self.assertIn("/usr/data/config/mod_data/ad5x_camera_manager/camera-manager.sh", cfg)

    def test_installer_does_not_append_to_printer_cfg(self):
        install = (ROOT / "install.sh").read_text()
        self.assertIn("mod_data/user.cfg", install)
        self.assertIn("update_manager ad5x_camera_manager", install)
        self.assertNotIn(">>\"$PRINTER\"", install)
        self.assertNotIn(">> \"$PRINTER\"", install)
        self.assertIn("grep -Fvx \"$LEGACY_INCLUDE\"", install)

    def test_update_manager_uses_git_checkout(self):
        install = (ROOT / "install.sh").read_text()
        self.assertIn("path: /opt/config/mod_data/plugins/ad5x_camera_manager", install)
        self.assertIn("origin: https://github.com/genrudko/ad5x-camera-manager.git", install)
        self.assertIn("primary_branch: main", install)

    def test_state_is_outside_git_checkout(self):
        update = (ROOT / "update.sh").read_text()
        self.assertIn('DATA="$CONFIG_ROOT/mod_data/ad5x_camera_manager"', update)
        self.assertIn('SRC="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"', update)
        self.assertIn("keeping existing cameras.json", update)


if __name__ == "__main__":
    unittest.main()
