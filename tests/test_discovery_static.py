from pathlib import Path
text=(Path(__file__).resolve().parents[1]/"app.py").read_text()
block=text.split("def query_v4l2",1)[1].split("def usb_identity_for_video",1)[0]
assert "fcntl.ioctl(" not in block
assert "VIDIOC_QUERYCAP," not in block
assert "'probe': 'sysfs'" in block
assert "if fmt in ('YUYV', 'YUY2'): input_args += ' -y'" in text
assert "if fmt in ('MJPEG', 'JPEG'): input_args += ' -y'" not in text
print("static discovery/format checks: PASS")
