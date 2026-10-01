#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ctypes
import glob
import http.client
import http.server
import json
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Any

CHROOT_BASE = Path('/opt/config/mod_data/ad5x_camera_manager')
HOST_BASE = Path('/usr/data/config/mod_data/ad5x_camera_manager')
BASE = CHROOT_BASE if CHROOT_BASE.exists() else HOST_BASE
CONFIG_PATH = BASE / 'cameras.json'
LOG_DIR = BASE / 'logs'
RUN_DIR = BASE / 'run'
WEB_DIR = BASE / 'web'
MANAGER_LOG = LOG_DIR / 'camera-manager.log'
MANAGER_PID = RUN_DIR / 'camera-manager.pid'
DEFAULT_LISTEN = '0.0.0.0'
DEFAULT_PORT = 8095
APP_VERSION = '0.1.9-beta'
FLUIDD_SERVICES = ('mjpegstreamer', 'mjpegstreamer-adaptive', 'uv4l-mjpeg')

V4L2_CAP_VIDEO_CAPTURE = 0x00000001
V4L2_CAP_VIDEO_CAPTURE_MPLANE = 0x00001000
V4L2_CAP_STREAMING = 0x04000000
V4L2_CAP_DEVICE_CAPS = 0x80000000
VIDIOC_QUERYCAP = 0x80685600
CPU_CLK_TCK = os.sysconf(os.sysconf_names['SC_CLK_TCK'])
NCPU = max(1, os.cpu_count() or 1)
_state_lock = threading.RLock()
_shutdown = threading.Event()


def ensure_dirs() -> None:
    for p in (LOG_DIR, RUN_DIR):
        p.mkdir(parents=True, exist_ok=True)


def log(msg: str) -> None:
    ensure_dirs()
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    try:
        with MANAGER_LOG.open('a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass


def atomic_json(path: Path, value: Any) -> None:
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(tmp, path)


def load_config() -> dict[str, Any]:
    raw = json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
    raw.setdefault('version', 1)
    raw.setdefault('listen', {'host': DEFAULT_LISTEN, 'port': DEFAULT_PORT})
    raw.setdefault('settings', {})
    raw.setdefault('cameras', [])

    # Config schema v2 folds the previously standalone Nebula DAY watchdog
    # into Camera Manager. Apply this migration only once; afterwards a user
    # may deliberately choose another sensor policy without it being reset.
    migrated = False
    if int(raw.get('version') or 1) < 2:
        for profile in raw['cameras']:
            if not isinstance(profile, dict):
                continue
            match = profile.get('match') or {}
            if (
                str(match.get('vid') or '').lower() == 'a108'
                and str(match.get('pid') or '').lower() == '2231'
                and str(profile.get('sensor_policy') or 'none') == 'none'
            ):
                profile['sensor_policy'] = 'nebula_force_day'
                migrated = True
        raw['version'] = 2
        migrated = True

    for profile in raw['cameras']:
        if isinstance(profile, dict):
            profile.setdefault('fluidd_service', 'mjpegstreamer')

    if migrated:
        atomic_json(CONFIG_PATH, raw)
        log('config migrated to schema v2 (Nebula DAY watchdog integrated)')
    return raw


def save_config(cfg: dict[str, Any]) -> None:
    with _state_lock:
        atomic_json(CONFIG_PATH, cfg)


def read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding='utf-8', errors='replace').strip()
    except Exception:
        return None


def query_v4l2(node: str) -> dict[str, Any]:
    """
    Probe a video node without VIDIOC_QUERYCAP from Python.

    On AD5X 32-bit MIPS, Python 3.12 + the fcntl V4L2 QUERYCAP path
    can terminate the interpreter with SIGSEGV. Discovery therefore uses
    video4linux sysfs metadata only. Actual format negotiation remains the
    streamer's responsibility.
    """
    name = Path(node).name
    cls = Path('/sys/class/video4linux') / name
    idx_raw = read_text(cls / 'index')
    card = read_text(cls / 'name') or name
    try:
        node_index = int(idx_raw) if idx_raw is not None else None
    except ValueError:
        node_index = None

    # UVC capture is normally index 0; metadata companion is non-zero.
    # If index is unavailable, keep it as a candidate and let strict
    # VID/PID/USB-path matching decide without touching the device via ioctl.
    capture = (node_index == 0) if node_index is not None else True
    return {
        'node': node,
        'capture': capture,
        'streaming': capture,
        'driver': '',
        'card': card,
        'bus_info': '',
        'capabilities': 0,
        'node_index': node_index,
        'probe': 'sysfs',
    }


def usb_identity_for_video(video_name: str) -> dict[str, str]:
    base = Path('/sys/class/video4linux') / video_name
    out = {'vid': '', 'pid': '', 'serial': '', 'usb_path': '', 'product': '', 'manufacturer': ''}
    try:
        cur = (base / 'device').resolve()
    except Exception:
        return out
    for _ in range(10):
        vid = read_text(cur / 'idVendor')
        pid = read_text(cur / 'idProduct')
        if vid and pid:
            out.update({
                'vid': vid.lower(), 'pid': pid.lower(),
                'serial': read_text(cur / 'serial') or '',
                'product': read_text(cur / 'product') or '',
                'manufacturer': read_text(cur / 'manufacturer') or '',
                'usb_path': cur.name,
            })
            break
        if cur.parent == cur:
            break
        cur = cur.parent
    return out


