"""Install bounded logs/retention and declarative firewall without starting audio.

Linux: sudo python3 ... robot|hub --root ... [--hub-ip ...]
Mac: .venv/bin/python ... mac --root ...
Firewall changes arm a 90s rollback; verify a NEW SSH connection, then stop the
printed rollback timer. A repeated installation replaces rules atomically.
"""
import argparse
from datetime import datetime, timezone
import ipaddress
import json
import os
from pathlib import Path
import plistlib
import shlex
import shutil
import subprocess
import sys


def run(*args,**kwargs):return subprocess.run(args,check=True,text=True,**kwargs)


def write(path, text, mode=0o644):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists() and not path.with_name(path.name+'.before-operations').exists():
        backup=path.with_name(path.name+'.before-operations');backup.write_bytes(path.read_bytes());backup.chmod(path.stat().st_mode&0o777)
    temporary=path.with_name(path.name+'.operations-tmp');temporary.write_text(text);temporary.chmod(mode);temporary.replace(path)


def retire_runtime_overlays(directory,archive):
    """Archive pure historical source/entrypoint overlays, preserving hardening."""
    moved=[]
    for path in sorted(Path(directory).glob('*.conf')):
        if path.name in ('60-operations.conf','zz-production-runtime.conf'):continue
        lines=[line.strip() for line in path.read_text().splitlines() if line.strip() and not line.lstrip().startswith(('#',';'))]
        if not lines or '[Service]' not in lines:continue
        def owned(line):
            if line=='[Service]' or line.startswith('ExecStart='):return True
            return any(line.startswith('Environment='+key+'=') for key in
                       ('PYTHONPATH','REACHY_U58_FENCE_PATH','REACHY_U58_FENCE_SHA256'))
        if not all(owned(line) for line in lines):continue
        destination=Path(archive)/path.name
        destination.parent.mkdir(parents=True,exist_ok=True)
        if destination.exists():raise RuntimeError('Archive collision: '+path.name)
        shutil.move(str(path),str(destination));moved.append(path.name)
    return moved


def install_mac(root,source,main_model=None,vad_filter=None):
    legacy=Path.home()/'Library/LaunchAgents'
    directory=Path.home()/'Library/Application Support/Reachy Companion/LaunchAgents'
    directory.mkdir(parents=True,exist_ok=True);directory.chmod(0o700);installed=[]
    for name in ('config.local.json','config.mac.local.json'):
        config_path=root/name
        if config_path.exists():
            value=json.loads(config_path.read_text());value['logging']['log_transcripts']=False
            if vad_filter is not None:value['conversation'].setdefault('recognition',{})['vad_filter']=vad_filter
            write(config_path,json.dumps(value,ensure_ascii=False,indent=2)+'\n',0o600)
    log_dir=root/'data/mac-runtime'
    log_dir.mkdir(parents=True,exist_ok=True);log_dir.chmod(0o700)
    for existing in log_dir.glob('*.log*'):
        if existing.is_file() and not existing.is_symlink():existing.chmod(0o600)
    names=('llm','fast','worker','gateway','tunnels')
    if any((p/'local.reachy.vlm.plist').is_file() for p in (legacy,directory)):names+=('vlm',)
    for name in names:
        path=directory/('local.reachy.'+name+'.plist');old=legacy/path.name
        source_path=path if path.exists() else old
        data=plistlib.loads(source_path.read_bytes())
        command=data['ProgramArguments']
        if main_model is not None and name=='llm':
            model=main_model.resolve()
            if not model.is_relative_to(root/'models') or not model.is_file():raise ValueError('Main model must be staged inside models/')
            original=command[command.index('--')+1:] if 'reachy_companion.production_logs' in command else command
            index=original.index('-m')+1;original[index]=str(model)
            if 'reachy_companion.production_logs' in command:command=command[:command.index('--')+1]+original
            else:command=original
            data['ProgramArguments']=command
        if 'reachy_companion.production_logs' not in command:
            log=data.get('StandardOutPath',str(root/'data/mac-runtime'/('local.reachy.'+name+'.log')))
            data['ProgramArguments']=[str(root/'.venv/bin/python'),'-m','reachy_companion.production_logs','run','--log',log,'--',*command]
        if name=='gateway' and '--keep-awake' not in data['ProgramArguments']:
            data['ProgramArguments'].insert(data['ProgramArguments'].index('--'),'--keep-awake')
        data.setdefault('EnvironmentVariables',{})['PYTHONPATH']=str(source/'src')
        data['StandardOutPath']='/dev/null';data['StandardErrorPath']='/dev/null'
        data['RunAtLoad']=False
        data['KeepAlive']=True
        write(path,plistlib.dumps(data).decode(),0o600);installed.append(path.name)
        if old.exists():
            backup=old.with_name(old.name+'.before-manual-start')
            if not backup.exists():shutil.copy2(old,backup)
            old.unlink()
    commands=Path.home()/'.local/bin';commands.mkdir(parents=True,exist_ok=True)
    for name in ('reachy-on','reachy-off'):
        target=root/'scripts'/name;entry=commands/name
        if entry.is_symlink() and entry.resolve()==target.resolve():continue
        if entry.exists() or entry.is_symlink():raise FileExistsError('Command already exists: '+str(entry))
        entry.symlink_to(target)
    print(json.dumps(dict(installed=installed,autostart=False,restart_required=True,commands=['reachy-on','reachy-off'])))


