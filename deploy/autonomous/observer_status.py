"""Allowlisted projection of an existing status response; no new runtime endpoint."""
from production_baseline import number,identifier,COUNTERS
from reachy_companion.lease_diagnostics import project_first_lease_invalid,project_first_reducer_expiry

TIMING=('last_send_age_ms','last_accepted_age_ms','reducer_progress_age_ms','worker_scheduling_age_ms')
LEASE=('progress_age_ms','max_tick_gap_ms','max_worker_scheduling_gap_ms','max_call_ms','calls','errors')
JOBS=('fast','main','motion','context','maintenance','updates','audio')
BUSY=JOBS+('actor','context_revoke','peer_status','health','peer_stop','retirement','media_close','context_terminal_revoke','speech','peer_poll','lease','background')
PHASES=('ACTIVE','DRAINING','DEGRADED','RECOVERING','STOPPED','STARTING')


def numeric(value,keys):
    if type(value) is not dict:return {}
    return {k:value[k] for k in keys if number(value.get(k))}


def project_status(value,*,candidate,binding,begin,end,outcome='response'):
    if not (type(candidate) is str and len(candidate)==40 and all(c in '0123456789abcdef' for c in candidate)):raise ValueError('candidate')
    if type(binding) is not dict or set(binding)!={'controller','source_boot','session_boot'} or not all(identifier(v) for v in binding.values()):raise ValueError('binding')
    if not number(begin) or not number(end) or end<begin:raise ValueError('interval')
    if outcome not in ('response','timeout','error','identity_changed','oversize'):raise ValueError('outcome')
    row=dict(version=1,kind='status',candidate=candidate,clock_basis='host_monotonic',
        hub_request_begin=begin,hub_request_end=end,poll_outcome=outcome,session_binding=dict(binding))
    if outcome!='response':return dict(row,stage='unavailable')
    if type(value) is not dict or any(value.get(k)!=v for k,v in binding.items()):return dict(row,poll_outcome='identity_changed',stage='unavailable')
    row.update(numeric(value,('elapsed_s',)));row['stage']=value.get('stage') if value.get('stage') in PHASES else 'unknown'
    peer=value.get('peer');peer=peer if type(peer) is dict else {}
    row['peer']={'source_boot':binding['source_boot']}
    row['lease']=numeric(value.get('lease'),LEASE)
    lease=value.get('lease');lease=lease if type(lease) is dict else {}
    row['lease']['timing']=numeric(lease.get('timing'),TIMING)
    row['first_lease_invalid']=project_first_lease_invalid(value.get('first_lease_invalid'))
    row['first_reducer_expiry']=project_first_reducer_expiry(value.get('first_reducer_expiry'))
    runtime=value.get('runtime');runtime=runtime if type(runtime) is dict else {}
    pressure=runtime.get('pressure');pressure=pressure if type(pressure) is dict else {}
    clean_pressure=numeric(pressure,('queue_depth','queue_limit','latency_limit_s','elapsed_s'))
    if pressure.get('phase') in PHASES:clean_pressure['phase']=pressure['phase']
    clean_pressure['active_age_s']=numeric(pressure.get('active_age_s'),JOBS)
    row['runtime']=dict(latency_s=numeric(runtime.get('latency_s'),('fast','main')),pressure=clean_pressure)
    busy=value.get('execution_busy');row['execution_busy']={k:busy[k] for k in BUSY if type(busy) is dict and type(busy.get(k)) is bool}
    audio=value.get('audio');audio=audio if type(audio) is dict else {}
    row['audio_counts']=numeric(audio.get('counts'),COUNTERS)
    speech=value.get('speech');speech=speech if type(speech) is dict else {}
    row['speech']={k:speech[k] for k in ('operator_receipt_fresh','execution_busy','stop_known') if type(speech.get(k)) is bool}
    return row