def enumerate_devices() -> list[dict[str, Any]]:
    devices = []
    def key(node: str) -> int:
        m = re.search(r'(\d+)$', node)
        return int(m.group(1)) if m else 9999
    for node in sorted(glob.glob('/dev/video*'), key=key):
        name = Path(node).name
        cap = query_v4l2(node)
        usb = usb_identity_for_video(name)
        sys_name = read_text(Path('/sys/class/video4linux') / name / 'name') or cap.get('card') or name
        item = {**cap, **usb, 'name': sys_name}
        # Camera Manager manages external USB UVC cameras only.
        # Internal SoC nodes such as felix-vdec also have video index=0,
        # but have no USB VID/PID and must never be offered as cameras.
        if item.get('capture') and item.get('vid') and item.get('pid'):
            item['transport'] = 'usb'
            devices.append(item)
    return devices


def match_device(profile: dict[str, Any], devices: list[dict[str, Any]], used: set[str] | None = None) -> dict[str, Any] | None:
    used = used or set()
    m = profile.get('match') or {}
    def same(v: Any, expected: Any) -> bool:
        if expected in (None, ''):
            return True
        return str(v or '').lower() == str(expected).lower()
    candidates = []
    for d in devices:
        if d['node'] in used:
            continue
        if not same(d.get('vid'), m.get('vid')) or not same(d.get('pid'), m.get('pid')):
            continue
        if not same(d.get('serial'), m.get('serial')) or not same(d.get('usb_path'), m.get('usb_path')):
            continue
        nc = str(m.get('name_contains') or '').lower().strip()
        if nc and nc not in str(d.get('name') or '').lower():
            continue
        candidates.append(d)
    if not candidates and m.get('usb_path'):
        relaxed = []
        for d in devices:
            if d['node'] in used:
                continue
            if not same(d.get('vid'), m.get('vid')) or not same(d.get('pid'), m.get('pid')):
                continue
            if not same(d.get('serial'), m.get('serial')):
                continue
            relaxed.append(d)
        if len(relaxed) == 1:
            relaxed[0] = dict(relaxed[0]); relaxed[0]['path_fallback'] = True
            candidates = relaxed
    # Some Z-Mod chroots may expose /dev but not USB sysfs. In that case,
    # a unique remaining capture node is a safe bootstrap fallback. As soon as
    # sysfs identity is available, strict VID/PID/path matching takes over.
    if not candidates and devices and all(not d.get('vid') and not d.get('pid') for d in devices):
        unused = [dict(d) for d in devices if d['node'] not in used]
        if len(unused) == 1:
            unused[0]['identity_fallback'] = True
            candidates = unused
    return candidates[0] if len(candidates) == 1 else None


def proc_alive(pid: int) -> bool:
    return pid > 1 and Path(f'/proc/{pid}').exists()


def proc_cmdline(pid: int) -> str:
    try:
        return Path(f'/proc/{pid}/cmdline').read_bytes().replace(b'\0', b' ').decode(errors='replace').strip()
    except Exception:
        return ''


def read_pidfile(path: Path) -> int:
    try:
        return int(path.read_text().strip())
    except Exception:
        return 0


def kill_pidfile(path: Path) -> None:
    pid = read_pidfile(path)
    if not proc_alive(pid):
        path.unlink(missing_ok=True); return
    try: os.kill(pid, signal.SIGTERM)
    except ProcessLookupError: pass
    deadline = time.time() + 3.0
    while time.time() < deadline and proc_alive(pid):
        time.sleep(0.1)
    if proc_alive(pid):
        try: os.kill(pid, signal.SIGKILL)
        except ProcessLookupError: pass
    path.unlink(missing_ok=True)


def port_open(port: int) -> bool:
    s = socket.socket(); s.settimeout(0.2)
    try: return s.connect_ex(('127.0.0.1', int(port))) == 0
    finally: s.close()


def wait_port(port: int, seconds: float = 4.0) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if port_open(port): return True
        time.sleep(0.1)
    return False


def binary_exists(path: str) -> bool:
    return Path(path).exists() and os.access(path, os.X_OK)


def v4l2_ctl_exe() -> str:
    return next((x for x in ('/usr/bin/v4l2-ctl', '/usr/local/bin/v4l2-ctl', '/bin/v4l2-ctl') if Path(x).exists()), '')


def normalize_format_name(value: str) -> str:
    v = str(value or '').upper()
    if v in ('MJPG', 'JPEG', 'MJPEG'):
        return 'MJPEG'
    if v in ('YUY2', 'YUYV'):
        return 'YUYV'
    return v


def parse_v4l2_modes(text: str) -> list[dict[str, Any]]:
    modes: list[dict[str, Any]] = []
    current_format = ''
    current_mode: dict[str, Any] | None = None
    for raw in text.splitlines():
        line = raw.strip()
        fm = re.match(r"\[\d+\]:\s*'([^']+)'", line)
        if fm:
            current_format = normalize_format_name(fm.group(1))
            current_mode = None
            continue
        sm = re.match(r'Size:\s+Discrete\s+(\d+)x(\d+)', line)
        if sm and current_format:
            current_mode = {
                'format': current_format,
                'width': int(sm.group(1)),
                'height': int(sm.group(2)),
                'fps': [],
            }
            modes.append(current_mode)
            continue
        im = re.search(r'\((\d+(?:\.\d+)?)\s+fps\)', line, re.I)
        if im and current_mode is not None:
            fps = float(im.group(1))
            value: int | float = int(round(fps)) if abs(fps - round(fps)) < 0.01 else round(fps, 3)
            if value not in current_mode['fps']:
                current_mode['fps'].append(value)
    return modes


