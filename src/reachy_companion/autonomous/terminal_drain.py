"""Content-free terminal snapshot; never cancels, consumes or replaces work."""
import math


# Best-effort grace from cleanup entry, leaving margin to the supervisor's 10s
# fallback. Close operations themselves may overrun; this is not a hard deadline
# for threads, transport, physical STOP, or the whole process.
TERMINAL_GRACE_S=8.0


def snapshot(started,now,busy,jobs):
    remaining=[]
    for slot,job in jobs:
        if job and not job.future.done():
            age=now-job.started
            remaining.append(dict(slot=slot,age_s=age if math.isfinite(age) and age>=0 else None))
    represented={row['slot'] for row in remaining}
    for slot,active in busy.items():
        if active and slot not in represented and not (slot=='background' and any(name.startswith('background.') for name in represented)):
            # Adapter-owned threads do not expose a start receipt. Do not invent
            # an age or use the age of a previous thread occupying the same slot.
            remaining.append(dict(slot=slot,age_s=None))
    return dict(budget_s=TERMINAL_GRACE_S,elapsed_s=now-started,
        overrun=now-started>TERMINAL_GRACE_S,completed=not any(busy.values()) and not remaining,
        remaining_count=len(remaining),remaining=remaining[:32],truncated=len(remaining)>32)


def project(value):
    """Standalone whitelist also used by the installed-status reader."""
    import math
    if not isinstance(value,dict):return None
    def number(v):return v if type(v) in (int,float) and math.isfinite(v) and v>=0 else None
    fixed={'fast','main','actor','motion','context','context_revoke','context_terminal_revoke',
        'peer_status','health','peer_stop','retirement','media_close','audio','speech','peer_poll','lease','background',
        'background.maintenance','background.update'}
    result={key:number(value.get(key)) for key in ('budget_s','elapsed_s')}
    result.update({key:value.get(key) if type(value.get(key)) is bool else None for key in ('completed','overrun','truncated')})
    count=value.get('remaining_count');result['remaining_count']=count if type(count) is int and 0<=count<=1000000 else None
    rows=value.get('remaining');result['remaining']=[]
    for row in rows[:32] if isinstance(rows,list) else []:
        if not isinstance(row,dict):continue
        slot=row.get('slot')
        if not isinstance(slot,str):continue
        parts=slot.split(':')
        indexed=(len(parts)==2 and parts[0] in ('background.poll','background.export','background.tool')
            and parts[1].isascii() and parts[1].isdigit() and len(parts[1])<=6)
        if slot in fixed or indexed:result['remaining'].append(dict(slot=slot,age_s=number(row.get('age_s'))))
    return result
