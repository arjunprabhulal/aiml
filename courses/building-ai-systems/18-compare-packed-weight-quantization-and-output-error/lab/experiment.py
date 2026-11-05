"""Actual CPU weight quantization and token-step scheduling experiments.

The scheduler uses logical arrival ticks, not measured network latency.
"""
import copy
import json
import math
from pathlib import Path
import torch
import torch.nn.functional as F
import decoder
from bpe import Tokenizer

HERE=Path(__file__).resolve().parent
MATRICES=['Wq','Wk','Wv','Wo','W1','W2','W_out']


def parameters():
    raw=json.loads((HERE/'params.json').read_text())
    decoder.CONFIG['d']=len(raw['tok_emb'][0])
    return {name:torch.tensor(value,dtype=torch.float64) for name,value in raw.items()}


def quantize(weight,bits):
    if bits not in (4,8) or weight.ndim!=2 or min(weight.shape)<1 or not torch.isfinite(weight).all():
        raise ValueError('finite matrix and 4 or 8 bits required')
    qmax=2**(bits-1)-1
    maximum=weight.abs().amax(1)
    scales=torch.where(maximum==0,torch.ones_like(maximum),maximum/qmax)
    q=(weight/scales[:,None]).round().clamp(-qmax,qmax).to(torch.int8)
    if bits==8:
        payload=bytes(q.view(torch.uint8).flatten().tolist())
    else:
        shifted=(q.flatten().to(torch.int16)+8).to(torch.uint8)
        if len(shifted)%2:shifted=torch.cat((shifted,torch.tensor([8],dtype=torch.uint8)))
        payload=bytes((shifted[::2] | (shifted[1::2]<<4)).tolist())
    return {'bits':bits,'shape':list(weight.shape),'scales':scales.tolist(),'payload_hex':payload.hex()}


def dequantize(artifact):
    bits=artifact['bits'];rows,cols=artifact['shape']
    if bits not in (4,8) or type(rows) is not int or type(cols) is not int or rows<1 or cols<1:
        raise ValueError('invalid quantized shape or width')
    scales=torch.tensor(artifact['scales'],dtype=torch.float64)
    if scales.shape!=(rows,) or not torch.isfinite(scales).all() or (scales<=0).any():
        raise ValueError('invalid row scales')
    data=bytearray.fromhex(artifact['payload_hex'])
    required=rows*cols if bits==8 else (rows*cols+1)//2
    if len(data)!=required:raise ValueError('quantized payload size mismatch')
    packed=torch.tensor(list(data),dtype=torch.uint8)
    if bits==8:q=packed.view(torch.int8).to(torch.float64)
    else:q=torch.stack((packed&15,packed>>4),1).flatten()[:rows*cols].to(torch.float64)-8
    return q.reshape(rows,cols)*scales[:,None]


def batched_logits(p,sequences):
    if not sequences:raise ValueError('nonempty batch required')
    for ids in sequences:decoder.inputs(p,ids,[0]*len(ids))
    length=max(map(len,sequences));d=p['tok_emb'].shape[1]
    ids=torch.zeros((len(sequences),length),dtype=torch.long)
    sizes=torch.tensor([len(s) for s in sequences])
    for i,sequence in enumerate(sequences):ids[i,:len(sequence)]=torch.tensor(sequence)
    x=p['tok_emb'][ids]+p['pos_emb'][:length]
    norm=lambda value,name:F.layer_norm(value,(d,),p[name+'_g'],p[name+'_b'],eps=decoder.model.EPS)
    h=norm(x,'ln1');q,k,v=(h@p[name] for name in ['Wq','Wk','Wv'])
    scores=(q@k.transpose(-1,-2))/math.sqrt(d)
    causal=torch.ones(length,length,dtype=torch.bool).tril()
    valid=torch.arange(length)[None,:]<sizes[:,None]
    allowed=causal[None,:,:]&valid[:,None,:]
    mixed=scores.masked_fill(~allowed,float('-inf')).softmax(-1)@v
    x=x+mixed@p['Wo'];h=norm(x,'ln2')
    x=x+F.relu(h@p['W1']+p['b1'])@p['W2']+p['b2']
    logits=norm(x,'lnf')@p['W_out']+p['b_out']
    return torch.stack([logits[i,n-1] for i,n in enumerate(sizes)])