def get_v4l2_modes(node: str) -> dict[str, Any]:
    exe = v4l2_ctl_exe()
    if not exe:
        return {'node': node, 'text': 'v4l2-ctl not found', 'modes': []}
    cp = subprocess.run([exe, '-d', node, '--list-formats-ext'], capture_output=True, text=True, timeout=6)
    text = (cp.stdout or '') + (cp.stderr or '')
    if cp.returncode != 0:
        raise RuntimeError(text.strip() or f'v4l2-ctl failed rc={cp.returncode}')
    return {'node': node, 'text': text, 'modes': parse_v4l2_modes(text)}


def ensure_stream_mode_supported(profile: dict[str, Any], device: str) -> None:
    if str(profile.get('backend', 'mjpg_streamer')) != 'mjpg_streamer':
        return
    fmt = normalize_format_name(str(profile.get('format', 'MJPEG')))
    if fmt not in ('MJPEG', 'YUYV'):
        raise RuntimeError(f'mjpg_streamer format {fmt} is not supported by Camera Manager')
    info = get_v4l2_modes(device)
    modes = info.get('modes') or []
    if not modes:
        # Do not make a missing diagnostic tool a runtime dependency.
        return
    width = int(profile.get('width', 0)); height = int(profile.get('height', 0)); fps = float(profile.get('fps', 0))
    candidates = [m for m in modes if m['format'] == fmt and m['width'] == width and m['height'] == height]
    if not candidates:
        raise RuntimeError(f'unsupported mode: {fmt} {width}x{height}')
    advertised = [float(x) for x in candidates[0].get('fps', [])]
    if advertised and not any(abs(x - fps) < 0.05 for x in advertised):
        available = ', '.join(str(x).rstrip('0').rstrip('.') if isinstance(x, float) else str(x) for x in candidates[0]['fps'])
        raise RuntimeError(f'unsupported FPS {fps:g} for {fmt} {width}x{height}; available: {available}')


def streamer_command(profile: dict[str, Any], device: str) -> tuple[list[str], str, str]:
    backend = profile.get('backend', 'mjpg_streamer')
    width, height = int(profile.get('width', 1280)), int(profile.get('height', 720))
    fps, buffers, port = int(profile.get('fps', 30)), int(profile.get('buffers', 4)), int(profile.get('port', 8080))
    fmt = str(profile.get('format', 'MJPEG')).upper()
    if backend == 'mjpg_streamer':
        exe = '/usr/bin/mjpg_streamer'; inp = '/usr/lib/mjpg-streamer/input_uvc.so'; out = '/usr/lib/mjpg-streamer/output_http.so'
        if not binary_exists(exe): raise RuntimeError(f'{exe} not found')
        if not Path(inp).exists() or not Path(out).exists(): raise RuntimeError('mjpg_streamer plugins not found')
        input_args = f'{inp} -b {buffers} -d {device} -r {width}x{height} -f {fps}'
        if fmt in ('YUYV', 'YUY2'): input_args += ' -y'
        return [exe, '-o', f'{out} -w /usr/share/mjpg-streamer/www -p {port}', '-i', input_args], f'http://HOST:{port}/?action=stream', f'http://HOST:{port}/?action=snapshot'
    if backend == 'ustreamer':
        candidates = ['/usr/data/zmod/zmod/.shell/root/zcam/ustreamer', '/usr/bin/ustreamer']
        exe = next((p for p in candidates if binary_exists(p)), '')
        if not exe: raise RuntimeError('ustreamer not found')
        cmd = [exe, '--process-name-prefix', f"cm_{profile['id']}", '-l', '-b', str(buffers), '-d', device,
               '-r', f'{width}x{height}', '-f', str(fps), '--format', fmt, '-s', '0.0.0.0', '-p', str(port),
               '-m', 'MJPEG', '--device-timeout=2', '-w', '1', '-I', 'MMAP', '-c', 'HW']
        return cmd, f'http://HOST:{port}/stream', f'http://HOST:{port}/snapshot'
    raise RuntimeError(f'unsupported backend: {backend}')

# ---- OV3660 orientation policy ----
#
# Important: the validated Sonix XU/SCCB sequence runs in a SHORT-LIVED
# helper process, not inside the long-running Camera Manager daemon.
# This mirrors the already-proven camera_safe implementation and isolates
# any native ioctl failure from the manager process.

def apply_sensor_policy(profile: dict[str, Any], device: str) -> dict[str, Any] | None:
    policy = str(profile.get('sensor_policy') or 'none')
    if policy == 'none':
        return None

    if policy in ('ov3660_rot180', 'ov3660_qxga_rot180'):
        helper = BASE / 'drivers' / 'ov3660_orientation.py'
        command = 'apply'
        attempts = 10
        label = 'OV3660'
    elif policy == 'nebula_force_day':
        helper = BASE / 'drivers' / 'nebula_day_mode.py'
        command = 'ensure-day'
        attempts = 3
        label = 'Nebula'
    else:
        raise RuntimeError(f'unknown sensor policy: {policy}')

    if not helper.exists():
        raise RuntimeError(f'{label} helper missing: {helper}')

    failures: list[str] = []

    for attempt in range(1, attempts + 1):
        try:
            cp = subprocess.run(
                [sys.executable, str(helper), device, command],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=5,
                close_fds=True,
            )
        except subprocess.TimeoutExpired:
            failures.append(f'attempt {attempt}: timeout')
            time.sleep(0.35)
            continue

        output = (cp.stdout or '').strip()
        if cp.returncode == 0:
            return {
                'driver': 'verified-external-helper',
                'attempt': attempt,
                'output': output,
            }

        failures.append(
            f'attempt {attempt}: rc={cp.returncode} {output[-240:]}'
        )
        if _shutdown.is_set():
            raise RuntimeError('manager is shutting down')
        time.sleep(0.35)

    raise RuntimeError(
        f'{label} helper failed after {attempts} attempts: ' +
        ' | '.join(failures[-3:])
    )


