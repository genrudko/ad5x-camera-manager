# 0.1.8-beta development baseline

- Repackaged as a Z-Mod-native git plugin.
- Git checkout lives in `mod_data/plugins/ad5x_camera_manager`.
- Persistent state moved outside the checkout to `mod_data/ad5x_camera_manager`.
- Klipper integration now uses `mod_data/user.cfg`; no plugin line is appended after `SAVE_CONFIG`.
- Installer migrates the previous `ad5x_custom/camera_manager` beta state and removes only the exact legacy `printer.cfg` include.
- Installer registers a Moonraker `git_repo` update manager for automatic Fluidd updates.
- Added idempotent `update.sh` and disable-safe `uninstall.sh`.
- Carries forward 0.1.7 camera recovery fixes: failed OV3660 policy attempts cannot leave a false-running wedged streamer behind.

This baseline is not tagged as a release until the new Z-Mod bootstrap/update path is accepted on the physical printer.