def install_linux(role,root,source,hub_ip,robot_ip,stt_diagnostics=False):
    if os.geteuid()!=0:raise PermissionError('Run Linux installation as root')
    # systemd paths are configuration, not shell text.
    if any(any(c.isspace() or c in '%"\\' for c in str(p)) for p in (root,source)):raise ValueError('Unsupported systemd path')
    config_path=root/'config.local.json'
    config_owner=config_path.stat();value=json.loads(config_path.read_text());value['logging']['log_transcripts']=False
    write(config_path,json.dumps(value,ensure_ascii=False,indent=2)+'\n',0o600)
    os.chown(config_path,config_owner.st_uid,config_owner.st_gid)
    user='deploy' if role=='hub' else 'pollen'
    services=('reachy-production','reachy-hub','reachy-voice') if role=='hub' else ('reachy-production-audio','reachy-voice-agent')
    if not robot_ip:raise ValueError('Explicit --robot-ip is required')
    robot_ip=str(ipaddress.IPv4Address(robot_ip))
    python=root/('.venv-router/bin/python' if role=='hub' else '.venv/bin/python')
    entry=source/'deploy/autonomous/production_start.py'
    if role=='hub':
        if stt_diagnostics:
            auto_path=root/'config.autonomous.mac.local.json';auto_owner=auto_path.stat()
            auto=json.loads(auto_path.read_text());auto.setdefault('production',{})['stt_diagnostics']=True
            write(auto_path,json.dumps(auto,ensure_ascii=False,indent=2)+'\n',0o600)
            os.chown(auto_path,auto_owner.st_uid,auto_owner.st_gid)
        argv=[str(python),str(entry),'hub','--root',str(root),'--config',str(root/'config.autonomous.mac.local.json'),
              '--token-file',str(root/'secrets/autonomous-mac.token'),'--peer-url','http://'+robot_ip+':8780',
              '--peer-stop-port','8781','--lease-datagram-port','8782','--trusted-private-lan']
    else:
        argv=[str(python),str(entry),'device','--root',str(root),'--listen-device',robot_ip,'--lease-datagram-port','8782']
    for name in services:
        directory=Path('/etc/systemd/system')/(name+'.service.d')
        retired=retire_runtime_overlays(directory,Path('/var/lib/reachy-operations/dropins')/name)
        if retired:print(json.dumps(dict(service=name,archived_runtime_overlays=len(retired))))
    write('/etc/systemd/system/'+services[0]+'.service.d/zz-production-runtime.conf',
          '[Service]\nEnvironment=PYTHONPATH='+str(source/'src')+'\nExecStart=\nExecStart='+shlex.join(argv)+'\n')
    for name,group in zip(services[1:],('hub','voice') if role=='hub' else ('agent',)):
        command=[str(python),'-B','-m','reachy_companion','--config',str(root/'config.local.json'),group,'serve']
        write('/etc/systemd/system/'+name+'.service.d/zz-production-runtime.conf',
              '[Service]\nEnvironment=PYTHONPATH='+str(source/'src')+'\nExecStart=\nExecStart='+shlex.join(command)+'\n')

    for name in services:
        content='[Service]\nEnvironment=PYTHONPATH='+str(source/'src')+'\nLogRateLimitIntervalSec=30s\nLogRateLimitBurst=200\n'
        if name=='reachy-production-audio':content+='ExecStartPre=\n'
        write('/etc/systemd/system/'+name+'.service.d/60-operations.conf',content)
    unit=f'''[Unit]
Description=Retain bounded completed Reachy session reports
[Service]
Type=oneshot
User={user}
Environment=PYTHONPATH={source}/src
ExecStart=/usr/bin/python3 -m reachy_companion.production_logs prune --data {root}/data --apply
UMask=0077
'''
    write('/etc/systemd/system/reachy-report-retention.service',unit)
    write('/etc/systemd/system/reachy-report-retention.timer','[Unit]\nDescription=Daily Reachy report retention\n[Timer]\nOnCalendar=daily\nPersistent=true\nRandomizedDelaySec=300\n[Install]\nWantedBy=timers.target\n')
    if role=='robot':
        if not hub_ip:raise ValueError('Explicit --hub-ip is required')
        hub_ip=str(ipaddress.IPv4Address(hub_ip))
        sys.path.insert(0,str(source/'src'))
        from reachy_companion.config import Config
        from reachy_companion.firewall import render,settings
        cfg=Config(root/'config.local.json',require_token=False)
        if cfg['security']['robot'].get('policy')!='local_ssh':raise ValueError('Expected installed local_ssh policy')
        cfg.data['security']['robot']['production_peer_ipv4']=hub_ip
        settings(cfg);new_rules=render(cfg)
        table=cfg['security']['robot']['nft_table']
        previous=run('nft','list','table','inet',table,capture_output=True).stdout
        replacement=f'delete table inet {table}\n'+new_rules
        run('nft','--check','-f','-',input=replacement)
        state=Path('/var/lib/reachy-operations');state.mkdir(mode=0o700,exist_ok=True)
        stamp=datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')
        rollback=state/(stamp+'.nft');rollback.write_text(f'delete table inet {table}\n'+previous);rollback.chmod(0o600)
        config_backup=state/(stamp+'.config.json');config_backup.write_bytes(cfg.filename.read_bytes());config_backup.chmod(0o600)
        rollback_script=state/(stamp+'.sh')
        rollback_script.write_text('#!/bin/sh\ncp '+shlex.quote(str(config_backup))+' '+shlex.quote(str(cfg.filename))+'\n/usr/sbin/nft -f '+shlex.quote(str(rollback))+'\n');rollback_script.chmod(0o700)
        timer='reachy-operations-rollback-'+stamp
        run('systemd-run','--unit='+timer,'--on-active=90s','/bin/sh',str(rollback_script))
        # Preserve config ownership when replacing it as root.
        owner=cfg.filename.stat()
        raw_config=json.loads(cfg.filename.read_text())
        raw_config['security']['robot']['production_peer_ipv4']=hub_ip
        write(cfg.filename,json.dumps(raw_config,ensure_ascii=False,indent=2)+'\n',0o600)
        os.chown(cfg.filename,owner.st_uid,owner.st_gid)
        write('/etc/systemd/system/'+cfg['security']['robot']['service']+'.service.d/60-operations.conf',
              '[Service]\nEnvironment=PYTHONPATH='+str(source/'src')+'\n')
        run('nft','-f','-',input=replacement)
        print(json.dumps(dict(firewall='applied',rollback_timer=timer+'.timer',requires_new_ssh_verification=True)),flush=True)
    run('systemctl','daemon-reload')
    for name in services:
        result=run('systemctl','show',name,'--property=Environment','--value',capture_output=True)
        environment=dict(item.split('=',1) for item in shlex.split(result.stdout) if '=' in item)
        if environment.get('PYTHONPATH')!=str(source/'src'):
            raise RuntimeError('Another override shadows the selected source: '+name)
    run('systemctl','enable','--now','reachy-report-retention.timer')
    run('systemctl','start','reachy-report-retention.service')
    print(json.dumps(dict(role=role,installed=True,audio_started=False)))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('role',choices=('mac','hub','robot'));parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--source-root',type=Path);parser.add_argument('--main-model',type=Path);parser.add_argument('--hub-ip');parser.add_argument('--robot-ip');parser.add_argument('--stt-diagnostics',action='store_true',help='Hub: worker must enable recognition diagnostics')
    parser.add_argument('--vad-filter',action=argparse.BooleanOptionalAction,default=None)
    args=parser.parse_args();root=args.root.resolve();source=(args.source_root or Path(__file__).resolve().parents[2]).resolve()
    if args.role=='mac':install_mac(root,source,args.main_model,args.vad_filter)
    else:install_linux(args.role,root,source,args.hub_ip,args.robot_ip,args.stt_diagnostics)


if __name__=='__main__':main()
