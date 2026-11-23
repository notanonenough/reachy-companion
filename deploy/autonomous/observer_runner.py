"""Concrete observer target acquisition from fixed production owner/service receipts."""
import argparse
import json
import os
from pathlib import Path
import runpy
import signal
import subprocess
import sys
from resource_observer import ProcessReader,bind_receipt,probe_deadline,run,Writer,StatusPoll


def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--execute',action='store_true');p.add_argument('--node',choices=('mac','hub','robot'),required=True)
    p.add_argument('--root',type=Path);p.add_argument('--candidate',required=True);p.add_argument('--owner',default='{}');a=p.parse_args(argv)
    if not a.execute:print(json.dumps(dict(mode='dry_run',node=a.node,probes=False)));return 0
    writer=Writer(sys.stdout.buffer);stopped=[False]
    def stop(*_):stopped[0]=True
    for sig in (signal.SIGTERM,signal.SIGINT,signal.SIGHUP):signal.signal(sig,stop)
    try:
        reader=ProcessReader();status_poll=None
        with probe_deadline(3):
            if a.node=='mac':
                root=a.root
                control=runpy.run_path(str(root/'scripts/production-control'),run_name='observer_receipt_helpers')
                # Existing fixed launchd-label + descendant PID receipts; no argv scan.
                receipts=control['mac_owned_processes']('gui/'+str(os.getuid()))
                if not 1<=len(receipts)<=8:raise ValueError('targets')
                targets=[]
                for pid,receipt in sorted(receipts.items()):
                    item=bind_receipt(reader,role='mac_provider',pid=pid)
                    if control['process_identity'](pid)!=receipt:raise ValueError('receipt_changed')
                    targets.append(item)
            else:
                root=Path('/home/deploy/reachy-companion' if a.node=='hub' else '/home/pollen/reachy-companion')
                if json.loads((root/'current/release.json').read_text())['commit']!=a.candidate:raise ValueError('candidate')
                if a.node=='robot':
                    def pid():return int(subprocess.check_output(['systemctl','show','reachy-production-audio','-p','MainPID','--value'],text=True,timeout=.5).strip())
                    known=pid();item=bind_receipt(reader,role='robot_audio',pid=known)
                    if pid()!=known:raise ValueError('unit_changed')
                    targets=[item]
                else:
                    owner=json.loads(a.owner);item=bind_receipt(reader,role='hub_owner',pid=owner['pid'])
                    if item['process_start_identity']!=owner['start_ticks']:raise ValueError('owner_changed')
                    from observer_listener import listener_owned
                    if not listener_owned(owner['pid'],owner['start_ticks']):raise ValueError('listener')
                    c=json.loads((root/'config.local.json').read_text());token=Path(c['paths']['token_file']);token=token if token.is_absolute() else root/token
                    status_poll=StatusPoll(dict(candidate=a.candidate,binding=owner['binding'],token_file=str(token)),provenance=lambda:listener_owned(owner['pid'],owner['start_ticks']))
                    targets=[item]
        result=run(reader,targets,a.node,writer,stopped=lambda:stopped[0],status_poll=status_poll)
        return 2 if result['incomplete'] else 0
    except Exception:
        writer.write(dict(version=1,kind='observer_end',node=a.node,incomplete=True,reason='acquisition_failed'));return 2


if __name__=='__main__':raise SystemExit(main())
