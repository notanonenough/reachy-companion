"""Add camera stream metrics and S3-only export to an existing installation.

Run as root on robot or hub after staging source. S3 keys remain on Mac.
Does not start/restart a session; use production-control restart after installation.
"""
import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess


def write(path,text,mode=0o644):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        backup=path.with_name(path.name+'.before-continuous')
        if not backup.exists():
            backup.write_bytes(path.read_bytes());backup.chmod(path.stat().st_mode&0o777)
    temporary=path.with_name(path.name+'.continuous-tmp')
    temporary.write_text(text);temporary.chmod(mode);temporary.replace(path)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('role',choices=('robot','hub'))
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--source',type=Path,required=True)
    args=parser.parse_args()
    if os.geteuid()!=0:raise PermissionError('Requires systemd installation permission')
    root=args.root.resolve();source=args.source.resolve()
    if any(any(c.isspace() or c in '%"\\' for c in str(p)) for p in (root,source)):
        raise ValueError('Unsupported systemd path')
    if args.role=='robot':
        keys=Path('/var/lib/reachy-tunnel/.ssh/authorized_keys')
        original=keys.read_text();owner=keys.stat()
        lines=original.splitlines()
        matches=[i for i,line in enumerate(lines) if 'permitopen="127.0.0.1:8781"' in line]
        if len(matches)!=1:raise ValueError('Expected one existing robot tunnel key')
        index=matches[0]
        if 'permitopen="127.0.0.1:8794"' not in lines[index]:
            lines[index]=lines[index].replace('permitopen="127.0.0.1:8781"',
                'permitopen="127.0.0.1:8781",permitopen="127.0.0.1:8794"',1)
            write(keys,'\n'.join(lines)+'\n',0o600);os.chown(keys,owner.st_uid,owner.st_gid)
        unit=f'''[Unit]
Description=Reachy camera stream numeric measurements (no raw export)
After=reachy-voice-agent.service
PartOf=reachy-production-audio.service
[Service]
User=pollen
WorkingDirectory={root}
Environment=PYTHONPATH={source}/src
ExecStart=/venvs/mini_daemon/bin/python -m reachy_companion.autonomous.camera_sensor --config {root}/config.local.json
Restart=no
UMask=0077
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=read-only
TimeoutStopSec=8
'''
        write('/etc/systemd/system/reachy-camera-sensor.service',unit)
        write('/etc/systemd/system/reachy-production-audio.service.d/70-camera.conf',
              '[Unit]\nWants=reachy-camera-sensor.service\n')
    else:
        path=root/'config.autonomous.mac.local.json';owner=path.stat();cfg=json.loads(path.read_text())
        cfg['export_enabled']=True;production=cfg['production']
        production['sensors']['camera']={'url':'http://127.0.0.1:18794/sensor','token_file':'secrets/token',
            'period_s':.5,'timeout_s':1,'source_id':'reachy-camera-stream-metrics'}
        production['delivery']['s3']={'enabled':True,'relay':True,
            'url':'http://127.0.0.1:8097/logs/{id}','token_env':cfg['gateway']['token_env']}
        production['delivery']['vps']['enabled']=False
        if production.get('updates'):production['updates']['enabled']=False
        # Validate before changing the runtime configuration.
        import sys
        sys.path.insert(0,str(source/'src'))
        from reachy_companion.autonomous.durable import Delivery
        Delivery('s3',production['delivery']['s3'])
        write(path,json.dumps(cfg,ensure_ascii=False,indent=2)+'\n',0o600);os.chown(path,owner.st_uid,owner.st_gid)
        write('/etc/systemd/system/reachy-production.service.d/zzz-continuous.conf',
              '[Service]\nEnvironment=PYTHONPATH='+str(source/'src')+'\n')
        args_=['/usr/bin/ssh','-N','-T','-o','BatchMode=yes','-o','IdentitiesOnly=yes','-o','StrictHostKeyChecking=yes',
            '-o','UserKnownHostsFile=/home/deploy/.ssh/reachy_robot_known_hosts','-o','HostKeyAlias=reachy-mini-device',
            '-o','ExitOnForwardFailure=yes','-o','ServerAliveInterval=15','-o','ServerAliveCountMax=3',
            '-i','/home/deploy/.ssh/reachy_robot_tunnel']
        for local,remote in ((18000,8000),(18090,8090),(18780,8780),(18781,8781),(18794,8794)):
            args_+=['-L',f'127.0.0.1:{local}:127.0.0.1:{remote}']
        args_.append('reachy-tunnel@reachy-mini.local')
        write('/etc/systemd/system/reachy-robot-tunnel.service.d/70-camera.conf',
              '[Service]\nExecStart=\nExecStart='+shlex.join(args_)+'\n')
    subprocess.run(['systemctl','daemon-reload'],check=True)
    print(json.dumps(dict(installed=args.role,restart_required=True,raw_camera_export=False,vps_enabled=False)))


if __name__=='__main__':main()