def moonraker_request(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode('utf-8')
    headers = {'Accept': 'application/json'}
    if body is not None:
        headers['Content-Type'] = 'application/json'
    conn = http.client.HTTPConnection('127.0.0.1', 7125, timeout=4)
    try:
        conn.request(method, path, body=body, headers=headers)
        resp = conn.getresponse()
        raw = resp.read()
    finally:
        conn.close()
    text = raw.decode('utf-8', errors='replace')
    try:
        data = json.loads(text) if text else {}
    except json.JSONDecodeError:
        data = {'raw': text}
    if resp.status < 200 or resp.status >= 300:
        msg = data.get('error') if isinstance(data, dict) else None
        raise RuntimeError(f'Moonraker HTTP {resp.status}: {msg or text[:300]}')
    if isinstance(data, dict) and isinstance(data.get('result'), dict):
        return data['result']
    return data if isinstance(data, dict) else {'result': data}


def sync_fluidd_webcam(profile: dict[str, Any], host: str) -> dict[str, Any]:
    host = str(host or '').strip()
    if not re.fullmatch(r'[A-Za-z0-9.-]+', host):
        raise ValueError('invalid printer host')
    port = int(profile.get('port', 8080))
    width = int(profile.get('width', 4)); height = int(profile.get('height', 3))
    import math
    g = max(1, math.gcd(width, height))
    aspect = f'{width // g}:{height // g}'
    cid = str(profile['id'])
    name = f"Camera Manager · {profile.get('name') or cid}"[:80]
    listing = moonraker_request('GET', '/server/webcams/list')
    webcams = listing.get('webcams', []) if isinstance(listing, dict) else []
    existing = next((w for w in webcams if (w.get('extra_data') or {}).get('ad5x_camera_manager_id') == cid), None)
    if not existing:
        existing = next((w for w in webcams if w.get('name') == name and w.get('source') == 'database'), None)
    payload: dict[str, Any] = {
        'name': name,
        'location': 'printer',
        'service': str(profile.get('fluidd_service') or 'mjpegstreamer'),
        'enabled': bool(profile.get('enabled', True)),
        'target_fps': max(1, min(120, int(profile.get('fps', 15)))),
        'target_fps_idle': max(1, min(5, int(profile.get('fps', 5)))),
        'stream_url': f'http://{host}:{port}/?action=stream' if profile.get('backend', 'mjpg_streamer') == 'mjpg_streamer' else f'http://{host}:{port}/stream',
        'snapshot_url': f'http://{host}:{port}/?action=snapshot' if profile.get('backend', 'mjpg_streamer') == 'mjpg_streamer' else f'http://{host}:{port}/snapshot',
        'flip_horizontal': False,
        'flip_vertical': False,
        'rotation': 0,
        'aspect_ratio': aspect,
        'extra_data': {'ad5x_camera_manager_id': cid, 'managed_by': 'AD5X Camera Manager'},
    }
    if existing and existing.get('source') == 'database' and existing.get('uid'):
        payload['uid'] = existing['uid']
    result = moonraker_request('POST', '/server/webcams/item', payload)
    return {'webcam': result.get('webcam', result), 'created': not bool(payload.get('uid'))}


def sync_fluidd_ui(host: str) -> dict[str, Any]:
    host = str(host or '').strip()
    if not re.fullmatch(r'[A-Za-z0-9.-]+', host):
        raise ValueError('invalid printer host')
    name = 'AD5X Camera Manager UI'
    listing = moonraker_request('GET', '/server/webcams/list')
    webcams = listing.get('webcams', []) if isinstance(listing, dict) else []
    existing = next((w for w in webcams if (w.get('extra_data') or {}).get('ad5x_camera_manager_ui') is True), None)
    if not existing:
        existing = next((w for w in webcams if w.get('name') == name and w.get('source') == 'database'), None)
    payload: dict[str, Any] = {
        'name': name,
        'location': 'printer',
        'service': 'iframe',
        'enabled': True,
        'target_fps': 1,
        'target_fps_idle': 1,
        'stream_url': f'http://{host}:{DEFAULT_PORT}/',
        'snapshot_url': '',
        'flip_horizontal': False,
        'flip_vertical': False,
        'rotation': 0,
        'aspect_ratio': '16:9',
        'extra_data': {'ad5x_camera_manager_ui': True, 'managed_by': 'AD5X Camera Manager'},
    }
    if existing and existing.get('source') == 'database' and existing.get('uid'):
        payload['uid'] = existing['uid']
    result = moonraker_request('POST', '/server/webcams/item', payload)
    return {'webcam': result.get('webcam', result), 'created': not bool(payload.get('uid'))}


def stream_probe(port: int, backend: str, seconds: float = 3.0) -> dict[str, Any]:
    path = '/?action=stream' if backend == 'mjpg_streamer' else '/stream'
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=max(5.0, seconds + 2))
    conn.request('GET', path); resp = conn.getresponse()
    if resp.status != 200: raise RuntimeError(f'HTTP {resp.status}')
    start = time.monotonic(); frames = 0; buf = b''; bytes_total = 0
    while time.monotonic() - start < seconds:
        chunk = resp.read(65536)
        if not chunk: break
        bytes_total += len(chunk); buf += chunk
        while True:
            soi = buf.find(b'\xff\xd8')
            if soi < 0: buf = buf[-2:]; break
            eoi = buf.find(b'\xff\xd9', soi + 2)
            if eoi < 0: buf = buf[soi:]; break
            frames += 1; buf = buf[eoi + 2:]
        if len(buf) > 4_000_000: buf = buf[-2:]
    elapsed = max(0.001, time.monotonic() - start); conn.close()
    return {'frames': frames, 'seconds': round(elapsed, 3), 'fps': round(frames / elapsed, 2),
            'mbit_s': round((bytes_total * 8 / elapsed) / 1_000_000, 2)}


