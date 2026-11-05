"""Single-head causal attention with fixed weights; not a pretrained language model."""
from dataclasses import dataclass, field
import hashlib
import json
import math
import platform
import random
import statistics
import time
D=8
rng=random.Random(17)
EMBED=[[rng.uniform(-1,1) for _ in range(D)] for _ in range(12)]
WEIGHTS=[[[rng.uniform(-.3,.3) for _ in range(D)] for _ in range(D)] for _ in range(3)]
MODEL_ID=hashlib.sha256(json.dumps([EMBED,WEIGHTS]).encode()).hexdigest()
def dot(a,b): return math.fsum(x*y for x,y in zip(a,b))
def project(x,w): return [dot(row,x) for row in w]
def qkv(token,position):
    if type(token) is not int or not 0<=token<len(EMBED): raise ValueError("invalid token ID")
    x=[v+math.sin(position/(10000**(i/D))) for i,v in enumerate(EMBED[token])]
    return [project(x,w) for w in WEIGHTS]
def attend(q,keys,values):
    scores=[dot(q,k)/math.sqrt(D) for k in keys]
    largest=max(scores); weights=[math.exp(x-largest) for x in scores]
    total=math.fsum(weights); weights=[x/total for x in weights]
    return [math.fsum(a*v[i] for a,v in zip(weights,values)) for i in range(D)]
def full(tokens):
    if not tokens: raise ValueError("empty prefix")
    projected=[qkv(t,p) for p,t in enumerate(tokens)]
    return [attend(row[0],[r[1] for r in projected[:p+1]],
                   [r[2] for r in projected[:p+1]]) for p,row in enumerate(projected)]
@dataclass
class Cache:
    model_id: str = MODEL_ID
    keys: list = field(default_factory=list)
    values: list = field(default_factory=list)
    tokens: list = field(default_factory=list)
def step(cache,token,position):
    if cache.model_id != MODEL_ID: raise ValueError("cache belongs to another model")
    if position != len(cache.tokens): raise ValueError("cache position mismatch")
    q,k,v=qkv(token,position)
    cache.keys.append(k);cache.values.append(v);cache.tokens.append(token)
    return attend(q,cache.keys,cache.values)
def next_token(state): return max(range(len(EMBED)),key=lambda i:dot(state,EMBED[i]))
def generate(prefix,steps,cached):
    if not prefix or steps<1: raise ValueError("nonempty prefix and positive steps required")
    tokens=list(prefix);cache=Cache();position=0;projected_rows=0;score_cells=0
    for _ in range(steps):
        if cached:
            while position<len(tokens):
                state=step(cache,tokens[position],position)
                position+=1;projected_rows+=1;score_cells+=position
        else:
            state=full(tokens)[-1];n=len(tokens)
            projected_rows+=n;score_cells+=n*(n+1)//2
        tokens.append(next_token(state))
    return {"tokens":tokens,"projected_token_rows":projected_rows,
            "attention_score_cells":score_cells,"cached_positions":len(cache.tokens)}
def workload_sweep():
    """Compare deterministic work for fixed, predeclared serving workloads."""
    rows=[]
    for prompt_tokens,new_tokens in ((8,8),(32,8),(8,32),(32,32)):
        prefix=[i%len(EMBED) for i in range(prompt_tokens)]
        uncached=generate(prefix,new_tokens,False)
        cached=generate(prefix,new_tokens,True)
        rows.append({"prompt_tokens":prompt_tokens,"new_tokens":new_tokens,
                     "identical_tokens":uncached["tokens"]==cached["tokens"],
                     "uncached_rows":uncached["projected_token_rows"],
                     "cached_rows":cached["projected_token_rows"],
                     "uncached_score_cells":uncached["attention_score_cells"],
                     "cached_score_cells":cached["attention_score_cells"],
                     "retained_kv_floats":2*D*cached["cached_positions"]})
    return rows

def report():
    prefix=[1,4,2,9,3,5,8,7];steps=8;records={}
    for mode in [False,True]:
        times=[]
        for _ in range(15):
            start=time.perf_counter();result=generate(prefix,steps,mode)
            times.append((time.perf_counter()-start)*1000)
        records['cached' if mode else 'uncached']={**result,"median_ms":round(statistics.median(times),3)}
    return {"implementation":"fixed-weight single attention layer; CPU Python lists",
            "python":platform.python_version(),"platform":platform.platform(),
            "model_sha256":MODEL_ID,"prompt_tokens":len(prefix),"generated_tokens":steps,
            "timing_repetitions":15,"results":records,"workload_sweep":workload_sweep(),
            "identical_tokens":records['cached']['tokens']==records['uncached']['tokens']}
if __name__ == '__main__': print(json.dumps(report(),indent=2,sort_keys=True))
