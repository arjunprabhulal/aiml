"""Full and LoRA updates of a small softmax text classifier, on CPU without an SDK."""
from pathlib import Path
import copy
import hashlib
import json
import math
import random
VOCAB=['deploy','release','rollback','restore','token','credential','rotate','stage','revert','key']
LABELS=['deployment','rollback','credentials']
D=len(VOCAB)
C=len(LABELS)
def features(text):
    import re
    words=set(re.findall(r'[a-z]+',text.lower()))
    return [float(word in words) for word in VOCAB]
def softmax(values):
    top=max(values);raw=[math.exp(v-top) for v in values];total=math.fsum(raw)
    return [v/total for v in raw]
def dot(a,b): return math.fsum(x*y for x,y in zip(a,b))
def base_weights():
    w=[[0.0]*D for _ in LABELS]
    for word,label in [('deploy','deployment'),('release','deployment'),('rollback','rollback'),('token','credentials')]:
        w[LABELS.index(label)][VOCAB.index(word)]=1.5
    return w
class Model:
    def __init__(self,base,rank=None):
        if rank is not None and not 1<=rank<=min(C,D): raise ValueError('rank must be between 1 and 3')
        self.base=copy.deepcopy(base);self.rank=rank;self.w=copy.deepcopy(base)
        rng=random.Random(31)
        self.a=[[rng.uniform(-.1,.1) for _ in range(D)] for _ in range(rank or 0)]
        self.b=[[0.0]*(rank or 0) for _ in range(C)]
    def effective(self):
        if self.rank is None: return self.w
        return [[self.base[c][d]+math.fsum(self.b[c][r]*self.a[r][d] for r in range(self.rank))
                 for d in range(D)] for c in range(C)]
    def predict(self,x): return softmax([dot(row,x) for row in self.effective()])
    def train(self,rows,epochs=200,lr=.12):
        for _ in range(epochs):
            for row in rows:
                x=features(row['text']);y=LABELS.index(row['label']);p=self.predict(x)
                grad=[prob-(c==y) for c,prob in enumerate(p)]
                if self.rank is None:
                    for c in range(C):
                        for d in range(D): self.w[c][d]-=lr*grad[c]*x[d]
                else:
                    hidden=[dot(a,x) for a in self.a]
                    # Both gradients use the same pre-update A and B.
                    back=[math.fsum(self.b[c][r]*grad[c] for c in range(C)) for r in range(self.rank)]
                    for c in range(C):
                        for r in range(self.rank): self.b[c][r]-=lr*grad[c]*hidden[r]
                    for r in range(self.rank):
                        for d in range(D): self.a[r][d]-=lr*back[r]*x[d]
    @property
    def trainable(self): return C*D if self.rank is None else self.rank*(C+D)
def evaluate(model,rows):
    correct=0;loss=0.0;predictions=[]
    for row in rows:
        p=model.predict(features(row['text']));target=LABELS.index(row['label']);guess=max(range(C),key=lambda i:p[i])
        correct+=guess==target;loss-=math.log(max(p[target],1e-15))
        predictions.append({'id':row['id'],'expected':row['label'],'predicted':LABELS[guess]})
    return {'correct':correct,'total':len(rows),'mean_cross_entropy':round(loss/len(rows),6),'predictions':predictions}
def validate_split(train,test):
    if not train or not test: raise ValueError('both splits required')
    if set(r['text'].strip().lower() for r in train)&set(r['text'].strip().lower() for r in test):
        raise ValueError('duplicate text across splits')
    if {tuple(features(r['text'])) for r in train}&{tuple(features(r['text'])) for r in test}:
        raise ValueError('duplicate model input across splits')
    for row in train+test:
        if row['label'] not in LABELS: raise ValueError('unknown label')
        if not any(features(row['text'])): raise ValueError('text has no known feature')
def experiment():
    root=Path(__file__).parent
    train=json.loads((root/'train.json').read_text());test=json.loads((root/'heldout.json').read_text())
    validate_split(train,test);base=base_weights();baseline=Model(base);results={}
    for name,rank in [('full',None),('lora_rank_1',1),('lora_rank_2',2)]:
        model=Model(base,rank);model.train(train)
        results[name]={'trainable_parameters':model.trainable,'train':evaluate(model,train),'heldout':evaluate(model,test),
                       'base_unchanged':model.base==base}
    return {'task':'small bag-of-words intent classifier; not a pretrained LLM','seed':31,'epochs':200,'learning_rate':.12,
            'base_sha256':hashlib.sha256(json.dumps(base).encode()).hexdigest(),
            'train_sha256':hashlib.sha256((root/'train.json').read_bytes()).hexdigest(),
            'heldout_sha256':hashlib.sha256((root/'heldout.json').read_bytes()).hexdigest(),
            'evaluation_feature_duplicates':sum(tuple(features(row['text'])) in {tuple(features(t['text'])) for t in train} for row in test),
            'baseline':evaluate(baseline,test),'results':results}
if __name__ == '__main__':print(json.dumps(experiment(),indent=2,sort_keys=True))