class CameraRuntime:
    def __init__(self):
        self.processes: dict[str, subprocess.Popen] = {}
        self.devices: dict[str, dict[str, Any]] = {}
        self.errors: dict[str, str] = {}
        self.last_start_attempt: dict[str, float] = {}
        self.cpu_percent: dict[str, float] = {}
        self._cpu_prev: dict[str, tuple[int, float, int]] = {}
        self._ops_lock = threading.RLock()
    def pidfile(self, cid: str) -> Path: return RUN_DIR / f'camera-{cid}.pid'
    def logfile(self, cid: str) -> Path: return LOG_DIR / f'camera-{cid}.log'
    def refresh_devices(self, cfg: dict[str, Any]) -> list[dict[str, Any]]:
        devices = enumerate_devices(); used: set[str] = set(); resolved = {}
        for p in cfg.get('cameras', []):
            d = match_device(p, devices, used)
            if d: resolved[p['id']] = d; used.add(d['node'])
        self.devices = resolved; return devices
    def start_camera(self, profile: dict[str, Any], force: bool = False) -> None:
        with self._ops_lock:
            return self._start_camera_locked(profile, force)

    def _start_camera_locked(self, profile: dict[str, Any], force: bool = False) -> None:
        cid = profile['id']
        if not profile.get('enabled', True): return
        now = time.time()
        if not force and now - self.last_start_attempt.get(cid, 0) < 8: return
        self.last_start_attempt[cid] = now
        cfg = load_config(); self.refresh_devices(cfg); d = self.devices.get(cid)
        if not d: self.errors[cid] = 'matching capture device not found or ambiguous'; return
        pidfile = self.pidfile(cid); old_pid = read_pidfile(pidfile)
        if proc_alive(old_pid):
            cmdline = proc_cmdline(old_pid)
            if 'mjpg_streamer' in cmdline or 'ustreamer' in cmdline: return
            kill_pidfile(pidfile)
        port = int(profile.get('port', 8080))
        if port_open(port): self.errors[cid] = f'port {port} is already in use'; return
        try:
            ensure_stream_mode_supported(profile, d['node'])
        except Exception as e:
            self.errors[cid] = f'mode validation failed: {e}'
            log(f'{cid}: {self.errors[cid]}')
            return
        cmd, _, _ = streamer_command(profile, d['node']); logf = self.logfile(cid)
        with logf.open('ab', buffering=0) as lf:
            lf.write((f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} START {cid} =====\n"
                      f"device={d['node']} usb={d.get('usb_path')} vidpid={d.get('vid')}:{d.get('pid')}\ncmd={cmd!r}\n").encode())
            proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=lf, stderr=subprocess.STDOUT,
                                    close_fds=True, start_new_session=True)
        pidfile.write_text(str(proc.pid) + '\n'); self.processes[cid] = proc
        if not wait_port(port, 4): self.errors[cid] = f'streamer did not open port {port}'; log(f'{cid}: {self.errors[cid]}'); return
        try:
            # The Sonix SCCB bridge can transiently return garbage immediately
            # after UVC STREAMON. Give the selected mode a short settle window
            # before touching sensor registers.
            if str(profile.get('sensor_policy') or 'none') != 'none':
                time.sleep(0.75)
            sensor = apply_sensor_policy(profile, d['node'])
            if sensor:
                log(f'{cid}: sensor policy applied: {sensor}')
        except Exception as e:
            policy = str(profile.get('sensor_policy') or 'none')
            if policy == 'nebula_force_day':
                # Day-mode control is a watchdog policy, not a prerequisite for
                # video. Keep the stream alive and retry the XU control later.
                self.errors[cid] = f'day-mode watchdog warning: {e}'
                log(f'{cid}: {self.errors[cid]}')
            else:
                # OV3660 orientation is mandatory: a half-applied SCCB state can
                # leave a seemingly-live but unusable stream.
                self.errors[cid] = f'sensor policy failed: {e}'
                log(f'{cid}: {self.errors[cid]}')
                kill_pidfile(pidfile)
                self.processes.pop(cid, None)
                self.cpu_percent.pop(cid, None)
                self._cpu_prev.pop(cid, None)
                log(f'{cid}: start aborted after sensor policy failure; monitor will retry')
                return
        else:
            self.errors.pop(cid, None)
        log(f"{cid}: started pid={proc.pid} device={d['node']} port={port}")
    def enforce_periodic_sensor_policy(self, profile: dict[str, Any]) -> None:
        if str(profile.get('sensor_policy') or 'none') != 'nebula_force_day':
            return
        cid = profile['id']
        with self._ops_lock:
            cfg = load_config()
            self.refresh_devices(cfg)
            device = self._resolve_profile_device(profile)
            if not device:
                return
            try:
                result = apply_sensor_policy(profile, device['node'])
            except Exception as e:
                self.errors[cid] = f'day-mode watchdog warning: {e}'
                log(f'{cid}: {self.errors[cid]}')
                return
            if str(self.errors.get(cid, '')).startswith('day-mode watchdog warning:'):
                self.errors.pop(cid, None)
            output = str((result or {}).get('output') or '')
            if output.startswith('forced DAY'):
                log(f'{cid}: Nebula watchdog {output}')

    def stop_camera(self, cid: str) -> None:
        with self._ops_lock:
            kill_pidfile(self.pidfile(cid))
            self.processes.pop(cid, None)
            self.cpu_percent.pop(cid, None)
            self._cpu_prev.pop(cid, None)
            log(f'{cid}: stopped')
    def restart_camera(self, profile: dict[str, Any]) -> None:
        self.stop_camera(profile['id']); time.sleep(0.3); self.start_camera(profile, force=True)
    def start_all(self) -> None:
        cfg = load_config(); self.refresh_devices(cfg)
        for p in cfg.get('cameras', []):
            if p.get('enabled', True): self.start_camera(p, force=True)
    def stop_all(self) -> None:
        cfg = load_config()
        for p in cfg.get('cameras', []): self.stop_camera(p['id'])
    def sample_cpu(self) -> None:
        now = time.monotonic()
        for cid in [p['id'] for p in load_config().get('cameras', [])]:
            pid = read_pidfile(self.pidfile(cid))
            if not proc_alive(pid): self.cpu_percent[cid] = 0.0; self._cpu_prev.pop(cid, None); continue
            try:
                parts = Path(f'/proc/{pid}/stat').read_text().split(); ticks = int(parts[13]) + int(parts[14])
            except Exception: continue
            prev = self._cpu_prev.get(cid)
            self._cpu_prev[cid] = (pid, now, ticks)
            if prev:
                prev_pid, prev_time, prev_ticks = prev
                if pid != prev_pid or ticks < prev_ticks:
                    self.cpu_percent[cid] = 0.0
                elif now > prev_time:
                    value = ((ticks - prev_ticks) / CPU_CLK_TCK) / (now - prev_time) * 100.0
                    self.cpu_percent[cid] = round(max(0.0, value), 1)
    def status(self) -> dict[str, Any]:
        cfg = load_config(); all_devices = self.refresh_devices(cfg); cameras = []
        for p in cfg.get('cameras', []):
            cid = p['id']; pid = read_pidfile(self.pidfile(cid)); alive = proc_alive(pid); d = self.devices.get(cid)
            backend = p.get('backend', 'mjpg_streamer'); port = int(p.get('port', 8080))
            cameras.append({'profile': p, 'device': d, 'pid': pid if alive else 0,
                            'running': alive and port_open(port), 'cpu_percent': self.cpu_percent.get(cid, 0.0),
                            'error': self.errors.get(cid, ''),
                            'stream_path': '/?action=stream' if backend == 'mjpg_streamer' else '/stream',
                            'snapshot_path': '/?action=snapshot' if backend == 'mjpg_streamer' else '/snapshot'})
        mem = {}
        try:
            for line in Path('/proc/meminfo').read_text().splitlines():
                if ':' in line:
                    k, v = line.split(':', 1)
                    if k in ('MemTotal', 'MemAvailable'): mem[k] = int(v.strip().split()[0])
        except Exception: pass
        return {'version': APP_VERSION, 'base': str(BASE), 'loadavg': [round(x, 2) for x in os.getloadavg()],
                'cpu_count': NCPU, 'memory_kb': mem, 'devices': all_devices, 'cameras': cameras}

