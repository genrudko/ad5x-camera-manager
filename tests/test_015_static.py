from pathlib import Path
root = Path(__file__).resolve().parents[1]
app = (root / 'app.py').read_text(encoding='utf-8')
helper = (root / 'drivers' / 'ov3660_orientation.py').read_text(encoding='utf-8')
js = (root / 'web' / 'app.js').read_text(encoding='utf-8')
html = (root / 'web' / 'index.html').read_text(encoding='utf-8')

a = app
assert "APP_VERSION = '0.1.9-beta'" in a
assert 'parse_v4l2_modes' in a and 'ensure_stream_mode_supported' in a
assert "policy in ('ov3660_rot180', 'ov3660_qxga_rot180')" in a
assert "p['sensor_policy'] = 'ov3660_rot180'" in a
assert "mjpg_streamer format must be MJPEG or YUYV" in a
assert 'camera is not in 2048x1536 QXGA mode' not in helper
assert 's["inc"] != 0x1111' not in helper
assert 'target20 = before["r3820"] & ~0x06' in helper
assert 'target21 = before["r3821"] | 0x06' in helper
assert 'target4514 = 0xBB' in helper
assert 'id="f-resolution"' in html
assert 'id="f-width"' not in html and 'id="f-height"' not in html
assert 'ov3660_rot180' in html
assert 'preview-shell' in js and 'HIDDEN_PREVIEWS' in js
assert "api('/api/formats?node='" in js
print('0.1.6 mode-aware UI/orientation regression checks: PASS')
assert '/api/fluidd/sync' in app
assert '/server/webcams/item' in app
assert 'Sync Fluidd' in js
