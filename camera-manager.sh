#!/bin/sh
set -u

PORT=8095
HOST_CHROOT="/usr/data/.mod/.zmod"
HOST_DATA="/usr/data/config/mod_data/ad5x_camera_manager"
CHROOT_DATA="/opt/config/mod_data/ad5x_camera_manager"

if [ -d /opt/config/mod_data ] && [ -x /bin/python3 ]; then
    MODE=chroot
    BASE="$CHROOT_DATA"
else
    MODE=host
    BASE="$HOST_DATA"
fi

PID="$BASE/run/camera-manager.pid"
LOG="$BASE/logs/camera-manager-launch.log"
mkdir -p "$BASE/run" "$BASE/logs"

proc_matches_manager() {
    P="$1"
    [ -n "$P" ] || return 1
    [ -r "/proc/$P/cmdline" ] || return 1
    CMDLINE="$(tr '\000' ' ' <"/proc/$P/cmdline" 2>/dev/null || true)"
    case "$CMDLINE" in
        *"/opt/config/mod_data/ad5x_camera_manager/app.py serve"*) return 0 ;;
        *"/usr/data/config/mod_data/ad5x_camera_manager/app.py serve"*) return 0 ;;
    esac
    return 1
}

alive() {
    [ -f "$PID" ] || return 1
    P="$(cat "$PID" 2>/dev/null || true)"
    [ -n "$P" ] || return 1
    proc_matches_manager "$P"
}

http_ready() {
    wget -qO- --timeout=2 "http://127.0.0.1:$PORT/api/status" >/dev/null 2>&1
}

start_manager() {
    if alive; then
        echo "camera-manager already running pid=$(cat "$PID")"
        return 0
    fi

    if [ "$MODE" = chroot ]; then
        [ -x /bin/python3 ] || { echo "ERROR: /bin/python3 missing" >&2; return 40; }
        [ -f "$BASE/app.py" ] || { echo "ERROR: app.py missing: $BASE/app.py" >&2; return 41; }
        echo "$(date '+%Y-%m-%d %H:%M:%S') launch" >>"$LOG"
        /bin/sh -c "cd '$BASE' || exit 1; nohup /bin/python3 '$BASE/app.py' serve </dev/null >>'$BASE/logs/camera-manager-stdout.log' 2>&1 & echo \$! >'$BASE/run/camera-manager.pid'"
    else
        [ -x "$HOST_CHROOT/bin/python3" ] || { echo "ERROR: Z-Mod chroot Python missing" >&2; return 40; }
        [ -f "$HOST_CHROOT$CHROOT_DATA/app.py" ] || { echo "ERROR: app.py missing in chroot: $CHROOT_DATA/app.py" >&2; return 41; }
        echo "$(date '+%Y-%m-%d %H:%M:%S') launch" >>"$LOG"
        chroot "$HOST_CHROOT" /bin/sh -c "cd '$CHROOT_DATA' || exit 1; nohup /bin/python3 '$CHROOT_DATA/app.py' serve </dev/null >>'$CHROOT_DATA/logs/camera-manager-stdout.log' 2>&1 & echo \$! >'$CHROOT_DATA/run/camera-manager.pid'"
    fi

    N=0
    while [ "$N" -lt 100 ]; do
        if alive && http_ready; then
            break
        fi
        if ! alive && [ "$N" -gt 5 ]; then
            break
        fi
        N=$((N + 1))
        sleep 0.1
    done
    if ! alive || ! http_ready; then
        echo "ERROR: camera-manager failed readiness check" >&2
        rm -f "$PID"
        tail -60 "$BASE/logs/camera-manager-stdout.log" 2>/dev/null || true
        return 42
    fi
    IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
    echo "camera-manager started pid=$(cat "$PID") url=http://${IP:-PRINTER_IP}:$PORT/"
}

stop_manager() {
    if ! alive; then
        rm -f "$PID"
        echo "camera-manager already stopped"
        return 0
    fi
    P="$(cat "$PID")"
    kill "$P" 2>/dev/null || true
    N=0
    while [ "$N" -lt 100 ] && proc_matches_manager "$P"; do
        N=$((N + 1)); sleep 0.1
    done
    if proc_matches_manager "$P"; then
        kill -9 "$P" 2>/dev/null || true
        N=0
        while [ "$N" -lt 20 ] && proc_matches_manager "$P"; do
            N=$((N + 1)); sleep 0.1
        done
    fi
    rm -f "$PID"
    if proc_matches_manager "$P"; then
        echo "ERROR: camera-manager pid $P did not stop" >&2
        return 43
    fi
    echo "camera-manager stopped"
}

api_post() {
    PATH_="$1"
    DATA="$2"
    wget -qO- --header='Content-Type: application/json' --post-data="$DATA" \
        "http://127.0.0.1:$PORT$PATH_" 2>/dev/null
}

cmd="${1:-status}"
id="${2:-}"
case "$cmd" in
    start) start_manager ;;
    stop) stop_manager ;;
    restart) stop_manager; sleep 1; start_manager ;;
    status)
        if alive; then
            echo "camera-manager running pid=$(cat "$PID")"
            wget -qO- "http://127.0.0.1:$PORT/api/status" 2>/dev/null || true
            echo
        else
            echo "camera-manager stopped"
        fi
        ;;
    on)
        [ -n "$id" ] || { echo "usage: $0 on CAMERA_ID" >&2; exit 2; }
        api_post /api/camera/action "{\"id\":\"$id\",\"action\":\"enable\"}"; echo
        ;;
    off)
        [ -n "$id" ] || { echo "usage: $0 off CAMERA_ID" >&2; exit 2; }
        api_post /api/camera/action "{\"id\":\"$id\",\"action\":\"disable\"}"; echo
        ;;
    camera-restart)
        [ -n "$id" ] || { echo "usage: $0 camera-restart CAMERA_ID" >&2; exit 2; }
        api_post /api/camera/action "{\"id\":\"$id\",\"action\":\"restart\"}"; echo
        ;;
    primary)
        [ -n "$id" ] || { echo "usage: $0 primary CAMERA_ID" >&2; exit 2; }
        api_post /api/camera/action "{\"id\":\"$id\",\"action\":\"primary\"}"; echo
        ;;
    ui)
        IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
        if [ -n "$IP" ] && alive; then
            api_post /api/fluidd/sync-ui "{\"host\":\"$IP\"}" >/dev/null 2>&1 || true
        fi
        echo "Camera Manager UI: http://${IP:-PRINTER_IP}:$PORT/"
        echo "Fluidd entry: AD5X Camera Manager UI (HTTP Page)"
        ;;
    *)
        echo "usage: $0 {start|stop|restart|status|ui|on ID|off ID|camera-restart ID|primary ID}" >&2
        exit 2
        ;;
esac
