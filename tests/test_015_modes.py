import importlib.util
from pathlib import Path
root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('cm_app', root / 'app.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

sample = r'''ioctl: VIDIOC_ENUM_FMT
        Type: Video Capture
        [0]: 'MJPG' (Motion-JPEG, compressed)
                Size: Discrete 1920x1080
                        Interval: Discrete 0.033s (30.000 fps)
                        Interval: Discrete 0.040s (25.000 fps)
                Size: Discrete 1280x720
                        Interval: Discrete 0.067s (15.000 fps)
        [1]: 'YUYV' (YUYV 4:2:2)
                Size: Discrete 640x480
                        Interval: Discrete 0.033s (30.000 fps)
'''
modes = mod.parse_v4l2_modes(sample)
assert modes == [
    {'format':'MJPEG','width':1920,'height':1080,'fps':[30,25]},
    {'format':'MJPEG','width':1280,'height':720,'fps':[15]},
    {'format':'YUYV','width':640,'height':480,'fps':[30]},
]

cfg={'cameras':[]}
p=mod.validate_profile({
    'id':'cam','name':'Cam','backend':'mjpg_streamer','port':8081,
    'width':1920,'height':1080,'fps':25,'buffers':4,'format':'MJPG',
    'sensor_policy':'ov3660_qxga_rot180','enabled':True,'match':{}
},cfg)
assert p['format']=='MJPEG'
assert p['sensor_policy']=='ov3660_rot180'

try:
    mod.validate_profile({
        'id':'bad','backend':'mjpg_streamer','port':8081,'width':1920,'height':1080,
        'fps':25,'buffers':4,'format':'H264','sensor_policy':'none','match':{}
    },cfg)
except ValueError as e:
    assert 'MJPEG or YUYV' in str(e)
else:
    raise AssertionError('H264 must be rejected for mjpg_streamer')
print('0.1.5 mode parser/profile tests: PASS')
