"""Content-free projection shared by live, final and installed-host diagnostics."""


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