def schedule(p,jobs,continuous=True,capacity=2):
    if type(capacity) is not int or capacity<1:raise ValueError('positive capacity required')
    if not isinstance(jobs,list) or not jobs or len(jobs)>64:
        raise ValueError('1..64 jobs required')
    if any(not isinstance(job,dict) or set(job)!={'id','arrival','prompt','tokens'} or not isinstance(job['id'],str) or not job['id'] for job in jobs):
        raise ValueError('named jobs with arrival, prompt and tokens required')
    if len({job['id'] for job in jobs})!=len(jobs):raise ValueError('unique job IDs required')
    for job in jobs:
        if type(job['arrival']) is not int or job['arrival']<0 or type(job['tokens']) is not int or job['tokens']<1:
            raise ValueError('nonnegative arrival and positive token budget required')
        decoder.inputs(p,job['prompt'],[0]*len(job['prompt']))
        if len(job['prompt'])+job['tokens']>len(p['pos_emb']):raise ValueError('context budget exceeded')
    pending=sorted(copy.deepcopy(jobs),key=lambda j:(j['arrival'],j['id']));active=[];done=[];ticks=[];tick=0
    with torch.no_grad():
        while pending or active:
            if continuous or not active:
                while pending and pending[0]['arrival']<=tick and len(active)<capacity:
                    job=pending.pop(0);job['generated']=[];job['admitted']=tick;active.append(job)
            if not active:
                tick=pending[0]['arrival'];continue
            logits=batched_logits(p,[j['prompt']+j['generated'] for j in active])
            tokens=logits.argmax(-1).tolist();ticks.append({'tick':tick,'active':[j['id'] for j in active]})
            keep=[]
            for job,token in zip(active,tokens):
                job['generated'].append(token)
                if len(job['generated'])==job['tokens']:
                    job['finished']=tick+1;done.append(job)
                else:keep.append(job)
            active=keep;tick+=1
    return {'policy':'continuous admission' if continuous else 'fixed batch until all finish',
            'capacity':capacity,'logical_ticks':tick,'batch_forward_calls':len(ticks),
            'jobs':sorted(done,key=lambda j:j['id']),'trace':ticks}


def quantization_run():
    p=parameters();tok=Tokenizer.load(HERE/'tokenizer.json');text='mia has a red hat.';ids=tok.encode(text)
    baseline,_=decoder.forward(p,ids,[0]*len(ids));rows=[]
    full=sum(value.numel()*value.element_size() for value in p.values())
    for bits in [8,4]:
        changed={name:value.clone() for name,value in p.items()};packed={}
        for name in MATRICES:
            packed[name]=quantize(p[name],bits);changed[name]=dequantize(packed[name])
        logits,_=decoder.forward(changed,ids,[0]*len(ids))
        payload=sum(len(bytes.fromhex(a['payload_hex']))+len(a['scales'])*8 for a in packed.values())
        untouched=sum(value.numel()*value.element_size() for name,value in p.items() if name not in MATRICES)
        rows.append({'bits':bits,'selected_matrices':MATRICES,'numeric_model_payload_bytes':payload+untouched,
                     'packed_matrix_bytes':payload,'unquantized_parameter_bytes':untouched,
                     'serialized_quantized_artifacts_bytes':len(json.dumps(packed).encode()),
                     'max_logit_error':(logits-baseline).abs().max().item(),
                     'changed_argmax_positions':int((logits.argmax(-1)!=baseline.argmax(-1)).sum()),
                     'positions':len(ids)})
    return {'mode':'actual local CPU quantization, packing and dequantized inference on an existing trained checkpoint',
            'input_text':text,'input_ids':ids,'full_precision_payload_bytes':full,'results':rows,
            'scope':'Selected linear matrices only; scales remain float64. No integer kernel, AWQ, GPU speed or quality benchmark.'}


def batching_run():
    p=parameters();tok=Tokenizer.load(HERE/'tokenizer.json')
    jobs=[{'id':'a','arrival':0,'prompt':tok.encode('mia has'),'tokens':2},
          {'id':'b','arrival':0,'prompt':tok.encode('zoe has'),'tokens':5},
          {'id':'c','arrival':0,'prompt':tok.encode('ben has'),'tokens':1}]
    fixed=schedule(p,jobs,False);continuous=schedule(p,jobs,True)
    same=[j['generated'] for j in fixed['jobs']]==[j['generated'] for j in continuous['jobs']]
    if not same:raise AssertionError('scheduling changed deterministic output')
    return {'mode':'actual local CPU batched token decoding under authored logical arrival ticks',
            'fixed':fixed,'continuous':continuous,'outputs_equal':same,
            'scope':'Logical ticks are not wall-clock latency or throughput. Full-prefix recomputation; no paged KV cache or vLLM claim.'}
