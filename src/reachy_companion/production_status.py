"""Bounded, content-free inventory of the installed three-host deployment."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import inspect
from pathlib import Path
import shlex
import subprocess
from urllib.request import Request, urlopen
from .private_audio_trace import project_summary
from .autonomous.stock_diagnostics import project as project_stock_diagnostics
from .autonomous.terminal_drain import project as project_terminal_drain
from .lease_diagnostics import project_first_lease_invalid,project_lease_withdrawal_reason,project_first_reducer_expiry

HOSTS = {
    'hub': ('reachy-hub', '/home/deploy/reachy-companion',
            ('reachy-hub', 'reachy-voice', 'reachy-robot-tunnel', 'reachy-production', 'reachy-report-retention.timer')),
    'robot': ('reachy-mini', '/home/pollen/reachy-companion',
              ('reachy-mini-daemon', 'reachy-voice-agent', 'reachy-production-audio', 'reachy-companion-firewall', 'reachy-report-retention.timer')),
}
PORTS = {'llm': 18097, 'router': 18098, 'worker': 8082, 'gateway': 8097, 'vlm':18099}
# Self-contained so a stopped, old or broken installation can still be inspected.
REMOTE_PROBE = inspect.getsource(project_terminal_drain).replace('def project(', 'def project_terminal_drain(') + inspect.getsource(project_stock_diagnostics).replace('def project(', 'def project_stock_diagnostics(') + inspect.getsource(project_first_lease_invalid) + inspect.getsource(project_lease_withdrawal_reason) + inspect.getsource(project_first_reducer_expiry) + inspect.getsource(project_summary) + r'''
import json,pathlib,shutil,subprocess,sys,urllib.request
root=pathlib.Path(sys.argv[1]); role=sys.argv[2]; names=sys.argv[3:]
def command(args):
 try:return subprocess.run(args,capture_output=True,text=True,timeout=3)
 except (OSError,subprocess.TimeoutExpired):return None
result={'reachable':True,'services':{}}
for name in names:
 p=command(['systemctl','is-active',name]);result['services'][name]=p.stdout.strip() if p else 'unknown'
u=shutil.disk_usage(root);result['disk']={'used_percent':round(u.used/(u.used+u.free)*100,1),'free_bytes':u.free}
reports=sorted(root.glob('data/production-*/'+('hub.json' if role=='hub' else 'device.json')),key=lambda p:p.stat().st_mtime,reverse=True)
result['last_session']=None
for p in reports[:3]:
 try:
  if p.stat().st_size>8*1024*1024:continue
  d=json.loads(p.read_text());result['last_session']={k:d.get(k) for k in ('reason','failure_code','errors','accepted','cleanup_verified','cleanup_issues','elapsed_s','peer_close_reason','cleanup_error')}
  result['last_session']['stock_diagnostics']=project_stock_diagnostics((d.get('motion_after') or {}).get('stock_diagnostics'))
  result['last_session']['terminal_drain']=project_terminal_drain(d.get('terminal_drain'))
  result['last_session']['private_audio_trace']=project_summary(d.get('private_audio_trace'))
  result['last_session']['first_reducer_expiry']=project_first_reducer_expiry(d.get('first_reducer_expiry'))
  result['last_session']['first_lease_invalid']=project_first_lease_invalid(d.get('first_lease_invalid'))
  result['last_session']['lease_withdrawal_reason']=project_lease_withdrawal_reason(d.get('lease',{}).get('withdrawal_reason')) if isinstance(d.get('lease'),dict) else None
  result['last_session']['finished_at']=p.stat().st_mtime
  break
 except (OSError,ValueError):pass
result['session']={'stage':'unavailable','listening_ready':False}
if role=='hub':
 try:
  c=json.loads((root/'config.local.json').read_text());p=pathlib.Path(c['paths']['token_file']);p=p if p.is_absolute() else root/p
  q=urllib.request.Request('http://127.0.0.1:8791/status',headers={'Authorization':'Bearer '+p.read_text().strip()})
  with urllib.request.urlopen(q,timeout=2) as response:raw=response.read(262145)
  if len(raw)>262144:raise ValueError('status bound')
  d=json.loads(raw)
  result['session']={k:d.get(k) for k in ('stage','reason','failure_code','elapsed_s','listening_ready','counts','audio','lease','peer_poll','background','cycle_phase','runtime','execution_busy','cleanup_verified')}
  result['session']['first_reducer_expiry']=project_first_reducer_expiry(d.get('first_reducer_expiry'))
  result['session']['terminal_drain']=project_terminal_drain(d.get('terminal_drain'))
  if isinstance(result['session'].get('lease'),dict):result['session']['lease']['first_reducer_expiry']=project_first_reducer_expiry(result['session']['lease'].get('first_reducer_expiry'))
  result['session']['first_lease_invalid']=project_first_lease_invalid(d.get('first_lease_invalid'))
  result['session']['speech']={k:d.get('speech',{}).get(k) for k in ('quarantined','terminal_unknown','stop_known','execution_busy','operator_receipt_fresh')}
  motion=d.get('motion') or {}
  result['session']['stock_diagnostics']=project_stock_diagnostics(motion.get('stock_diagnostics'))
  result['session']['motion']={k:motion.get(k) for k in ('allowed','execution_busy','stop_known','hard_stop_certified','tracking_enabled','tracking_mode','tracking_error')}
 except Exception as exc:result['session']['error_class']=type(exc).__name__
 try:
  c=json.loads((root/'config.autonomous.mac.local.json').read_text());p=c.get('production',{})
  result['capabilities']={'camera':bool(c.get('context',{}).get('enabled') or 'camera' in p.get('sensors',{})),'motion':bool(c.get('motion',{}).get('enabled')),'actuators':c.get('actuators'),'sensors':sorted(p.get('sensors',{})),'tools':sorted(p.get('tools',{})),'export':c.get('export_enabled',False)}
 except Exception:result['capabilities']={}
if role=='robot':
 result['motor_mode']='unknown'
 try:
  with urllib.request.urlopen('http://127.0.0.1:8000/api/state/full',timeout=2) as response:d=json.load(response)
  mode=d.get('control_mode')
  if mode in ('enabled','disabled','gravity_compensation'):result['motor_mode']=mode
 except Exception as exc:result['motor_error_class']=type(exc).__name__
 p=command(['sudo','-n','nft','list','chain','inet','reachy_companion','input'])
 rules=[line.strip() for line in p.stdout.splitlines() if ' saddr ' in line and ' accept' in line] if p and p.returncode==0 else None
 result['firewall']={'inspected':rules is not None,'duplicate_rules':len(rules)-len(set(rules)) if rules is not None else None}
print(json.dumps(result))
'''


def probe_host(role):
    host, root, services = HOSTS[role]
    try:
        result = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5',
                                 '-o', 'ServerAliveInterval=3', '-o', 'ServerAliveCountMax=1',
                                 host, 'python3 -c '+shlex.quote(REMOTE_PROBE)+' '+shlex.join([root, role, *services])],
                                capture_output=True, text=True, timeout=25)
        if result.returncode:return dict(reachable=False, error_class='SSHFailed')
        if len(result.stdout)>300000:raise ValueError('Probe response bound')
        value=json.loads(result.stdout)
        if not isinstance(value,dict) or value.get('reachable') is not True:raise ValueError('Probe contract')
        if role=='hub':normalize_tracking(value.get('session',{}))
        return value
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return dict(reachable=False, error_class=type(exc).__name__)


def normalize_tracking(session):
    """A retained planner mode is not evidence of an active tracking session."""
    motion=session.get('motion') or {}
    if motion.get('tracking_enabled') and (session.get('stage')!='ACTIVE' or session.get('lease',{}).get('withdrawn')):
        motion['last_tracking_mode']=motion.get('tracking_mode')
        motion['tracking_mode']='suspended'
        motion['tracking_error']='lease_withdrawn' if session.get('lease',{}).get('withdrawn') else 'session_'+str(session.get('stage','unavailable')).lower()
    return session


def probe_model(root, name):
    try:
        headers={}
        if name=='gateway':headers['Authorization']='Bearer '+(root/'secrets/autonomous-mac.token').read_text().strip()
        with urlopen(Request(f'http://127.0.0.1:{PORTS[name]}/health',headers=headers),timeout=2) as response:
            raw=response.read(65537)
        if len(raw)>65536:raise ValueError('Health response bound')
        d=json.loads(raw)
        return dict(ready=d.get('status')=='ok' or d.get('ok') is True or d.get('role')=='pc_gateway',
                    quarantined=bool(d.get('quarantined',False)),**({'vision':d['vision']} if 'vision' in d else {}))
    except (OSError, ValueError) as exc:return dict(ready=False,error_class=type(exc).__name__)


def summarize(models, hosts):
    issues=[];hub=hosts.get('hub',{});robot=hosts.get('robot',{});session=hub.get('session',{})
    for name,value in models.items():
        if not value.get('ready') or value.get('quarantined'):issues.append('compute:'+name)
    vision=models.get('gateway',{}).get('vision',{})
    if vision.get('error'):issues.append('vision:'+vision['error'])
    if vision.get('detector',{}).get('error'):issues.append('detector:'+vision['detector']['error'])
    if vision.get('detector',{}).get('backend_error'):issues.append('detector:cpu_fallback:'+vision['detector']['backend_error'])
    for role,value in hosts.items():
        if not value.get('reachable'):issues.append('unreachable:'+role);continue
        for name,state in value.get('services',{}).items():
            if state!='active' and not (state=='inactive' and name in ('reachy-production','reachy-production-audio')):issues.append('service:'+name+':'+state)
        if value.get('disk',{}).get('used_percent',0)>=80:issues.append('disk:'+role)
    if robot.get('firewall',{}).get('duplicate_rules'):issues.append('firewall:duplicates')
    if robot.get('reachable') and not robot.get('firewall',{}).get('inspected'):issues.append('firewall:unknown')
    stage=session.get('stage','unavailable');speech=session.get('speech',{})
    if speech.get('quarantined') or speech.get('terminal_unknown'):issues.append('speech:unknown_completion')
    motion=session.get('motion',{})
    if motion.get('tracking_mode')=='pose_fault':issues.append('motion:pose_fault')
    if motion.get('stop_known') is False and not motion.get('execution_busy'):issues.append('motion:unknown_completion')
    if session.get('lease',{}).get('withdrawn'):issues.append('session:lease_withdrawn')
    if session.get('cycle_phase') not in (None,'ACTIVE'):issues.append('session:'+session['cycle_phase'].lower())
    if session.get('background',{}).get('errors'):issues.append('background:errors')
    if session.get('audio',{}).get('last_error'):issues.append('stt:'+session['audio']['last_error'])
    if session.get('audio',{}).get('waiting_terminal'):issues.append('stt:waiting_terminal')
    if stage=='ACTIVE' and hub.get('capabilities',{}).get('motion') and robot.get('motor_mode')!='enabled':
        issues.append('motors:'+str(robot.get('motor_mode','unknown')))
    if stage=='ACTIVE' and not session.get('listening_ready'):issues.append('audio:not_ready')
    if stage=='ACTIVE' and session.get('listening_ready') and not any(i.startswith(('unreachable:','compute:','service:','speech:','session:','audio:')) for i in issues):
        state='ready' if not issues else 'degraded'
    elif stage in ('WITHDRAWN','STOPPED'):state='needs_start'
    elif stage=='ACTIVE':state='degraded'
    elif hub.get('reachable') and hub.get('services',{}).get('reachy-production')=='failed':state='needs_start'
    elif hub.get('reachable') and hub.get('services',{}).get('reachy-production')=='inactive':state='stopped'
    else:state='unavailable'
    if state not in ('ready','degraded','stopped'):issues.append('session:'+stage.lower())
    return dict(state=state,issues=issues,recovery=dict(automatic_microphone_restart=False,
        command='scripts/production-control start' if state=='stopped' else 'scripts/production-control restart' if state in ('needs_start','unavailable') or stage in ('WITHDRAWN','STOPPED') else None))


def collect(root):
    root=Path(root)
    try:vision=json.loads((root/'config.autonomous.mac.local.json').read_text()).get('gateway',{}).get('vision',{}).get('enabled',False)
    except (OSError,ValueError):vision=False
    with ThreadPoolExecutor(max_workers=6) as pool:
        model_jobs={name:pool.submit(probe_model,root,name) for name in PORTS if name!='vlm' or vision}
        host_jobs={role:pool.submit(probe_host,role) for role in HOSTS}
        models={k:v.result() for k,v in model_jobs.items()};hosts={k:v.result() for k,v in host_jobs.items()}
    return dict(schema_version=1,checked_at=datetime.now(timezone.utc).isoformat(),
                **summarize(models,hosts),compute=models,hosts=hosts)


def format_human(report):
    lines=['System: '+report['state'].upper(), 'Checked: '+report['checked_at']]
    lines.append('Compute: '+', '.join(name+'='+('ready' if value.get('ready') and not value.get('quarantined') else 'unavailable') for name,value in report['compute'].items()))
    for role,host in report['hosts'].items():
        if not host.get('reachable'):
            lines.append(role+': unreachable ('+host.get('error_class','unknown')+')');continue
        lines.append(role+': '+', '.join(name+'='+state for name,state in host.get('services',{}).items()))
        if role=='robot':lines.append('  motors: '+str(host.get('motor_mode','unknown')))
        disk=host.get('disk',{});lines.append('  disk: '+str(disk.get('used_percent','?'))+'% used')
    hub=report['hosts'].get('hub',{});session=hub.get('session',{})
    lines.append('Session: '+str(session.get('stage','unavailable'))+', listening='+str(session.get('listening_ready',False)))
    runtime=session.get('runtime',{});network=runtime.get('network',{})
    if network:
        lines.append('HTTP observed round trip: '+', '.join(name+'='+str(network.get(name,{}).get('state','unknown'))+
            ' ('+str(network.get(name,{}).get('elapsed_ms','?'))+' ms)' for name in ('robot','compute'))+
            '; internet='+str(network.get('internet','unknown')))
    pressure=runtime.get('pressure',{})
    if pressure and pressure.get('phase')!='ACTIVE':
        lines.append('Pressure: '+str(pressure.get('phase'))+', '+str(pressure.get('elapsed_s',0))+' s; '+
                     ', '.join(pressure.get('reasons') or pressure.get('last_trigger',{}).get('reasons',[])))
        lines.append('  active seconds: '+json.dumps(pressure.get('active_age_s',{}),sort_keys=True))
    motion=session.get('motion',{})
    if motion.get('tracking_enabled'):
        lines.append('Tracking: '+str(motion.get('tracking_mode'))+', error='+str(motion.get('tracking_error')))
    last=hub.get('last_session')
    if last and session.get('stage')!='ACTIVE':
        lines.append('Last exit: '+str(last.get('failure_code') or last.get('reason'))+', cleanup_verified='+str(last.get('cleanup_verified')))
        if last.get('cleanup_issues'):lines.append('  unresolved: '+', '.join(last['cleanup_issues']))
    audio=session.get('audio',{});counts=audio.get('counts',{})
    if counts:lines.append('STT: '+', '.join(k+'='+str(counts[k]) for k in ('submitted','completed','empty','errors','timeouts','stale','overwritten') if k in counts))
    background=session.get('background',{});outbox=background.get('outbox',{})
    if outbox:lines.append('Logs: retained='+str(outbox.get('retained'))+', pending_s3='+str(outbox.get('pending_s3'))+', pending_vps='+str(outbox.get('pending_vps')))
    if hub.get('capabilities'):lines.append('Capabilities: '+json.dumps(hub['capabilities'],ensure_ascii=False))
    if report['issues']:lines.append('Issues: '+', '.join(report['issues']))
    if report['recovery']['command']:lines.append('Explicit recovery: '+report['recovery']['command'])
    return '\n'.join(lines)