runtime = CameraRuntime()

def find_profile(cfg: dict[str, Any], cid: str) -> dict[str, Any]:
    for p in cfg.get('cameras', []):
        if p.get('id') == cid: return p
    raise KeyError(cid)

def sanitize_id(value: str) -> str:
    v = re.sub(r'[^a-zA-Z0-9_-]+', '-', value.strip()).strip('-').lower()
    if not v or len(v) > 40: raise ValueError('invalid id')
    return v

def validate_profile(p: dict[str, Any], all_cfg: dict[str, Any], previous_id: str | None = None) -> dict[str, Any]:
    p = json.loads(json.dumps(p)); p['id'] = sanitize_id(str(p.get('id', ''))); p['name'] = str(p.get('name') or p['id'])[:80]
    p['enabled'] = bool(p.get('enabled', True)); p['backend'] = str(p.get('backend', 'mjpg_streamer'))
    if p['backend'] not in ('mjpg_streamer', 'ustreamer'): raise ValueError('invalid backend')
    for k, lo, hi, default in (('port',1024,65535,8080),('width',160,7680,1280),('height',120,4320,720),('fps',1,120,30),('buffers',2,16,4)):
        v = int(p.get(k, default))
        if not lo <= v <= hi: raise ValueError(f'{k} out of range')
        p[k] = v
    p['format'] = normalize_format_name(str(p.get('format', 'MJPEG')))
    if p['backend'] == 'mjpg_streamer' and p['format'] not in ('MJPEG', 'YUYV'):
        raise ValueError('mjpg_streamer format must be MJPEG or YUYV')
    p['fluidd_service'] = str(p.get('fluidd_service') or 'mjpegstreamer')
    if p['fluidd_service'] not in FLUIDD_SERVICES:
        raise ValueError('invalid Fluidd stream type')
    p['sensor_policy'] = str(p.get('sensor_policy', 'none'))
    if p['sensor_policy'] == 'ov3660_qxga_rot180':
        p['sensor_policy'] = 'ov3660_rot180'
    if p['sensor_policy'] not in ('none', 'ov3660_rot180', 'nebula_force_day'): raise ValueError('invalid sensor_policy')
    m = p.get('match') or {}
    p['match'] = {'vid':str(m.get('vid') or '').lower(),'pid':str(m.get('pid') or '').lower(),'serial':str(m.get('serial') or ''),
                  'usb_path':str(m.get('usb_path') or ''),'name_contains':str(m.get('name_contains') or '')}
    for other in all_cfg.get('cameras', []):
        if other.get('id') == previous_id: continue
        if other.get('id') == p['id']: raise ValueError('duplicate id')
        if int(other.get('port', 0)) == p['port']: raise ValueError(f"port {p['port']} already used by {other.get('id')}")
    return p

