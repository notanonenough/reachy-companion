"""Offline, content-free baseline from bounded production evidence. Never starts a session."""
import argparse
from collections import Counter
import json
import math
from pathlib import Path
import statistics
from reachy_companion.autonomous.contracts import Authority,decode
from reachy_companion.model_timing import project as project_model_timing
from reachy_companion.lease_diagnostics import project_first_lease_invalid,project_first_reducer_expiry

TRACE_KINDS=('session_begin','stt_result','stt_disposition','input_admission','input_retry',
    'main_request','main_transport','main_result','main_checked','speech_commit','speech_terminal','playback_stop','trace_end')
COUNTERS=('submitted','overwritten','stale','echo','started','completed','no_response','empty','errors','timeouts')
METRICS=('stt_client_s','stt_end_to_admission_s','admission_to_main_start_s','main_client_s',
    'main_end_to_checked_s','checked_to_speech_s','tts_first_pcm_s','tts_producer_s','stt_end_to_playback_stop_s','retry_candidate_to_main_start_s')


def number(value):
    if type(value) is int:return 0<=value<=10**15
    return type(value) is float and math.isfinite(value) and 0<=value<=1e15


def identifier(value):
    return type(value) is str and 0<len(value)<=256


def valid_authority(value,hub_boot):
    if type(value) is not dict or set(value)!=set(Authority.__dataclass_fields__):return False
    return (value.get('hub_boot_id')==hub_boot and all(
        identifier(v) if k.endswith('boot_id') else type(v) is int and 0<=v<2**63 for k,v in value.items()))


def read_rows(path,*,trace=False,final=False):
    if path is None:return None
    cap=1048576 if trace else 33554432
    with Path(path).open('rb') as stream:raw=stream.read(cap+1)
    if len(raw)>cap:raise ValueError('input_size_cap')
    try:
        if final:
            value=decode(raw);rows=value if type(value) is list else [value]
        else:
            lines=raw.splitlines()
            if len(lines)>(512 if trace else 10000):raise ValueError('row_cap')
            if any(len(line)>(16384 if trace else 262144) for line in lines):raise ValueError('line_cap')
            rows=[decode(line) for line in lines]
    except (UnicodeError,json.JSONDecodeError,RecursionError):raise ValueError('invalid_json') from None
    if not all(type(row) is dict for row in rows):raise ValueError('object_required')
    return rows


def distribution(values):
    values=sorted(values);n=len(values)
    if not n:return dict(state='missing',n=0)
    # Nearest ranks are descriptive observations, not population tail guarantees.
    return dict(state='observed',n=n,min=values[0],p50=statistics.median(values),
        p95=values[math.ceil(.95*n)-1],p99=values[math.ceil(.99*n)-1],max=values[-1],
        tail_guarantee=False,quantile_method='empirical_nearest_rank_p95_p99')


