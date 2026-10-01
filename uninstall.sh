#!/bin/sh
set -u

if [ -d /opt/config/mod_data ]; then
    CONFIG_ROOT="/opt/config"
else
    CONFIG_ROOT="/usr/data/config"
fi

DATA="$CONFIG_ROOT/mod_data/ad5x_camera_manager"
USER_CFG="$CONFIG_ROOT/mod_data/user.cfg"
CAMCONF="$CONFIG_ROOT/mod_data/camera.conf"
SAFE="$CONFIG_ROOT/mod_data/ad5x_custom/camera_safe/S99camera_safe.sh"
STATE="$DATA/install.state"
INCLUDE='[include plugins/ad5x_camera_manager/ad5x_camera_manager.cfg]'

[ -x "$DATA/camera-manager.sh" ] && "$DATA/camera-manager.sh" stop 2>/dev/null || true

if [ -f "$USER_CFG" ] && grep -qF "$INCLUDE" "$USER_CFG"; then
    TMP="$USER_CFG.ad5xcm.$$"
    grep -Fvx "$INCLUDE" "$USER_CFG" >"$TMP" || true
    cat "$TMP" >"$USER_CFG"
    rm -f "$TMP"
    echo "removed Camera Manager include from mod_data/user.cfg"
fi

OLD_START=""
[ -f "$STATE" ] && OLD_START="$(sed -n 's/^CAMERA_START_BEFORE=//p' "$STATE" | head -1)"
if [ -f "$CAMCONF" ] && [ -n "$OLD_START" ]; then
    if grep -q '^START=' "$CAMCONF"; then
        sed -i "s/^START=.*/START=$OLD_START/" "$CAMCONF"
    else
        echo "START=$OLD_START" >>"$CAMCONF"
    fi
    echo "restored camera.conf START=$OLD_START"
fi

if [ "$OLD_START" = "on" ] && [ -x "$SAFE" ]; then
    "$SAFE" restart 2>/dev/null || true
fi

echo "AD5X Camera Manager disabled."
echo "Persistent cameras.json/logs/backups remain in mod_data/ad5x_camera_manager."
echo "The Moonraker update_manager entry is intentionally kept so the repository can still be updated/re-enabled."
echo "Run FIRMWARE_RESTART when idle to unload CAMERA_* macros."
