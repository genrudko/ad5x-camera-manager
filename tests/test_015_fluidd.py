import importlib.util
from pathlib import Path
root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('cm_app',root/'app.py')
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
calls=[]
def fake(method,path,payload=None):
    calls.append((method,path,payload))
    if method=='GET': return {'webcams':[]}
    return {'webcam':{'uid':'u1',**payload}}
mod.moonraker_request=fake
p={'id':'cam2','name':'CCX2F3298','backend':'mjpg_streamer','port':8081,'width':1920,'height':1080,'fps':25,'enabled':True}
r=mod.sync_fluidd_webcam(p,'192.168.1.10')
assert r['created'] is True
payload=calls[-1][2]
assert payload['stream_url']=='http://192.168.1.10:8081/?action=stream'
assert payload['snapshot_url']=='http://192.168.1.10:8081/?action=snapshot'
assert payload['aspect_ratio']=='16:9'
assert payload['target_fps']==25
assert payload['extra_data']['ad5x_camera_manager_id']=='cam2'
print('0.1.5 Fluidd/Moonraker sync payload tests: PASS')