def analyze_trace(rows):
    metrics={key:[] for key in METRICS};issues=Counter();counts=Counter()
    if rows is None:return dict(state='missing',metrics={k:distribution(v) for k,v in metrics.items()})
    if not rows:return dict(state='incomplete',issues={'empty_trace':1},metrics={k:distribution(v) for k,v in metrics.items()})
    begin=rows[0];identity=(begin.get('trace_id'),begin.get('hub_boot_id'))
    if begin.get('kind')!='session_begin' or not all(identifier(x) for x in identity):issues['session_identity']+=1
    events=[];footer=None
    # Project before indexing: arbitrary nested/text values never become report fields.
    ids=('trace_id','hub_boot_id','source_boot','lineage_id','input_ref','parent_input_ref','task_id','attempt_id','request_id','stream_id')
    times=('at','started_at','ended_at','tts_first_pcm_s','producer_elapsed_s')
    for index,row in enumerate(rows):
        kind=row.get('kind')
        if kind not in TRACE_KINDS:issues['unknown_event']+=1;continue
        counts[kind]+=1
        if kind=='trace_end':
            if footer is not None or index!=len(rows)-1:issues['footer_position']+=1
            footer=row;continue
        if ((row.get('trace_id'),row.get('hub_boot_id'))!=identity or row.get('clock_basis')!='hub_monotonic'
                or row.get('version')!=1 or not number(row.get('at'))):issues['clock_or_identity']+=1;continue
        clean={key:value for key,value in row.items() if key in ids and identifier(value)}
        clean.update({key:row[key] for key in times if number(row.get(key))})
        clean.update({key:row[key] for key in ('cancelled','tts_complete','stop_known','verified_stopped') if type(row.get(key)) is bool})
        clean['kind']=kind
        clean['disposition']=row.get('disposition') if type(row.get('disposition')) is str and len(row['disposition'])<=64 else None
        needs_authority=kind in ('stt_result','input_admission','input_retry','main_request','main_transport','main_result','main_checked','speech_commit','speech_terminal')
        if needs_authority and not valid_authority(row.get('authority'),identity[1]):
            issues['invalid_authority']+=1;continue
        clean['authority']=row.get('authority') if needs_authority else None
        if 'aggregation' in row:clean['aggregation']=row['aggregation']
        if kind=='main_transport':
            receipt=project_model_timing(row.get('model_timing'),request_id=row.get('attempt_id'),
                gateway_boot_id=row['authority']['compute_boot_id'])
            status=row.get('transport_diagnostic_status')
            missing=status in ('no_response','missing_diagnostic','malformed_diagnostic','identity_mismatch')
            if ((missing and row.get('model_timing')!=project_model_timing(None))
                    or (not missing and (status not in ('verified_receipt','partial_diagnostic') or receipt.get('reason')=='invalid_receipt' or receipt!=row.get('model_timing')))
                    or clean['disposition'] not in ('execution_unknown','observed_error_receipt','transport_failure')):
                issues['invalid_transport_receipt']+=1;continue
        if type(row.get('sequence')) is int and 0<=row['sequence']<2**63:clean['sequence']=row['sequence']
        events.append(clean)
    if counts['session_begin']!=1:issues['session_begin_count']+=1
    if footer is None:issues['missing_footer']+=1
    elif (footer.get('incomplete') is not False or type(footer.get('dropped')) is not int or footer.get('dropped')!=0
          or type(footer.get('records_written')) is not int or footer.get('records_written')!=len(rows)-1 or footer.get('clock_basis')!='hub_monotonic' or footer.get('version')!=1
          or not number(footer.get('at')) or footer['at']<max((r['at'] for r in events),default=0)):
        issues['incomplete_footer']+=1
    def table(kind,keys):
        result={};duplicate=set()
        for row in events:
            if row['kind']!=kind:continue
            key=tuple(row.get(k) for k in keys)
            if not all(identifier(x) or type(x) is int and 0<=x<2**63 for x in key):
                issues['missing_join_key']+=1;continue
            if key in result:duplicate.add(key);issues['duplicate_event']+=1
            else:result[key]=row
        return {k:v for k,v in result.items() if k not in duplicate}
    source_keys=('source_boot','sequence','lineage_id');task_keys=('task_id','attempt_id','input_ref')
    stt=table('stt_result',source_keys);admissions=table('input_admission',('input_ref',))
    requests=table('main_request',task_keys);results=table('main_result',task_keys)
    transports=table('main_transport',task_keys)
    for key,row in transports.items():
        request=requests.get(key)
        if request is None or request['authority']!=row['authority'] or row['at']<request['at']:
            issues['invalid_transport_join']+=1
    checked=table('main_checked',task_keys);commits=table('speech_commit',task_keys)
    terminal=table('speech_terminal',('request_id',));stops=table('playback_stop',('request_id',))
    refs={key[0]:row for key,row in admissions.items() if row.get('disposition')=='admitted'}
    for row in events:
        if row['kind']=='input_retry' and row.get('disposition')=='linked':
            parent=refs.get(row.get('parent_input_ref'));ref=row.get('input_ref')
            if (parent and identifier(ref) and ref not in refs and row.get('authority')==parent.get('authority')
                    and row['at']>=parent.get('retry_candidate_at',parent['at'])):
                refs[ref]={**parent,'retry_candidate_at':row['at']}
            else:issues['retry_link']+=1
    def interval(name,end,start):
        if number(end) and number(start) and end>=start:metrics[name].append(end-start)
        else:issues['invalid_or_missing_time']+=1
    def ordered(*values):return all(number(v) for v in values) and all(a<=z for a,z in zip(values,values[1:]))
    chains=0
    for key,request in requests.items():
        if request.get('disposition')!='audio_linked':continue
        admission=refs.get(key[2]);result=results.get(key);check=checked.get(key)
        if not admission or not result or not check:issues['missing_chain']+=1;continue
        if (type(admission.get('authority')) is not dict or
                any(row.get('authority')!=admission['authority'] for row in (request,result,check))):
            issues['authority_mismatch']+=1;continue
        if admission.get('aggregation') is not None:
            # Retain denominator/counts; never label the final fragment's STT
            # duration as the whole aggregated utterance. Detailed turn timing
            # requires its own member/clock join, not the legacy single source.
            issues['aggregate_timing_unsupported']+=1;continue
        source=stt.get(tuple(admission.get(k) for k in source_keys))
        if source is None:issues['missing_stt']+=1;continue
        if not ordered(source.get('started_at'),source.get('ended_at'),source.get('at'),admission.get('at')):
            issues['admission_time_conflict']+=1;continue
        if (request.get('started_at')!=result.get('started_at') or not ordered(
                admission.get('at'),admission.get('retry_candidate_at',admission.get('at')),request.get('started_at'),
                request.get('at'),result.get('ended_at'),result.get('at'),check.get('at'))):
            issues['attempt_time_conflict']+=1;continue
        interval('admission_to_main_start_s',request.get('started_at'),admission.get('at'))
        if 'retry_candidate_at' in admission:interval('retry_candidate_to_main_start_s',request.get('started_at'),admission['retry_candidate_at'])
        interval('main_client_s',result.get('ended_at'),result.get('started_at'))
        interval('main_end_to_checked_s',check.get('at'),result.get('ended_at'))
        commit=commits.get(key)
        if commit is None:continue # rejected/cancelled main attempts need not become speech
        if (check.get('disposition')!='ready' or commit.get('authority')!=admission['authority']
                or not ordered(check.get('at'),commit.get('at'))):
            issues['unready_speech']+=1;continue
        speech=terminal.get((commit.get('request_id'),));stop=stops.get((commit.get('request_id'),))
        if not speech or not stop:issues['missing_terminal']+=1;continue
        if (tuple(speech.get(k) for k in task_keys)!=key or speech.get('authority')!=admission['authority']
                or speech.get('stream_id')!=stop.get('stream_id') or source.get('source_boot')!=stop.get('source_boot')):
            issues['terminal_identity']+=1;continue
        if not ordered(commit.get('at'),speech.get('at')) or not ordered(commit.get('at'),stop.get('at')):
            issues['terminal_time_conflict']+=1;continue
        interval('checked_to_speech_s',commit.get('at'),check.get('at'))
        for name,field in (('tts_first_pcm_s','tts_first_pcm_s'),('tts_producer_s','producer_elapsed_s')):
            if number(speech.get(field)):metrics[name].append(speech[field])
            else:issues['invalid_or_missing_time']+=1
        interval('stt_end_to_playback_stop_s',stop.get('at'),source.get('ended_at'));chains+=1
        # Correlation alone is not physical/terminal acceptance. Kept as separate source evidence below.
    # Empty polls are not recognized speech latency. Keep all outcome denominators.
    stt_groups={key:[] for key in ('recognized','empty','stale','error','other')}
    stt_counts=Counter()
    for source in stt.values():
        group=source.get('disposition');group=group if group in stt_groups else 'other';stt_counts[group]+=1
        end,start=source.get('ended_at'),source.get('started_at')
        if ordered(start,end,source.get('at')):
            stt_groups[group].append(end-start)
            if group=='recognized':metrics['stt_client_s'].append(end-start)
        else:issues['invalid_or_missing_time']+=1
    for admission in admissions.values():
        source=stt.get(tuple(admission.get(k) for k in source_keys))
        if source and ordered(source.get('ended_at'),source.get('at'),admission.get('at')):interval('stt_end_to_admission_s',admission.get('at'),source.get('ended_at'))
        elif source:issues['admission_time_conflict']+=1
        else:issues['missing_stt']+=1
    return dict(state='incomplete' if issues else 'complete',issues=dict(issues),event_counts=dict(counts),
        audio_playback_chains=chains,terminal_outcomes=dict(cancelled=sum(r.get('cancelled') is True for r in terminal.values()),
            tts_complete=sum(r.get('tts_complete') is True for r in terminal.values()),
            stop_known=sum(r.get('stop_known') is True for r in stops.values()),
            verified_stopped=sum(r.get('verified_stopped') is True for r in stops.values())),clock_basis='hub_monotonic',interval_scope='client_observation_not_compute_or_acoustic',
        metrics={k:distribution(v) for k,v in metrics.items()},
        stt_by_outcome={k:dict(events=stt_counts[k],intervals=distribution(v)) for k,v in stt_groups.items()},
        main_outcomes={k:sum(row.get('disposition')==k for row in checked.values()) for k in ('ready','discarded','failed')},
        main_request_scopes={k:sum(row.get('disposition')==k for row in requests.values()) for k in ('audio_linked','metadata_only')},
        stale_stt_dispositions=sum(row['kind']=='stt_disposition' and row.get('disposition')=='stale' for row in events))


