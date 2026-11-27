"""Bounded source endpoint metadata; never speaker identity or authority."""
import re


def segment(value, samples=None):
    keys={'version','turn_id','segment_index','end_reason','final','sample_start','sample_end','clock_basis'}
    if (type(value) is not dict or set(value)!=keys or type(value['version']) is not int or value['version']!=1
            or type(value['turn_id']) is not str or not re.fullmatch('[a-f0-9]{32}',value['turn_id'])
            or type(value['segment_index']) is not int or not 0<=value['segment_index']<3
            or value['end_reason'] not in ('deadline','silence') or type(value['final']) is not bool
            or value['final']!=(value['end_reason']=='silence')
            or value['clock_basis']!='source_capture_samples'
            or any(type(value[k]) is not int or not 0<=value[k]<2**63 for k in ('sample_start','sample_end'))
            or not 0<value['sample_end']-value['sample_start']<=128000
            or samples is not None and value['sample_end']-value['sample_start']!=samples):
        raise ValueError('Typed contiguous endpoint segment required')
    return dict(value)
