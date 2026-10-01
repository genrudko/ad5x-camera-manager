#!/bin/sh
set -eu

PLUGIN_NAME="ad5x_camera_manager"
REPO_URL="https://github.com/genrudko/ad5x-camera-manager.git"
SRC="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

if [ -d /opt/config/mod_data ]; then
    CONFIG_ROOT="/opt/config"
    RUN_PY="/bin/python3"
    CHROOT_MODE=1
else
    CONFIG_ROOT="/usr/data/config"
    CHROOT_ROOT="/usr/data/.mod/.zmod"
    RUN_PY="$CHROOT_ROOT/bin/python3"
    CHROOT_MODE=0
fi

DATA="$CONFIG_ROOT/mod_data/ad5x_camera_manager"
OLD_DATA="$CONFIG_ROOT/mod_data/ad5x_custom/camera_manager"
USER_CFG="$CONFIG_ROOT/mod_data/user.cfg"
CAMCONF="$CONFIG_ROOT/mod_data/camera.conf"
SAFE="$CONFIG_ROOT/mod_data/ad5x_custom/camera_safe/S99camera_safe.sh"
INCLUDE='[include plugins/ad5x_camera_manager/ad5x_camera_manager.cfg]'

case "$SRC" in
    */mod_data/plugins/ad5x_camera_manager) ;;
    *)
        echo "ERROR: repository must be cloned as mod_data/plugins/ad5x_camera_manager" >&2
        echo "Current path: $SRC" >&2
        exit 2
        ;;
esac

mkdir -p "$DATA" "$DATA/logs" "$DATA/run" "$DATA/backups"

# One-time migration from the pre-repository beta layout. Preserve user state.
if [ -d "$OLD_DATA" ]; then
    for F in cameras.json install.state; do
        if [ ! -e "$DATA/$F" ] && [ -e "$OLD_DATA/$F" ]; then
            cp "$OLD_DATA/$F" "$DATA/$F"
            echo "migrated $F from legacy beta layout"
        fi
    done
    if [ -d "$OLD_DATA/backups" ] && [ ! -e "$DATA/backups/.legacy-imported" ]; then
        cp -a "$OLD_DATA/backups/." "$DATA/backups/" 2>/dev/null || true
        : >"$DATA/backups/.legacy-imported"
    fi
fi

rm -rf "$DATA/web" "$DATA/drivers"
mkdir -p "$DATA/web" "$DATA/drivers"
cp "$SRC/app.py" "$DATA/app.py"
cp "$SRC/camera-manager.sh" "$DATA/camera-manager.sh"
cp "$SRC/VERSION" "$DATA/VERSION"
cp "$SRC/drivers/ov3660_orientation.py" "$DATA/drivers/ov3660_orientation.py"
cp "$SRC/drivers/nebula_day_mode.py" "$DATA/drivers/nebula_day_mode.py"
cp "$SRC/web/index.html" "$DATA/web/index.html"
cp "$SRC/web/app.js" "$DATA/web/app.js"
cp "$SRC/web/style.css" "$DATA/web/style.css"
chmod 0755 "$DATA/app.py" "$DATA/camera-manager.sh" "$DATA/drivers/ov3660_orientation.py" "$DATA/drivers/nebula_day_mode.py"
chmod 0644 "$DATA/VERSION" "$DATA/web/"*

if [ ! -f "$DATA/cameras.json" ]; then
    cp "$SRC/defaults/cameras.json" "$DATA/cameras.json"
    chmod 0644 "$DATA/cameras.json"
    echo "installed default camera profile"
else
    echo "keeping existing cameras.json"
fi

# Z-Mod's documented place for user Klipper integration is mod_data/user.cfg.
touch "$USER_CFG"
if ! grep -qF "$INCLUDE" "$USER_CFG"; then
    printf '\n# AD5X Camera Manager\n%s\n' "$INCLUDE" >>"$USER_CFG"
    echo "added Klipper include to mod_data/user.cfg"
fi

# Keep native Z-Mod camera service from competing for /dev/video* and :8080.
if [ -f "$CAMCONF" ]; then
    if grep -q '^START=' "$CAMCONF"; then
        sed -i 's/^START=.*/START=off/' "$CAMCONF"
    else
        echo 'START=off' >>"$CAMCONF"
    fi
fi

# Validate copied runtime before restarting it.
if [ "$CHROOT_MODE" = 1 ]; then
    /bin/python3 -m py_compile "$DATA/app.py" "$DATA/drivers/ov3660_orientation.py" "$DATA/drivers/nebula_day_mode.py"
else
    chroot "$CHROOT_ROOT" /bin/python3 -m py_compile \
        /opt/config/mod_data/ad5x_camera_manager/app.py \
        /opt/config/mod_data/ad5x_camera_manager/drivers/ov3660_orientation.py \
        /opt/config/mod_data/ad5x_camera_manager/drivers/nebula_day_mode.py
fi
sh -n "$DATA/camera-manager.sh"

# Stop any previous manager generation. The legacy and new paths may coexist during migration.
[ -x "$OLD_DATA/camera-manager.sh" ] && "$OLD_DATA/camera-manager.sh" stop 2>/dev/null || true
"$DATA/camera-manager.sh" stop 2>/dev/null || true
[ -x "$SAFE" ] && "$SAFE" stop 2>/dev/null || true
killall mjpg_streamer 2>/dev/null || true
killall ustreamer 2>/dev/null || true

"$DATA/camera-manager.sh" start

echo "AD5X Camera Manager updated to $(cat "$DATA/VERSION")"
echo "Klipper macros are sourced from: $INCLUDE"
echo "FIRMWARE_RESTART is required only when the .cfg integration changed."
