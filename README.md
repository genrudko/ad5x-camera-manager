# AD5X Camera Manager

Multi-camera manager for **Flashforge Adventurer 5X (AD5X) + Z-Mod**.

> Current development baseline: **0.1.8-beta**. The runtime camera code is based on the physically tested 0.1.7-beta line; 0.1.8-beta restructures installation and updates as a native Z-Mod git plugin.

[Русская документация](README_ru.md)

## Features

- multiple USB UVC cameras;
- stable device matching by VID/PID, serial and USB path instead of relying only on `/dev/videoN`;
- filters metadata nodes and the internal `felix-vdec` node;
- `mjpg_streamer` backend with per-camera resolution, FPS, buffer and port settings;
- verified OV3660 sensor-level 180° orientation helper;
- web UI on `http://PRINTER_IP:8095/` with live previews;
- CPU/load/RAM and real FPS measurement;
- per-camera logs and automatic restart;
- primary camera on port `8080` for Z-Mod compatibility;
- Fluidd/Moonraker webcam synchronization, including selectable MJPEG/Adaptive/UV4L-MJPEG service type;
- optional Camera Manager UI entry in Fluidd as an HTTP Page;
- Z-Mod-native git/update-manager layout.

## Z-Mod layout

The git checkout is kept clean and updateable:

```text
/opt/config/mod_data/plugins/ad5x_camera_manager/   # git repository
/opt/config/mod_data/ad5x_camera_manager/           # persistent runtime state
```

Persistent `cameras.json`, logs and backups are **not** stored inside the git checkout.

Klipper integration is added to Z-Mod's documented `mod_data/user.cfg`; the installer does not append plugin configuration after Klipper's `SAVE_CONFIG` block.

## First installation on AD5X

Enter the Z-Mod chroot and clone the repository using the required plugin directory name:

```sh
chroot /usr/data/.mod/.zmod/
cd /opt/config/mod_data/plugins/
git clone https://github.com/genrudko/ad5x-camera-manager.git ad5x_camera_manager
cd ad5x_camera_manager
sh install.sh
```

Then, when the printer is idle, run:

```gcode
FIRMWARE_RESTART
```

Restart Moonraker or reboot once so the new `ad5x_camera_manager` entry appears under **Software Updates** in Fluidd.

The installer writes the following update-manager entry to `mod_data/user.moonraker.conf` if it is missing:

```ini
[update_manager ad5x_camera_manager]
type: git_repo
channel: dev
path: /opt/config/mod_data/plugins/ad5x_camera_manager
origin: https://github.com/genrudko/ad5x-camera-manager.git
is_system_service: False
primary_branch: main
```

## Updates

After bootstrap, use **Fluidd → Software Updates**. Z-Mod runs `update.sh` for plugin updates; it keeps user camera configuration and runtime logs while replacing the tracked application files and restarting Camera Manager.

## Disable / uninstall

From the repository directory:

```sh
sh uninstall.sh
```

The runtime state is intentionally preserved. The script restores the original Z-Mod camera `START` value recorded during first installation and removes only the Camera Manager include from `mod_data/user.cfg`.

## Compatibility / safety

This project is currently beta and is being validated on a physical AD5X. A full two-camera print soak is still required before calling the current line production-ready.

The plugin does not patch tracked files under `/usr/data/zmod/...`.

## License

A project license has not been selected yet.
