#!/bin/sh
set -eu

PLUGIN_NAME="ad5x_camera_manager"
REPO_URL="https://github.com/genrudko/ad5x-camera-manager.git"
SRC="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

if [ -d /opt/config/mod_data ]; then
    CONFIG_ROOT="/opt/config"
else
    CONFIG_ROOT="/usr/data/config"
fi

DATA="$CONFIG_ROOT/mod_data/ad5x_camera_manager"
OLD_DATA="$CONFIG_ROOT/mod_data/ad5x_custom/camera_manager"
PRINTER="$CONFIG_ROOT/printer.cfg"
USER_CFG="$CONFIG_ROOT/mod_data/user.cfg"
MOONRAKER_CFG="$CONFIG_ROOT/mod_data/user.moonraker.conf"
CAMCONF="$CONFIG_ROOT/mod_data/camera.conf"
STATE="$DATA/install.state"
LEGACY_INCLUDE='[include mod_data/ad5x_custom/camera_manager/klipper.cfg]'
NEW_INCLUDE='[include plugins/ad5x_camera_manager/ad5x_camera_manager.cfg]'
TS="$(date '+%Y%m%d-%H%M%S' 2>/dev/null || echo install)"

case "$SRC" in
    */mod_data/plugins/ad5x_camera_manager) ;;
    *)
        echo "ERROR: clone repository as mod_data/plugins/ad5x_camera_manager" >&2
        echo "Current path: $SRC" >&2
        exit 2
        ;;
esac

mkdir -p "$DATA" "$DATA/backups"

# Migrate original installation state first so we retain the pre-manager camera START value.
if [ ! -f "$STATE" ] && [ -f "$OLD_DATA/install.state" ]; then
    cp "$OLD_DATA/install.state" "$STATE"
fi

OLD_START=""
[ -f "$STATE" ] && OLD_START="$(sed -n 's/^CAMERA_START_BEFORE=//p' "$STATE" | head -1)"
if [ -z "$OLD_START" ] && [ -f "$CAMCONF" ]; then
    OLD_START="$(sed -n 's/^START=//p' "$CAMCONF" | head -1)"
fi
if [ ! -f "$STATE" ]; then
    cat >"$STATE" <<EOF_STATE
INSTALL_TS=$TS
CAMERA_START_BEFORE=$OLD_START
EOF_STATE
fi

# Back up only files we may touch.
[ -f "$PRINTER" ] && cp "$PRINTER" "$DATA/backups/printer.cfg.$TS"
[ -f "$USER_CFG" ] && cp "$USER_CFG" "$DATA/backups/user.cfg.$TS"
[ -f "$MOONRAKER_CFG" ] && cp "$MOONRAKER_CFG" "$DATA/backups/user.moonraker.conf.$TS"
[ -f "$CAMCONF" ] && cp "$CAMCONF" "$DATA/backups/camera.conf.$TS"

# Repair the pre-repository beta integration: remove only its exact line from printer.cfg.
# SAVE_CONFIG stays untouched and terminal.
if [ -f "$PRINTER" ] && grep -qF "$LEGACY_INCLUDE" "$PRINTER"; then
    TMP="$PRINTER.ad5xcm.$$"
    grep -Fvx "$LEGACY_INCLUDE" "$PRINTER" >"$TMP" || true
    cat "$TMP" >"$PRINTER"
    rm -f "$TMP"
    echo "removed legacy Camera Manager include from printer.cfg"
fi

# Register the git checkout with Moonraker in Z-Mod's documented user config.
touch "$MOONRAKER_CFG"
if ! grep -q '^\[update_manager ad5x_camera_manager\]$' "$MOONRAKER_CFG"; then
    cat >>"$MOONRAKER_CFG" <<'EOF_MOONRAKER'

# AD5X Camera Manager — managed git plugin
[update_manager ad5x_camera_manager]
type: git_repo
channel: dev
path: /opt/config/mod_data/plugins/ad5x_camera_manager
origin: https://github.com/genrudko/ad5x-camera-manager.git
is_system_service: False
primary_branch: main
EOF_MOONRAKER
    echo "registered Moonraker update_manager ad5x_camera_manager"
fi

"$SRC/update.sh"

echo
echo "AD5X Camera Manager installed."
echo "Web UI: http://PRINTER_IP:8095/"
echo "Run FIRMWARE_RESTART once when the printer is idle to load the plugin macros."
echo "Restart Moonraker (or reboot once) to make the new Software Updates entry appear."