def analyze_status(rows):
    if rows is None:return dict(state='missing')
    rows=[row for row in rows if row.get('kind','status')=='status']
    counters={key:0 for key in COUNTERS};pairs=Counter();previous={};identity=None;segments=0;unknown=0;last_elapsed=None;resets=0
    maxima=[];elapsed=[];rtt=[];progress=[];queue=[];latest={};active=invalid=stale=0
    first_invalid=first_expiry=None;poll_outcomes=Counter();seen_snapshots=set();repeated=0;pressure_max={};timing_max={};pressure_phases=Counter()
    for row in rows:
        begin,end=row.get('hub_request_begin'),row.get('hub_request_end')
        if number(begin) and number(end) and end>=begin:
            rtt.append(end-begin)
            outcome=row.get('poll_outcome') if row.get('poll_outcome') in ('response','timeout','error','identity_changed','oversize') else ('unavailable' if row.get('stage')=='unavailable' or row.get('error_class') is not None else 'response')
            poll_outcomes[outcome]+=1
        else:poll_outcomes['missing_interval']+=1
        if row.get('first_reducer_expiry') or row.get('first_lease_invalid'):invalid+=1
        first_invalid=first_invalid or project_first_lease_invalid(row.get('first_lease_invalid'))
        first_expiry=first_expiry or project_first_reducer_expiry(row.get('first_reducer_expiry'))
        peer=row.get('peer');peer=peer if type(peer) is dict else {}
        source=peer.get('source_boot');binding=row.get('session_binding')
        current=source
        if binding is not None:
            candidate=row.get('candidate')
            if (type(binding) is dict and set(binding)=={'controller','source_boot','session_boot'} and all(identifier(v) for v in binding.values())
                    and binding['source_boot']==source and type(candidate) is str and len(candidate)==40 and all(c in '0123456789abcdef' for c in candidate)):
                current=(candidate,binding['controller'],source,binding['session_boot'])
            else:current=None
        if current is None or (type(current) is not tuple and not identifier(current)):unknown+=1;previous={};identity=None;last_elapsed=None;continue
        if current!=identity:segments+=1;previous={};identity=current;last_elapsed=None;seen_snapshots.clear()
        current_elapsed=row.get('elapsed_s')
        if number(current_elapsed):
            if last_elapsed is not None and current_elapsed<last_elapsed:
                segments+=1;resets+=1;previous={};seen_snapshots.clear()
            last_elapsed=current_elapsed
        if row.get('stage')=='ACTIVE':active+=1
        snapshot=(current,current_elapsed)
        if number(current_elapsed) and snapshot in seen_snapshots:repeated+=1;continue
        if number(current_elapsed):seen_snapshots.add(snapshot)
        speech=row.get('speech',{})
        if type(speech) is dict and speech.get('operator_receipt_fresh') is False:stale+=1
        if number(row.get('elapsed_s')):elapsed.append(row['elapsed_s'])
        lease=row.get('lease',{})
        if type(lease) is dict:
            if number(lease.get('max_tick_gap_ms')):maxima.append(lease['max_tick_gap_ms'])
            if number(lease.get('progress_age_ms')):progress.append(lease['progress_age_ms'])
            timing=lease.get('timing',{})
            for key in ('last_send_age_ms','last_accepted_age_ms','reducer_progress_age_ms','worker_scheduling_age_ms'):
                if type(timing) is dict and number(timing.get(key)):timing_max[key]=max(timing_max.get(key,0),timing[key])
        runtime=row.get('runtime',{})
        if type(runtime) is dict:
            latency=runtime.get('latency_s',{});pressure=runtime.get('pressure',{})
            if type(latency) is dict:
                for key in ('fast','main'):
                    if number(latency.get(key)):latest[key]=latency[key]
            if type(pressure) is dict:
                if number(pressure.get('queue_depth')):queue.append(pressure['queue_depth'])
                if pressure.get('phase') in ('ACTIVE','DRAINING','DEGRADED','RECOVERING','STOPPED'):pressure_phases[pressure['phase']]+=1
                ages=pressure.get('active_age_s',{})
                for key in ('fast','main','motion','context','maintenance','updates','audio'):
                    if type(ages) is dict and number(ages.get(key)):pressure_max[key]=max(pressure_max.get(key,0),ages[key])
        values=row.get('audio_counts',row.get('audio',{}).get('counts',{}) if type(row.get('audio')) is dict else {})
        if type(values) is not dict:values={}
        if any(key in previous and type(values.get(key)) is int and values[key]<previous[key] for key in COUNTERS):
            segments+=1;resets+=1;previous={}
        for key in COUNTERS:
            value=values.get(key)
            if type(value) is not int or not number(value):previous.pop(key,None);continue
            if key in previous:
                counters[key]+=value-previous[key];pairs[key]+=1
            previous[key]=value
    return dict(state='observed' if rows else 'empty',rows=len(rows),active_rows=active,
        invalid_snapshot_rows=invalid,stale_operator_rows=stale,identity_unknown_rows=unknown,
        counter_segments=segments,counter_resets=resets,repeated_snapshot_rows=repeated,pressure_phase_snapshots=dict(pressure_phases),sampled_active_age_max_s=pressure_max,sampled_lease_timing_max_ms=timing_max,audio_observed_deltas={k:v if pairs[k] else None for k,v in counters.items()},
        counter_interval_counts=dict(pairs),first_lease_invalid=first_invalid,first_reducer_expiry=first_expiry,
        last_job_latency_s=latest,job_latency_semantics='last_value_not_call_samples',
        sampled_progress_age_ms=dict(n=len(progress),max=max(progress,default=None)),
        sampled_queue_depth=dict(n=len(queue),max=max(queue,default=None)),
        sampled_session_elapsed_max_s=max(elapsed,default=None),max_tick_gap_ms=max(maxima,default=None),
        max_tick_gap_semantics='cumulative_max_not_samples',status_request_s=distribution(rtt),status_request_outcomes=dict(poll_outcomes),
        missing=['per_tick_distribution','per_job_latency_distribution','cpu_rss','acoustic_latency']
            +([] if queue else ['queue_depth'])+([] if progress else ['progress_age']))


