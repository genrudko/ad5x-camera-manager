const $ = s => document.querySelector(s);
let STATUS = null;
let HIDDEN_PREVIEWS = new Set();
let LANG = localStorage.getItem('cm_lang') || 'ru';
let EDITOR_MODES = [];
let EDITOR_PROFILE = null;

const I = {
  ru: {
    rescan:'Обновить', cameras:'Камеры', devices:'Обнаруженные UVC-устройства', system:'Система',
    cpu_note:'Видео идёт напрямую от streamer к браузеру; Camera Manager кадры не проксирует.',
    enabled:'Включена', delete:'Удалить', cancel:'Отмена', save:'Сохранить и применить', match:'Привязка устройства',
    edit:'Настроить', preview:'Показать видео', stop_preview:'Скрыть видео', restart:'Перезапустить', start:'Включить', stop:'Выключить',
    primary:'Сделать основной', primary_now:'Основная', probe:'Измерить FPS', snapshot:'Снимок', modes:'Режимы', log:'Лог', add:'Добавить',
    running:'Работает', stopped:'Остановлена', missing:'Устройство не найдено', no_devices:'Новых capture-устройств нет',
    name:'Название', backend:'Backend', port:'Порт', resolution:'Разрешение', format:'Формат', sensor_policy:'Ориентация / sensor policy',
    loading_modes:'Читаю поддерживаемые режимы…', modes_loaded:'Режимы загружены с', modes_unavailable:'Режимы недоступны; показана текущая конфигурация',
    live:'Живое видео', fluidd:'Во Fluidd', fluidd_ok:'Камера добавлена/обновлена в Moonraker/Fluidd', fluidd_type:'Тип потока во Fluidd', fluidd_ui:'Интерфейс Camera Manager во Fluidd', fluidd_ui_ok:'Интерфейс Camera Manager добавлен/обновлён во Fluidd'
  },
  en: {
    rescan:'Rescan', cameras:'Cameras', devices:'Detected UVC devices', system:'System',
    cpu_note:'Video goes directly from each streamer to the browser; Camera Manager does not proxy frames.',
    enabled:'Enabled', delete:'Delete', cancel:'Cancel', save:'Save & apply', match:'Device binding',
    edit:'Settings', preview:'Show video', stop_preview:'Hide video', restart:'Restart', start:'Enable', stop:'Disable',
    primary:'Make primary', primary_now:'Primary', probe:'Measure FPS', snapshot:'Snapshot', modes:'Modes', log:'Log', add:'Add',
    running:'Running', stopped:'Stopped', missing:'Device not found', no_devices:'No unassigned capture devices',
    name:'Name', backend:'Backend', port:'Port', resolution:'Resolution', format:'Format', sensor_policy:'Orientation / sensor policy',
    loading_modes:'Reading supported modes…', modes_loaded:'Modes loaded from', modes_unavailable:'Modes unavailable; showing current configuration',
    live:'Live video', fluidd:'Sync Fluidd', fluidd_ok:'Camera added/updated in Moonraker/Fluidd', fluidd_type:'Fluidd stream type', fluidd_ui:'Camera Manager UI in Fluidd', fluidd_ui_ok:'Camera Manager UI added/updated in Fluidd'
  }
};
const t = k => I[LANG][k] || k;
function esc(s){return String(s ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
async function api(path, body){
  const o={cache:'no-store'};
  if(body!==undefined){o.method='POST';o.headers={'Content-Type':'application/json'};o.body=JSON.stringify(body)}
  const r=await fetch(path,o); const j=await r.json(); if(!r.ok)throw new Error(j.error||r.statusText); return j;
}
function hostUrl(port,path){return `${location.protocol}//${location.hostname}:${port}${path}`}
function applyLang(){
  document.documentElement.lang=LANG; $('#lang').value=LANG;
  document.querySelectorAll('[data-i18n]').forEach(e=>e.textContent=t(e.dataset.i18n));
}
async function refresh(){try{STATUS=await api('/api/status');render()}catch(e){$('#summary').textContent='ERROR: '+e.message}}

function render(){
  applyLang();
  const s=STATUS; const ma=s.memory_kb||{}; const mem=ma.MemTotal?Math.round((1-ma.MemAvailable/ma.MemTotal)*100):'?';
  $('#summary').textContent=`v${s.version} · load ${s.loadavg[0]} / ${s.cpu_count} · RAM ${mem}%`;
  $('#system').innerHTML=`<div class="kv"><span>Load <b>${s.loadavg.join(' / ')}</b></span><span>CPU <b>${s.cpu_count}</b></span><span>RAM <b>${mem}%</b></span><span>UI <b>:8095</b></span></div>`;
  const list=$('#camera-list'); list.innerHTML='';
  for(const c of s.cameras){
    const p=c.profile,d=c.device;
    const state=!p.enabled?['off',t('stopped')]:c.running?['good',t('running')]:['bad',d?t('stopped'):t('missing')];
    const isPrimary=Number(p.port)===8080;
    const showPreview=c.running&&!HIDDEN_PREVIEWS.has(p.id);
    const el=document.createElement('div'); el.className='card';
    el.innerHTML=`
      <div class="card-head"><div><div class="title">${esc(p.name)}</div><div class="muted">${esc(p.id)}</div></div><span class="badge ${state[0]}">${state[1]}</span></div>
      ${c.running?`<div class="preview-shell ${showPreview?'on':''}"><div class="preview-label">● ${t('live')} · :${p.port}</div><img class="preview" alt="camera preview" style="aspect-ratio:${Number(p.width)||4}/${Number(p.height)||3}"></div>`:''}
      <div class="meta"><span>Device <b>${esc(d?.node||'—')}</b></span><span>USB <b>${esc(d?.usb_path||p.match?.usb_path||'—')}</b></span><span>Mode <b>${p.width}×${p.height} / ${p.fps} req</b></span><span>Buffers <b>${p.buffers}</b></span><span>Backend <b>${esc(p.backend)}</b></span><span>Fluidd <b>${esc(p.fluidd_service||'mjpegstreamer')}</b></span><span>Port <b>${p.port}${isPrimary?' · '+t('primary_now'):''}</b></span><span>CPU streamer <b id="cpu-${esc(p.id)}">${c.cpu_percent}%</b></span><span>VID:PID <b>${esc(d?.vid||p.match?.vid)}:${esc(d?.pid||p.match?.pid)}</b></span></div>
      ${c.error?`<div class="error">${esc(c.error)}</div>`:''}
      <div class="actions">${c.running?`<button data-a="preview">${showPreview?t('stop_preview'):t('preview')}</button>`:''}<button data-a="edit">${t('edit')}</button><button data-a="restart">${t('restart')}</button><button data-a="${p.enabled?'disable':'enable'}">${p.enabled?t('stop'):t('start')}</button>${isPrimary?'':`<button data-a="primary">${t('primary')}</button>`}<button data-a="probe">${t('probe')}</button><button data-a="snapshot">${t('snapshot')}</button><button data-a="modes">${t('modes')}</button><button data-a="fluidd">${t('fluidd')}</button><button data-a="log">${t('log')}</button></div>
      <div class="muted probe-result"></div>`;
    el.querySelectorAll('button').forEach(b=>b.onclick=()=>cardAction(c,b.dataset.a,el,b));
    list.appendChild(el);
    if(showPreview){const img=el.querySelector('.preview'); img.src=hostUrl(p.port,c.stream_path)}
  }
  renderDevices();
}

async function cardAction(c,a,el,b){
  const p=c.profile;
  try{
    if(a==='preview'){
      if(HIDDEN_PREVIEWS.has(p.id)) HIDDEN_PREVIEWS.delete(p.id); else HIDDEN_PREVIEWS.add(p.id);
      render(); return;
    }
    if(a==='edit'){await openEditor(p);return}
    if(a==='snapshot'){const sep=c.snapshot_path.includes('?')?'&':'?';window.open(hostUrl(p.port,c.snapshot_path)+sep+'t='+Date.now(),'_blank');return}
    if(a==='modes'){
      if(!c.device?.node){alert(t('missing'));return}
      const j=await api('/api/formats?node='+encodeURIComponent(c.device.node)); $('#log-text').textContent=j.text||j.error||'(empty)'; $('#log-dialog').showModal(); return;
    }
    if(a==='log'){const j=await api('/api/log?id='+encodeURIComponent(p.id));$('#log-text').textContent=j.log||'(empty)';$('#log-dialog').showModal();return}
    if(a==='fluidd'){b.disabled=true;const j=await api('/api/fluidd/sync',{id:p.id,host:location.hostname});b.disabled=false;alert(`${t('fluidd_ok')}\n${j.result.webcam?.name||p.name}`);return}
    if(a==='probe'){b.disabled=true;b.textContent='…';const j=await api('/api/probe',{id:p.id,seconds:3});el.querySelector('.probe-result').textContent=`${j.result.fps} fps · ${j.result.mbit_s} Mbit/s · ${j.result.frames} frames`;b.disabled=false;b.textContent=t('probe');return}
    const j=await api('/api/camera/action',{id:p.id,action:a});STATUS=j.status;render();
  }catch(e){alert(e.message);if(b)b.disabled=false}
}

function assignedNodes(){return new Set((STATUS.cameras||[]).map(c=>c.device?.node).filter(Boolean))}
function renderDevices(){
  const box=$('#device-list');box.innerHTML='';const used=assignedNodes();const devices=(STATUS.devices||[]).filter(d=>!used.has(d.node));
  if(!devices.length){box.innerHTML=`<div class="muted">${t('no_devices')}</div>`;return}
  for(const d of devices){
    const el=document.createElement('div');el.className='device';
    el.innerHTML=`<div><b>${esc(d.name)}</b> · ${esc(d.node)}<br><small>${esc(d.manufacturer)} ${esc(d.product)} · ${esc(d.vid)}:${esc(d.pid)} · USB ${esc(d.usb_path)}</small></div><button>${t('add')}</button>`;
    el.querySelector('button').onclick=async()=>{try{const j=await api('/api/profile/add-device',{node:d.node});STATUS=j.status;render();await openEditor(j.profile)}catch(e){alert(e.message)}};
    box.appendChild(el);
  }
}

function currentCameraForProfile(p){return (STATUS?.cameras||[]).find(c=>c.profile?.id===p.id)}
function supportedEditorModes(){return (EDITOR_MODES||[]).filter(m=>['MJPEG','YUYV'].includes(m.format))}
function option(select,value,label){const o=document.createElement('option');o.value=String(value);o.textContent=label??String(value);select.appendChild(o)}

function populateFormats(preferred){
  const select=$('#f-format'); select.innerHTML='';
  const formats=[...new Set(supportedEditorModes().map(m=>m.format))];
  if(!formats.length) formats.push(preferred||'MJPEG');
  if(preferred&&!formats.includes(preferred)) formats.push(preferred);
  for(const f of formats) option(select,f,f);
  select.value=formats.includes(preferred)?preferred:formats[0];
  populateResolutions(`${EDITOR_PROFILE?.width||1280}x${EDITOR_PROFILE?.height||720}`);
}
function populateResolutions(preferred){
  const select=$('#f-resolution'); select.innerHTML=''; const fmt=$('#f-format').value;
  const modes=supportedEditorModes().filter(m=>m.format===fmt);
  const values=[];
  for(const m of modes){const v=`${m.width}x${m.height}`;if(!values.includes(v))values.push(v)}
  if(!values.length) values.push(preferred);
  if(preferred&&!values.includes(preferred)) values.push(preferred);
  for(const v of values) option(select,v,v);
  select.value=values.includes(preferred)?preferred:values[0];
  populateFps(Number(EDITOR_PROFILE?.fps||30));
}
function populateFps(preferred){
  const select=$('#f-fps'); select.innerHTML=''; const fmt=$('#f-format').value; const [w,h]=$('#f-resolution').value.split('x').map(Number);
  const mode=supportedEditorModes().find(m=>m.format===fmt&&m.width===w&&m.height===h);
  const values=(mode?.fps||[]).map(Number);
  if(!values.length) values.push(preferred||30);
  if(preferred&&!values.some(x=>Math.abs(x-preferred)<0.05)) values.push(preferred);
  values.sort((a,b)=>b-a);
  for(const v of values) option(select,v,Number.isInteger(v)?String(v):String(v));
  const closest=values.find(x=>Math.abs(x-preferred)<0.05)??values[0]; select.value=String(closest);
}

async function openEditor(p){
  EDITOR_PROFILE=JSON.parse(JSON.stringify(p)); EDITOR_MODES=[];
  $('#previous-id').value=p.id||''; $('#f-id').value=p.id||''; $('#f-name').value=p.name||''; $('#f-backend').value=p.backend||'mjpg_streamer'; $('#f-port').value=p.port||8080;
  $('#f-buffers').value=p.buffers||4; $('#f-fluidd-service').value=p.fluidd_service||'mjpegstreamer'; $('#f-policy').value=(p.sensor_policy==='ov3660_qxga_rot180'?'ov3660_rot180':(p.sensor_policy||'none'));
  $('#f-vid').value=p.match?.vid||''; $('#f-pid').value=p.match?.pid||''; $('#f-usb').value=p.match?.usb_path||''; $('#f-serial').value=p.match?.serial||''; $('#f-enabled').checked=!!p.enabled;
  $('#delete-btn').style.visibility=p.id?'visible':'hidden'; $('#editor-title').textContent=p.name||'Camera'; $('#mode-source').textContent=t('loading_modes');
  populateFormats(p.format||'MJPEG'); $('#editor').showModal();
  const c=currentCameraForProfile(p);
  if(!c?.device?.node){$('#mode-source').textContent=t('modes_unavailable');return}
  try{
    const j=await api('/api/formats?node='+encodeURIComponent(c.device.node)); EDITOR_MODES=j.modes||[];
    populateFormats(p.format||'MJPEG'); $('#mode-source').textContent=`${t('modes_loaded')} ${c.device.node}`;
  }catch(e){$('#mode-source').textContent=`${t('modes_unavailable')}: ${e.message}`}
}

function editorProfile(){
  const [width,height]=$('#f-resolution').value.split('x').map(Number);
  return {id:$('#f-id').value,name:$('#f-name').value,backend:$('#f-backend').value,port:Number($('#f-port').value),width,height,fps:Number($('#f-fps').value),buffers:Number($('#f-buffers').value),format:$('#f-format').value,fluidd_service:$('#f-fluidd-service').value,sensor_policy:$('#f-policy').value,enabled:$('#f-enabled').checked,match:{vid:$('#f-vid').value,pid:$('#f-pid').value,usb_path:$('#f-usb').value,serial:$('#f-serial').value,name_contains:''}};
}

$('#f-format').onchange=()=>populateResolutions($('#f-resolution').value||`${EDITOR_PROFILE?.width||1280}x${EDITOR_PROFILE?.height||720}`);
$('#f-resolution').onchange=()=>populateFps(Number(EDITOR_PROFILE?.fps||30));
$('#save-btn').onclick=async()=>{try{const j=await api('/api/profile/save',{previous_id:$('#previous-id').value,profile:editorProfile()});STATUS=j.status;$('#editor').close();render()}catch(e){alert(e.message)}};
$('#delete-btn').onclick=async()=>{const id=$('#previous-id').value;if(!id||!confirm('Delete '+id+'?'))return;try{const j=await api('/api/profile/delete',{id});STATUS=j.status;$('#editor').close();render()}catch(e){alert(e.message)}};
$('#rescan').onclick=refresh;
$('#fluidd-ui').onclick=async()=>{const b=$('#fluidd-ui');try{b.disabled=true;const j=await api('/api/fluidd/sync-ui',{host:location.hostname});alert(`${t('fluidd_ui_ok')}\n${j.result.webcam?.name||'AD5X Camera Manager UI'}`)}catch(e){alert(e.message)}finally{b.disabled=false}};
$('#lang').onchange=e=>{LANG=e.target.value;localStorage.setItem('cm_lang',LANG);render()};
function topologyKey(s){return JSON.stringify((s?.cameras||[]).map(c=>[c.profile.id,c.running,c.profile.port,c.profile.width,c.profile.height,c.profile.fluidd_service,c.error,c.device?.node||'']))}
function updateLiveStats(){
  if(!STATUS)return; const ma=STATUS.memory_kb||{}; const mem=ma.MemTotal?Math.round((1-ma.MemAvailable/ma.MemTotal)*100):'?';
  $('#summary').textContent=`v${STATUS.version} · load ${STATUS.loadavg[0]} / ${STATUS.cpu_count} · RAM ${mem}%`;
  $('#system').innerHTML=`<div class="kv"><span>Load <b>${STATUS.loadavg.join(' / ')}</b></span><span>CPU <b>${STATUS.cpu_count}</b></span><span>RAM <b>${mem}%</b></span><span>UI <b>:8095</b></span></div>`;
  for(const c of STATUS.cameras||[]){const n=document.getElementById(`cpu-${c.profile.id}`);if(n)n.textContent=`${c.cpu_percent}%`}
}
async function backgroundRefresh(){
  if($('#editor').open)return;
  try{const next=await api('/api/status');const changed=topologyKey(next)!==topologyKey(STATUS);STATUS=next;if(changed)render();else updateLiveStats()}catch(_e){}
}
applyLang(); refresh(); setInterval(backgroundRefresh,5000);