class Handler(http.server.SimpleHTTPRequestHandler):
    server_version = 'AD5XCameraManager/0.1'
    def log_message(self, fmt: str, *args: Any) -> None:
        if args and str(args[0]).startswith(('4','5')): log('http: ' + (fmt % args))
    def _json(self, value: Any, code: int = 200) -> None:
        data = json.dumps(value, ensure_ascii=False).encode(); self.send_response(code)
        self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Cache-Control','no-store')
        self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)
    def _body_json(self) -> dict[str, Any]:
        n = int(self.headers.get('Content-Length','0') or '0')
        if n > 1_000_000: raise ValueError('request too large')
        return json.loads((self.rfile.read(n) if n else b'{}').decode('utf-8'))
    def do_GET(self) -> None:
        u = urllib.parse.urlparse(self.path)
        if u.path == '/api/status': return self._json(runtime.status())
        if u.path == '/api/log':
            q = urllib.parse.parse_qs(u.query); cid = sanitize_id((q.get('id') or [''])[0]); path = runtime.logfile(cid); text = ''
            if path.exists(): text = '\n'.join(path.read_text(encoding='utf-8', errors='replace').splitlines()[-250:])
            return self._json({'id':cid,'log':text})
        if u.path == '/api/formats':
            q = urllib.parse.parse_qs(u.query); node = (q.get('node') or [''])[0]
            if not re.fullmatch(r'/dev/video\d+', node): return self._json({'error':'invalid node'},400)
            try:
                return self._json(get_v4l2_modes(node))
            except Exception as e: return self._json({'error':str(e)},500)
        if u.path in ('/','/index.html'): self.path = '/index.html'
        return super().do_GET()
    def do_POST(self) -> None:
        try:
            body = self._body_json(); path = urllib.parse.urlparse(self.path).path; cfg = load_config()
            if path == '/api/camera/action':
                cid = sanitize_id(str(body.get('id',''))); action = str(body.get('action','')); p = find_profile(cfg,cid)
                if action == 'start': runtime.start_camera(p, force=True)
                elif action == 'stop': runtime.stop_camera(cid)
                elif action == 'restart': runtime.restart_camera(p)
                elif action == 'enable': p['enabled']=True; save_config(cfg); runtime.start_camera(p,force=True)
                elif action == 'disable': runtime.stop_camera(cid); p['enabled']=False; save_config(cfg)
                elif action == 'primary':
                    target_port = int(p.get('port',0))
                    if target_port != 8080:
                        current = next((x for x in cfg['cameras'] if int(x.get('port',0))==8080),None)
                        # Stop both before swapping ports so neither can block the other's new listen port.
                        if current: runtime.stop_camera(current['id'])
                        runtime.stop_camera(p['id'])
                        if current: current['port']=target_port
                        p['port']=8080; save_config(cfg)
                        if current and current.get('enabled', True): runtime.start_camera(current, force=True)
                        if p.get('enabled', True): runtime.start_camera(p, force=True)
                else: return self._json({'error':'invalid action'},400)
                return self._json({'ok':True,'status':runtime.status()})
            if path == '/api/profile/save':
                previous_id = body.get('previous_id'); profile = validate_profile(body.get('profile') or {},cfg,previous_id); replaced=False
                for i,old in enumerate(cfg['cameras']):
                    if old.get('id') == previous_id:
                        if old.get('id') != profile['id']: runtime.stop_camera(old['id'])
                        cfg['cameras'][i]=profile; replaced=True; break
                if not replaced: cfg['cameras'].append(profile)
                save_config(cfg)
                if profile.get('enabled'): runtime.restart_camera(profile)
                return self._json({'ok':True,'status':runtime.status()})
            if path == '/api/profile/add-device':
                node = str(body.get('node','')); devices = enumerate_devices(); d = next((x for x in devices if x['node']==node),None)
                if not d: return self._json({'error':'device not found'},404)
                existing_ports={int(x.get('port',0)) for x in cfg['cameras']}; port=8080
                while port in existing_ports: port+=1
                baseid=sanitize_id(str(d.get('product') or d.get('name') or Path(node).name)); cid=baseid; n=2; ids={x['id'] for x in cfg['cameras']}
                while cid in ids: cid=f'{baseid}-{n}'; n+=1
                p={'id':cid,'name':d.get('product') or d.get('name') or cid,'enabled':False,'backend':'mjpg_streamer','width':1280,'height':720,
                   'fps':30,'buffers':4,'format':'MJPEG','port':port,'sensor_policy':('nebula_force_day' if str(d.get('vid','')).lower()=='a108' and str(d.get('pid','')).lower()=='2231' else 'none'),'fluidd_service':'mjpegstreamer',
                   'match':{'vid':d.get('vid',''),'pid':d.get('pid',''),'serial':d.get('serial',''),'usb_path':d.get('usb_path',''),'name_contains':''}}
                cfg['cameras'].append(p); save_config(cfg); return self._json({'ok':True,'profile':p,'status':runtime.status()})
            if path == '/api/profile/delete':
                cid=sanitize_id(str(body.get('id',''))); runtime.stop_camera(cid); cfg['cameras']=[x for x in cfg['cameras'] if x.get('id')!=cid]; save_config(cfg)
                return self._json({'ok':True,'status':runtime.status()})
            if path == '/api/probe':
                cid=sanitize_id(str(body.get('id',''))); p=find_profile(cfg,cid)
                result=stream_probe(int(p['port']),p.get('backend','mjpg_streamer'),float(body.get('seconds',3)))
                return self._json({'ok':True,'result':result})
            if path == '/api/fluidd/sync':
                cid=sanitize_id(str(body.get('id',''))); p=find_profile(cfg,cid)
                result=sync_fluidd_webcam(p, str(body.get('host','')))
                return self._json({'ok':True,'result':result})
            if path == '/api/fluidd/sync-ui':
                result=sync_fluidd_ui(str(body.get('host','')))
                return self._json({'ok':True,'result':result})
            if path == '/api/rescan': return self._json({'ok':True,'status':runtime.status()})
            return self._json({'error':'not found'},404)
        except KeyError: return self._json({'error':'camera not found'},404)
        except Exception as e: log(f'api error: {e}'); return self._json({'error':str(e)},500)

