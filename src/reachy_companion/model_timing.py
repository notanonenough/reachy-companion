"""Finite numeric diagnostics for one existing model call; never model policy."""
import hashlib
import json
import math
import re
import time

STAGES=('tokenize_text','tokenize_prompt','completion','validation','backend_total',
        'gateway_total','handler_to_pre_serialize')
USAGE=('input_tokens','text_tokens','template_tokens','output_reserved','output_tokens')
COUNTS=('cache_n','prompt_n','predicted_n')
MILLISECONDS=('prompt_ms','predicted_ms')
TOP_COUNTS=('tokens_evaluated','tokens_cached','tokens_predicted')
HASHES=('model_id_sha256','weight_sha256','tokenizer_sha256','template_sha256','config_sha256')
SETTINGS=('context_tokens','admission_context_tokens','input_cap_tokens','template_cap_tokens',
          'output_tokens','reserve_tokens','temperature','structured_reply','completion_backend',
          'tokenizer_backend','message_template','assistant_prefix','stop')


def stamp():
    try:return time.monotonic()
    except Exception:return None


def number(value, ceiling):
    return type(value) in (int,float) and math.isfinite(value) and 0<=value<=ceiling


def count(value):
    return type(value) is int and 0<=value<=10000000


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,
        allow_nan=False,separators=(',',':')).encode()).hexdigest()


def project(value, *, request_id=None, gateway_boot_id=None):
    """Fresh bounded copy. Invalid diagnostic input cannot invalidate inference."""
    result=dict(version=1,clock_basis='gateway_monotonic',incomplete=False,
        reason=None,request_id=None,gateway_boot_id=None,backend=None,build=None,
        stages={name:dict(state='missing',duration_s=None) for name in STAGES},
        usage={name:None for name in USAGE},reported_native={},ttft_s=None,cache_hit=None)
    for name in (*COUNTS,*MILLISECONDS,*TOP_COUNTS):
        result['reported_native']['reported_'+name]=None
    for name in HASHES:result[name]=None
    try:
        if type(value) is not dict or type(value.get("version")) is not int or value.get("version")!=1 or value.get("clock_basis")!="gateway_monotonic":raise ValueError
        for name,expected in (('request_id',request_id),('gateway_boot_id',gateway_boot_id)):
            item=value.get(name)
            if type(item) is not str or not 1<=len(item)<=128 or not re.fullmatch(r'[A-Za-z0-9_.:-]+',item):raise ValueError
            if expected is not None and item!=expected:raise ValueError
            result[name]=item
        result['backend']=value.get('backend') if value.get('backend') in ('llama_native','lmstudio_sdk','completion_http') else None
        build=value.get('build')
        if type(build) is str and re.fullmatch(r'[A-Za-z0-9_. /+-]{1,128}',build):result['build']=build
        for name in HASHES:
            item=value.get(name)
            if type(item) is str and re.fullmatch('[a-f0-9]{64}',item):result[name]=item
            else:result['incomplete']=True
        if result['backend'] is None or result['build'] is None:result['incomplete']=True
        stages=value.get('stages',{})
        for name in STAGES:
            stage=stages.get(name) if type(stages) is dict else None
            if type(stage) is dict and stage.get('state')=='complete' and number(stage.get('duration_s'),3600):
                result['stages'][name]=dict(state='complete',duration_s=stage['duration_s'])
            else:
                state='failed' if type(stage) is dict and stage.get('state')=='failed' else 'missing'
                result['stages'][name]=dict(state=state,duration_s=None)
                result['incomplete']=True
        usage=value.get('usage',{})
        if type(usage) is not dict:result['incomplete']=True
        for name in USAGE:
            item=usage.get(name) if type(usage) is dict else None
            if count(item):result['usage'][name]=item
            elif item is not None:result['incomplete']=True
        native=value.get('reported_native',{})
        if type(native) is not dict:result['incomplete']=True
        for name in (*COUNTS,*MILLISECONDS,*TOP_COUNTS):
            key='reported_'+name;item=native.get(key) if type(native) is dict else None
            if (number(item,3600000) if name in MILLISECONDS else count(item)):
                result['reported_native'][key]=item
            elif item is not None:result['incomplete']=True
        if value.get('incomplete') is True:result['incomplete']=True
        if result['incomplete']:result['reason']='partial_or_invalid'
    except Exception:
        # Never retain an unverified causal identity or any arbitrary fields.
        result['request_id']=result['gateway_boot_id']=None
        result['incomplete']=True;result['reason']='invalid_receipt'
    return result


class Timing:
    def __init__(self,model,clock=None):
        self.clock=clock or time.monotonic;self.active={};self.value={}
        try:
            audit=model.get('audit',{})
            self.value=dict(version=1,clock_basis='gateway_monotonic',backend=model.get('completion_backend','completion_http'),
                build=audit.get('runtime_build'),model_id_sha256=digest(model.get('id')),
                config_sha256=digest({k:model[k] for k in SETTINGS if k in model}),
                stages={},usage={},reported_native={},
                **{k:audit.get(k) for k in HASHES if k not in ('model_id_sha256','config_sha256')})
            self.start('backend_total')
        except Exception:self.value={'incomplete':True,'stages':{}}
    def start(self,name):
        try:self.active[name]=self.clock()
        except Exception:self.value['incomplete']=True
    def end(self,name,failed=False):
        try:
            began=self.active.pop(name)
            elapsed=self.clock()-began
            self.value['stages'][name]=dict(state='failed' if failed else 'complete',duration_s=None if failed else elapsed)
        except Exception:self.value['incomplete']=True
    def call(self,name,function,*args,**kwargs):
        self.start(name)
        try:result=function(*args,**kwargs)
        except BaseException:self.end(name,True);raise
        self.end(name);return result
    def usage(self,**values):
        try:self.value["usage"].update({k:v for k,v in values.items() if k in USAGE})
        except Exception:self.value["incomplete"]=True
    def native(self,response):
        try:
            if type(response) is not dict:return
            timings=response.get('timings',{})
            if type(timings) is not dict:self.value['incomplete']=True
            self.value['reported_native']={
                **{'reported_'+k:timings.get(k) for k in (*COUNTS,*MILLISECONDS) if type(timings) is dict and k in timings},
                **{'reported_'+k:response[k] for k in TOP_COUNTS if k in response}}
        except Exception:self.value['incomplete']=True
    def finish(self,result=None,error=None):
        for name in tuple(self.active):self.end(name,error is not None)
        try:
            if type(result) is dict:self.value['usage']=result.get('usage',{})
            if error is not None:setattr(error,'model_timing',self.value)
            elif type(result) is dict:result['model_timing']=self.value
        except Exception:pass


def bind(value,request_id,boot_id,stage,began,*,failed=False):
    try:
        raw=dict(value) if type(value) is dict else {}
        raw.update(version=1,clock_basis='gateway_monotonic',request_id=request_id,gateway_boot_id=boot_id)
        raw['stages']={**raw.get('stages',{}),stage:dict(state='failed' if failed else 'complete',
            duration_s=None if failed else time.monotonic()-began)}
        return raw
    except Exception:return project(None)


def attach_error(error,receipt):
    try:error.model_timing=receipt
    except Exception:pass
