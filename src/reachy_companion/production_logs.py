"""Bounded production logging and retention; never removes unfinished sessions."""
import argparse
from datetime import datetime, timezone
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
from .private_audio_trace import project_summary
from .lease_diagnostics import project_first_lease_invalid,project_lease_withdrawal_reason,project_first_reducer_expiry


from .autonomous.stock_diagnostics import project as project_stock_diagnostics
from .autonomous.terminal_drain import project as project_terminal_drain


def report_summary(report):
    result={k:report[k] for k in ('mode','accepted','reason','errors','error','cleanup_error',
        'failure_code','cleanup_verified','cleanup_issues','elapsed_s','peer_close_reason','microphone_restored','capture_closed') if k in report}
    if 'first_lease_invalid' in report:result['first_lease_invalid']=project_first_lease_invalid(report['first_lease_invalid'])
    if 'terminal_drain' in report:result['terminal_drain']=project_terminal_drain(report['terminal_drain'])
    if 'first_reducer_expiry' in report:result['first_reducer_expiry']=project_first_reducer_expiry(report['first_reducer_expiry'])
    motion=report.get('motion_after')
    if isinstance(motion,dict) and 'stock_diagnostics' in motion:
        result['stock_diagnostics']=project_stock_diagnostics(motion['stock_diagnostics'])
    private=report.get('private_audio_trace')
    if isinstance(private,dict):
        result['private_audio_trace']=project_summary(private)
    if isinstance(report.get('lease'),dict):
        result['lease_withdrawal_reason']=project_lease_withdrawal_reason(report['lease'].get('withdrawal_reason'))
    return result


def prune_reports(data, *, keep=30, days=7, apply=False, now=None):
    """Only completed production directories, with no links or foreign files."""
    data=Path(data);now=time.time() if now is None else now
    completed=[];removed=[]
    for directory in data.glob('production-*'):
        if directory.is_symlink() or not directory.is_dir():continue
        files=list(directory.iterdir())
        if not files or any(p.is_symlink() or not p.is_file() or p.name not in ('owner.json','hub.json','device.json') for p in files):continue
        reports=[p for p in files if p.name in ('hub.json','device.json')]
        if not reports:continue
        try:
            for p in reports:
                if p.stat().st_size>8*1024*1024:raise ValueError('report bound')
                d=json.loads(p.read_text())
                # A partial report must not make an active directory eligible.
                if not isinstance(d,dict) or 'accepted' not in d or 'elapsed_s' not in d:raise ValueError('unfinished')
            completed.append((max(p.stat().st_mtime for p in files),directory))
        except (OSError,ValueError):continue
    for index,(modified,directory) in enumerate(sorted(completed,reverse=True)):
        if now-modified<3600:continue
        if index<keep and now-modified<days*86400:continue
        removed.append(directory.name)
        if apply:shutil.rmtree(directory)
    return dict(apply=apply,completed=len(completed),removed=removed)


def run_logged(path, argv, *, max_bytes=5*1024*1024, backups=3, keep_awake=False):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    handler=RotatingFileHandler(path,maxBytes=max_bytes,backupCount=backups,encoding='utf-8')
    path.chmod(0o600)
    handler.setFormatter(logging.Formatter('%(message)s'))
    logger=logging.Logger('child',level=logging.INFO);logger.addHandler(handler)
    try:child=subprocess.Popen(argv,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,start_new_session=True)
    except OSError as exc:
        logger.error('child_start_failed error_class=%s',type(exc).__name__);handler.close();return 2
    previous={};awake=None
    def forward(signum,frame):
        try:os.killpg(child.pid,signum)
        except ProcessLookupError:pass
    try:
        if keep_awake and sys.platform=='darwin':
            # Tied to this child only. No global power settings or lid override.
            awake=subprocess.Popen(['/usr/bin/caffeinate','-i','-w',str(child.pid)],
                                   stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        for signum in (signal.SIGTERM,signal.SIGINT):previous[signum]=signal.signal(signum,forward)
        while True:
            line=child.stdout.readline(16384)
            if not line:break
            logger.info('%s',line.decode('utf-8',errors='replace').rstrip())
        code=child.wait()
        return code if code>=0 else 128-code
    finally:
        if child.poll() is None:
            forward(signal.SIGTERM,None)
            try:child.wait(timeout=5)
            except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
        child.stdout.close();handler.close()
        if awake is not None:
            if awake.poll() is None:awake.terminate()
            try:awake.wait(timeout=2)
            except subprocess.TimeoutExpired:awake.kill();awake.wait()
        for signum,value in previous.items():signal.signal(signum,value)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='action',required=True)
    run=sub.add_parser('run');run.add_argument('--log',type=Path,required=True)
    run.add_argument('--keep-awake',action='store_true');run.add_argument('command',nargs=argparse.REMAINDER)
    prune=sub.add_parser('prune');prune.add_argument('--data',type=Path,required=True);prune.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    if args.action=='prune':
        print(json.dumps(dict(at=datetime.now(timezone.utc).isoformat(),**prune_reports(args.data,apply=args.apply))));return 0
    argv=args.command[1:] if args.command[:1]==['--'] else args.command
    if not argv:parser.error('A child command is required')
    os.umask(0o077)
    return run_logged(args.log,argv,keep_awake=args.keep_awake)


if __name__=='__main__':raise SystemExit(main())
