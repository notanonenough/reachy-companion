"""Content-free projection shared by live, final and installed-host diagnostics."""
import json
import math
import re
import sys
import threading
import time


def project_lease_withdrawal_reason(value):
    """Existing worker/close reason, never inferred from an invalid snapshot."""
    known=('controller_stop','authority_changed','reducer_expired','initial_authority_timeout',
           'late_renewal_ack','renewal_unknown','renewal_worker_failed')
    return value if type(value) is str and value in known else None


def project_first_lease_invalid(value):
    """Self-contained: production_status embeds this trusted source in its probe."""
    import math
    if not isinstance(value,dict) or value.get('cause')!='invalid_complete_authority':return None
    checks=('peer_receipt_present','operator_ready','status_seen','status_fresh',
            'current_present','current_fresh','microphone_enabled','not_quiet','not_privacy','binding_matches')
    raw=value.get('predicates')
    raw=raw if isinstance(raw,dict) else {}
    predicates={key:raw.get(key) if type(raw.get(key)) is bool else None for key in checks}
    def number(item,signed=False):
        if type(item) not in (int,float):return None
        try:
            if not math.isfinite(item):return None
        except OverflowError:return None
        return round(max(-1e12 if signed else 0,min(1e12,item)),3)
    timings=value.get('lease_timing')
    timings=timings if isinstance(timings,dict) else {}
    prior=value.get('prior_withdrawal_reason')
    known=('controller_stop','authority_changed','reducer_expired','initial_authority_timeout',
           'late_renewal_ack','renewal_unknown','renewal_worker_failed')
    return dict(cause='invalid_complete_authority',
        failed_checks=[key for key in checks if predicates[key] is False],predicates=predicates,
        elapsed_ms=number(value.get('elapsed_ms')),
        startup_phase=value.get('startup_phase') if value.get('startup_phase') in
            ('STARTING','ACTIVE','WITHDRAWN','STOPPED') else 'unknown',
        peer_status_age_ms=number(value.get('peer_status_age_ms')),
        operator_valid_remaining_ms=number(value.get('operator_valid_remaining_ms'),True),
        lease_already_withdrawn=value.get('lease_already_withdrawn') is True,
        prior_withdrawal_reason=prior if prior in known else None,
        diagnostic_unavailable=value.get('diagnostic_unavailable') is True,
        lease_timing={key:number(timings.get(key)) for key in
            ('last_send_age_ms','last_accepted_age_ms','reducer_progress_age_ms',
             'worker_scheduling_age_ms','progress_timeout_ms','max_call_ms')})


def project_first_reducer_expiry(value):
    """Standalone bounded projection; frame labels are trusted code metadata."""
    import math
    import re
    if type(value) is not dict or value.get('cause')!='reducer_expired':return None
    stages=('startup_control','speech_advance','scheduler_advance','peer_poll',
            'lease_gate','status_publish','loop_wait','playback_control','cleanup')
    def number(item):
        if type(item) not in (int,float):return None
        try:
            if not math.isfinite(item):return None
        except OverflowError:return None
        return round(max(0,min(1e12,item)),3)
    frames=[]
    raw=value.get('stack')
    for frame in (raw[:16] if type(raw) is list else []):
        if type(frame) is not dict:continue
        module=frame.get('module');function=frame.get('function');line=frame.get('line')
        if (type(module) is not str or len(module)>160 or
                re.fullmatch(r'reachy_companion(?:\.[A-Za-z_][A-Za-z_0-9]*)+',module) is None):
            frames.append(dict(module='external',function='external',line=None));continue
        if (type(function) is not str or len(function)>96 or
                re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*|<module>|<lambda>|<listcomp>|<dictcomp>|<genexpr>|<setcomp>',function) is None):
            function='unknown'
        frames.append(dict(module=module,function=function,
            line=line if type(line) is int and 1<=line<=1000000 else None))
    return dict(cause='reducer_expired',stage=value.get('stage') if value.get('stage') in stages else 'unknown',
        stage_age_ms=number(value.get('stage_age_ms')),progress_age_ms=number(value.get('progress_age_ms')),
        capture_delay_ms=number(value.get('capture_delay_ms')),
        trigger=value.get('trigger') if value.get('trigger') in ('worker','tick') else 'unknown',
        capture_status=value.get('capture_status') if value.get('capture_status') in
            ('captured','thread_missing','unregistered','capture_failed') else 'capture_failed',
        stage_changed_during_capture=value.get('stage_changed_during_capture') is True,
        stack_truncated=value.get('stack_truncated') is True,stack=frames)


class ReducerTrace:
    """One reducer's stage hint, not progress, authority, or a profiler.

    Tuple assignment is the only reducer-side communication. No shared lock or
    callback is acquired while sampling; frames are inspected without locals.
    """
    def __init__(self):
        self.thread_id=None;self.stage=None;self._attempted=False;self._record=None
    def bind_current(self):
        self.thread_id=threading.get_ident()
        self.enter('startup_control')
    def enter(self,stage):
        self.stage=(stage,time.monotonic())
    def unbind(self):
        self.thread_id=None
    def capture(self,trigger,progress_age_ms,closed_at):
        if self._attempted:return
        self._attempted=True
        frame=None
        try:
            before=self.stage;sampled=time.monotonic();thread_id=self.thread_id
            value=dict(cause='reducer_expired',trigger=trigger,progress_age_ms=progress_age_ms,
                capture_delay_ms=(sampled-closed_at)*1000,stage=before[0] if before else None,
                stage_age_ms=(sampled-before[1])*1000 if before else None,stack=[],
                capture_status='unregistered' if thread_id is None else 'thread_missing')
            if thread_id is not None:
                frame=sys._current_frames().get(thread_id)
                if frame is not None:value['capture_status']='captured'
                # Lexical package prefix only: no path resolution or source IO.
                prefix=__file__.replace('\\','/').rsplit('/',1)[0]+'/'
                for _ in range(16):
                    if frame is None:break
                    filename=frame.f_code.co_filename.replace('\\','/')
                    module='external';function='external';line=None
                    if filename.startswith(prefix) and filename.endswith('.py'):
                        module='reachy_companion.'+filename[len(prefix):-3].replace('/','.')
                        function=frame.f_code.co_name;line=frame.f_lineno
                    value['stack'].append(dict(module=module,function=function,line=line))
                    frame=frame.f_back
                value['stack_truncated']=frame is not None
            value['stage_changed_during_capture']=self.stage is not before
            self._record=json.dumps(project_first_reducer_expiry(value),allow_nan=False)
        except Exception:
            self._record=json.dumps(project_first_reducer_expiry(dict(cause='reducer_expired',
                trigger=trigger,capture_status='capture_failed')),allow_nan=False)
        finally:
            # Never retain a frame (and its locals) in the record or tracker.
            frame=None
    def view(self):
        return json.loads(self._record) if self._record is not None else None