def analyze_final(rows):
    if rows is None:return dict(state='missing')
    if len(rows)!=1:return dict(state='incomplete',reason='one_final_required')
    row=rows[0];trace=row.get('private_audio_trace',{});busy=row.get('execution_busy')
    known_busy=type(busy) is dict and bool(busy) and all(type(v) is bool for v in busy.values())
    control=row.get('control_transport',{});peer=row.get('peer_stop',{})
    return dict(state='observed',accepted=row.get('accepted') is True,
        cleanup_verified=row.get('cleanup_verified') is True,
        busy_known=known_busy,any_execution_busy=any(busy.values()) if known_busy else None,
        control_handlers=control.get('handlers') if type(control) is dict and type(control.get('handlers')) is int and number(control['handlers']) else None,
        peer_stop_known=peer.get('stop_known') if type(peer) is dict and type(peer.get('stop_known')) is bool else None,
        first_lease_invalid=project_first_lease_invalid(row.get('first_lease_invalid')),
        first_reducer_expiry=project_first_reducer_expiry(row.get('first_reducer_expiry')),
        elapsed_s=row.get('elapsed_s') if number(row.get('elapsed_s')) else None,
        trace_incomplete=trace.get('incomplete') if type(trace) is dict and type(trace.get('incomplete')) is bool else None)


