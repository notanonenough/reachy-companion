"""Configure the local CPU VLM and its latest-only background cache.

Mac: python install_vision.py mac --root <workspace>
Hub: sudo python install_vision.py hub --root /home/deploy/reachy-companion
No service starts here; explicitly restart the existing production session.
"""
import argparse
import json
import os
from pathlib import Path
import plistlib


def write(path,content,mode=0o600):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    old=path.stat() if path.exists() else None
    if old:
        backup=path.with_name(path.name+'.before-vlm')
        if not backup.exists():backup.write_bytes(path.read_bytes());backup.chmod(old.st_mode&0o777)
    temp=path.with_name(path.name+'.vlm-tmp');temp.write_bytes(content);temp.chmod(mode)
    if old:os.chown(temp,old.st_uid,old.st_gid)
    temp.replace(path)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('role',choices=('mac','hub'));p.add_argument('--root',type=Path,required=True)
    args=p.parse_args();root=args.root.resolve()
    config_path=root/'config.autonomous.mac.local.json';cfg=json.loads(config_path.read_text())
    if args.role=='hub':
        cfg['production']['sensors']['camera.scene']=dict(url='http://127.0.0.1:8097/vision',
            token_env=cfg['gateway']['token_env'],source_id='mac-smolvlm2',period_s=.5,timeout_s=1)
        cfg['production']['sensors']['camera.change']=dict(url='http://127.0.0.1:8097/vision/change',
            token_env=cfg['gateway']['token_env'],source_id='mac-yolox-changes',period_s=.5,timeout_s=1)
        cfg['production']['sensors']['camera.objects']=dict(url='http://127.0.0.1:8097/vision/objects',
            token_env=cfg['gateway']['token_env'],source_id='mac-yolox',period_s=.5,timeout_s=1)
        cfg['production']['sensors']['camera.person']=dict(url='http://127.0.0.1:8097/vision/person',
            token_env=cfg['gateway']['token_env'],source_id='mac-yolox-person',period_s=.25,timeout_s=1)
    else:
        model=root/'models/smolvlm2-500m/SmolVLM2-500M-Video-Instruct-Q8_0.gguf'
        projector=model.with_name('mmproj-SmolVLM2-500M-Video-Instruct-Q8_0.gguf')
        if not model.is_file() or not projector.is_file():raise ValueError('Stage verified VLM weights first')
        detector=root/'models/yolox/object_detection_yolox_2022nov.onnx'
        if not detector.is_file():raise ValueError('Stage verified object detector weights first')
        cfg['gateway']['vision']=dict(enabled=True,camera_url='http://127.0.0.1:18794/frame',
            camera_token_file='secrets/token',model_url='http://127.0.0.1:18099',
            poll_s=.5,interval_s=2,ttl_s=20,timeout_s=25,detector_model=str(detector))
        directory=Path.home()/'Library/Application Support/Reachy Companion/LaunchAgents'
        command=[str(root/'.venv/bin/python'),'-m','reachy_companion.production_logs','run',
            '--log',str(root/'data/mac-runtime/vlm.log'),'--',str(Path.home()/'.local/bin/llama'),'serve',
            '-m',str(model),'--mmproj',str(projector),'--host','127.0.0.1','--port','18099',
            '-c','2048','-np','1','-ngl','0','--no-mmproj-offload','-t','2','-tb','2',
            '--prio','-1','--alias','reachy-vision','--slots','--cache-ram','0']
        definition=dict(Label='local.reachy.vlm',ProgramArguments=command,WorkingDirectory=str(root),
            EnvironmentVariables=dict(PYTHONPATH=str(root/'src')),RunAtLoad=False,KeepAlive=True,
            StandardOutPath='/dev/null',StandardErrorPath='/dev/null')
        write(directory/'local.reachy.vlm.plist',plistlib.dumps(definition))
        tunnel_path=directory/'local.reachy.tunnels.plist';tunnel=plistlib.loads(tunnel_path.read_bytes())
        arguments=tunnel['ProgramArguments'];forward='127.0.0.1:18794:127.0.0.1:18794'
        if forward not in arguments:arguments[-1:-1]=['-L',forward]
        write(tunnel_path,plistlib.dumps(tunnel))
    write(config_path,(json.dumps(cfg,ensure_ascii=False,indent=2)+'\n').encode())
    print(json.dumps(dict(configured=args.role,restart_required=True,vision_device='cpu',image_upload_to_cloud=False)))


if __name__=='__main__':main()
