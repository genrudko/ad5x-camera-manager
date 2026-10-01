from pathlib import Path
root=Path(__file__).resolve().parents[1]
app=(root/'app.py').read_text()
js=(root/'web/app.js').read_text()
html=(root/'web/index.html').read_text()
kl=(root/'ad5x_camera_manager.cfg').read_text()
sh=(root/'camera-manager.sh').read_text()
assert "APP_VERSION = '0.1.9-beta'" in app
assert "FLUIDD_SERVICES = ('mjpegstreamer', 'mjpegstreamer-adaptive', 'uv4l-mjpeg')" in app
assert "profile.get('fluidd_service')" in app
assert "'service': 'iframe'" in app
assert '/api/fluidd/sync-ui' in app
assert 'id="f-fluidd-service"' in html
assert 'mjpegstreamer-adaptive' in html and 'uv4l-mjpeg' in html
assert "$('#fluidd-ui').onclick" in js
assert 'CAMERA_MANAGER_UI' in kl
assert 'api_post /api/fluidd/sync-ui' in sh
print('0.1.6 static integration checks: PASS')