def parse_proc_stat(text,*,pid,start_ticks,host_boot,at,user_hz,page_size):
    """Pure Linux /proc/PID/stat parser; caller owns before/after PID identity checks."""
    if (type(pid) is not int or pid<=0 or not identifier(host_boot) or not number(at)
            or type(user_hz) is not int or not 1<=user_hz<=10**9 or type(page_size) is not int or not 1<=page_size<=2**30):
        raise ValueError('resource_scope')
    try:
        prefix,rest=text.rsplit(')',1);actual_pid=int(prefix.split('(',1)[0].strip());fields=rest.split()
        ticks=int(fields[19]);cpu=int(fields[11])+int(fields[12]);rss=int(fields[21])*page_size
        if actual_pid!=pid or ticks!=start_ticks or not number(cpu) or not number(rss):raise ValueError('resource_identity')
    except (IndexError,TypeError,ValueError):raise ValueError('resource_stat') from None
    return dict(pid=pid,start_ticks=ticks,host_boot=host_boot,at=at,clock_basis='host_monotonic',
        cpu_s=cpu/user_hz,rss_bytes=rss)


def analyze_resources(rows):
    output={}
    allowed_roles=('hub_owner','robot_audio','mac_fast','mac_main','mac_stt','mac_tts','mac_embeddings','mac_provider','legacy')
    for node in ('hub','robot','mac'):
        selected=[r for r in rows or [] if r.get('node')==node and r.get('kind','resource')=='resource']
        instances={};unknown=0;states=Counter();prior_by_role={}
        for row in selected:
            role=row.get('role','legacy');state=row.get('sample_state','ok')
            state=state if state in ('ok','missing','identity_changed','timeout','unsupported','error') else 'error';states[state]+=1
            basis=row.get('identity_basis','linux_start_ticks')
            start=row.get('process_start_identity')
            if start is None and type(row.get('start_ticks')) is int:start=str(row['start_ticks'])
            scope=(role,row.get('host_boot'),row.get('pid'),basis,start)
            valid=(role in allowed_roles and identifier(scope[1]) and type(scope[2]) is int and scope[2]>0
                and basis in ('linux_start_ticks','mach_start_abstime') and type(start) is str and start.isdigit() and len(start)<=32
                and row.get('clock_basis')=='host_monotonic' and state=='ok'
                and all(number(row.get(k)) for k in ('at','cpu_s','rss_bytes')))
            if not valid:
                unknown+=1
                if role in allowed_roles and type(row.get('pid')) is int:prior_by_role.pop((role,row['pid']),None)
                else:prior_by_role.clear()
                continue
            item=instances.setdefault(scope,dict(role=role,identity_basis=basis,rows=0,cpu=[],rss=[]))
            item['rows']+=1;item['rss'].append(row['rss_bytes'])
            prior=prior_by_role.get((role,row['pid']))
            if prior is not None:
                before,old_scope=prior;dt=row['at']-before['at'];dc=row['cpu_s']-before['cpu_s']
                if scope==old_scope and dt>0 and dc>=0 and math.isfinite(100*dc/dt):item['cpu'].append(100*dc/dt)
                else:unknown+=1
            prior_by_role[(role,row['pid'])]=(row,scope)
        groups=[dict(instance=index,role=item['role'],identity_basis=item['identity_basis'],rows=item['rows'],
            cpu_percent_one_core=distribution(item['cpu']),rss_bytes=distribution(item['rss'])) for index,item in enumerate(instances.values(),1)]
        # Keep old single-instance report shape; never pool different workers/instances.
        single=groups[0] if len(groups)==1 else {}
        node_rows=[r for r in rows or [] if r.get('node')==node]
        footers=[r for r in node_rows if r.get('kind')=='observer_end']
        modern=any(r.get('kind')=='resource' for r in selected)
        completion=dict(state='unknown',footer_present=False,reason='legacy')
        if modern or footers:
            valid_footer=(len(footers)==1 and node_rows[-1] is footers[0] and footers[0].get('incomplete') is False
                and footers[0].get('reason') in ('complete','stopped')
                and type(footers[0].get('records')) is int and footers[0]['records']==len(node_rows)-1)
            reason=footers[0].get('reason') if len(footers)==1 else 'missing_footer' if not footers else 'multiple_footers'
            reason=reason if reason in ('complete','stopped','samples','io','cap','status_error','control','acquisition_failed','missing_footer','multiple_footers') else 'invalid_footer'
            completion=dict(state='complete' if valid_footer else 'incomplete',footer_present=bool(footers),reason=reason)
        state='observed' if instances else 'incomplete' if selected else 'missing'
        if completion['state']=='incomplete':state='incomplete'
        output[node]=dict(state=state,completion=completion,rows=len(selected),
            unknown_intervals=unknown,sample_states=dict(states),instances=groups,process_scope_only=True,
            cpu_percent_one_core=single.get('cpu_percent_one_core',distribution([])),rss_bytes=single.get('rss_bytes',distribution([])),
            coverage=dict(process_instances=len(groups),roles=sorted({g['role'] for g in groups}),
                usable_cpu_intervals=sum(g['cpu_percent_one_core']['n'] for g in groups),host_total=False,gpu=False,rss_unique_total=False))
    return output


def report(trace,status,final,candidate,resources=None):
    if len(candidate)!=40 or any(c not in '0123456789abcdef' for c in candidate):raise ValueError('candidate_sha_required')
    return dict(version=1,candidate=candidate,mode='offline',hardware_started=False,
        trace=analyze_trace(trace),status=analyze_status(status),final=analyze_final(final),resources=analyze_resources(resources),
        population_tail_claim=False,clock_alignment_verified=False)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate',required=True)
    for name in ('trace','status','final','resources'):parser.add_argument('--'+name,type=Path)
    parser.add_argument('--dry-run',action='store_true',help='Validate arguments and show plan without opening inputs')
    args=parser.parse_args(argv)
    try:
        if args.dry_run:
            value=report(None,None,None,args.candidate);value['mode']='dry_run'
        else:value=report(read_rows(args.trace,trace=True),read_rows(args.status),read_rows(args.final,final=True),args.candidate,read_rows(args.resources))
    except (ValueError,OSError):
        # Never reflect filenames, malformed values or source text in public output.
        print(json.dumps(dict(mode='offline',state='invalid_input')));return 2
    print(json.dumps(value,allow_nan=False,sort_keys=True,indent=2));return 0


if __name__=='__main__':raise SystemExit(main())
