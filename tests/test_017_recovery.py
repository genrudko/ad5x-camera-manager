from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
app = (root / 'app.py').read_text()
installer = (root / 'install.sh').read_text()
updater = (root / 'update.sh').read_text()

assert "APP_VERSION = '0.1.9-beta'" in app
assert "start aborted after sensor policy failure; monitor will retry" in app
assert "kill_pidfile(pidfile)" in app
assert "time.sleep(0.75)" in app

# 0.1.7 recovery is retained; 0.1.8+ moves integration out of printer.cfg.
assert 'cp "$SRC/VERSION" "$DATA/VERSION"' in updater
assert 'chmod 0644 "$DATA/VERSION"' in updater
assert 'mod_data/user.cfg' in installer
assert 'mod_data/user.cfg' in updater
assert 'update_manager ad5x_camera_manager' in installer
assert "LEGACY_INCLUDE='[include mod_data/ad5x_custom/camera_manager/klipper.cfg]'" in installer
assert 'grep -Fvx "$LEGACY_INCLUDE" "$PRINTER"' in installer
assert '>>"$PRINTER"' not in installer

# Migration may remove only the exact legacy include, but must leave SAVE_CONFIG terminal.
sample = (
    "[heater_bed]\n"
    "heater_pin: x\n\n"
    "#*# <---------------------- SAVE_CONFIG ---------------------->\n"
    "#*# DO NOT EDIT\n"
    "#*# [heater_bed]\n"
    "#*# control = pid\n\n"
    "[include mod_data/ad5x_custom/camera_manager/klipper.cfg]\n"
)
marker = '[include mod_data/ad5x_custom/camera_manager/klipper.cfg]'
with tempfile.NamedTemporaryFile('w+', delete=False) as f:
    f.write(sample)
    path = f.name
out = subprocess.check_output(['grep', '-Fvx', marker, path], text=True)
assert marker not in out
assert out.index('SAVE_CONFIG') < out.index('#*# control = pid')
assert out.rstrip().endswith('#*# control = pid')
print('0.1.7 recovery + 0.1.9 Z-Mod installer regression checks: PASS')