def monitor_loop() -> None:
    next_scan=0.0
    next_policy=0.0
    while not _shutdown.wait(1.0):
        try:
            runtime.sample_cpu(); now=time.monotonic()
            if now >= next_scan:
                next_scan=now+5.0; cfg=load_config(); runtime.refresh_devices(cfg)
                for p in cfg.get('cameras',[]):
                    if not p.get('enabled',True): continue
                    cid=p['id']; pid=read_pidfile(runtime.pidfile(cid))
                    if not proc_alive(pid) or not port_open(int(p.get('port',8080))): runtime.start_camera(p)
            if now >= next_policy:
                next_policy=now+60.0; cfg=load_config()
                for p in cfg.get('cameras',[]):
                    if not p.get('enabled',True): continue
                    if str(p.get('sensor_policy') or 'none') == 'nebula_force_day':
                        runtime.enforce_periodic_sensor_policy(p)
        except Exception as e: log(f'monitor warning: {e}')

def camera_bootstrap_loop() -> None:
    log('camera bootstrap started')
    try:
        runtime.start_all()
    except Exception as e:
        log(f'camera bootstrap warning: {e}')
    finally:
        log('camera bootstrap finished')
        if not _shutdown.is_set():
            threading.Thread(target=monitor_loop, name='camera-monitor', daemon=True).start()


def run_server() -> None:
    ensure_dirs()
    cfg = load_config()
    listen = cfg.get('listen') or {}
    host = str(listen.get('host') or DEFAULT_LISTEN)
    port = int(listen.get('port') or DEFAULT_PORT)

    # Control plane must be available independently of camera/XU startup.
    # In 0.1.3 start_all() ran synchronously before HTTP bind, so a slow
    # OV3660 helper retry made the installer think the manager was dead.
    os.chdir(WEB_DIR)
    server = http.server.ThreadingHTTPServer((host, port), Handler)
    MANAGER_PID.write_text(str(os.getpid()) + '\n')

    def sig(_signum: int, _frame: Any) -> None:
        _shutdown.set()
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, sig)
    signal.signal(signal.SIGINT, sig)

    log(f'manager control plane started pid={os.getpid()} http={host}:{port}')
    threading.Thread(
        target=camera_bootstrap_loop,
        name='camera-bootstrap',
        daemon=True,
    ).start()

    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        _shutdown.set()
        runtime.stop_all()
        MANAGER_PID.unlink(missing_ok=True)
        log('manager stopped')

def main() -> int:
    ap=argparse.ArgumentParser(); sub=ap.add_subparsers(dest='command'); sub.add_parser('serve'); sub.add_parser('validate'); ss=sub.add_parser('sensor-status'); ss.add_argument('id'); args=ap.parse_args()
    if args.command in (None,'serve'): run_server(); return 0
    if args.command=='validate': print(json.dumps(runtime.status(),ensure_ascii=False,indent=2)); return 0
    if args.command=='sensor-status':
        cfg = load_config()
        runtime.refresh_devices(cfg)
        d = runtime.devices.get(args.id)
        if not d:
            raise RuntimeError('device not found')
        helper = BASE / 'drivers' / 'ov3660_orientation.py'
        cp = subprocess.run(
            [sys.executable, str(helper), d['node'], 'status'],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=8,
            close_fds=True,
        )
        if cp.stdout:
            print(cp.stdout, end='' if cp.stdout.endswith('\n') else '\n')
        return cp.returncode
    return 2

if __name__=='__main__': raise SystemExit(main())
