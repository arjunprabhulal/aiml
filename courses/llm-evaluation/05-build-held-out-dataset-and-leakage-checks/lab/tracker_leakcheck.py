"""Check tracker eval splits. Reuses the legacy leakage rules with scoped decisions."""
import json
import re
from pathlib import Path
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.metrics import jaccard_score
from sklearn.model_selection import GroupShuffleSplit
from split_models import SplitCase,SplitDataset,FrozenSplit,case_hash

NEAR_DUPLICATE=0.6
COPIED_WORDS=8

def normalize(text):
    # Legacy rule: preserve Unicode letters/digits, remove punctuation and case.
    return ' '.join(re.findall(r'[^\W_]+',text.lower()))

def word_similarity(left,right):
    words=[normalize(left),normalize(right)]
    if not words[0] or not words[1]:return 0.0
    binary=CountVectorizer(binary=True,token_pattern=r'(?u)\b\w+\b').fit_transform(words).toarray()
    return float(jaccard_score(binary[0],binary[1],zero_division=0))

def assign_groups(cases:list[dict],seed=7):
    groups=[c.get('source_id') or c['id'] for c in cases]
    split=GroupShuffleSplit(n_splits=1,test_size=1/3,random_state=seed)
    dev,held=next(split.split(cases,groups=groups))
    held_ids=set(held.tolist())
    return [dict(c,split='held_out' if i in held_ids else 'development') for i,c in enumerate(cases)]

def check(dataset:SplitDataset,prompt:str='',locked:FrozenSplit|None=None):
    rows=[]
    def finding(check,severity,**details):rows.append(dict(check=check,severity=severity,**details))
    dev=[c for c in dataset.cases if c.split=='development']
    held=[c for c in dataset.cases if c.split=='held_out']
    for left in dev:
        for right in held:
            score=word_similarity(left.issue,right.issue)
            if normalize(left.issue) and normalize(left.issue)==normalize(right.issue):
                finding('duplicate input','block',development=left.id,held_out=right.id)
            elif score>=NEAR_DUPLICATE:
                finding('near duplicate','review',development=left.id,held_out=right.id,similarity=round(score,4))
    by_id={c.id:c for c in dataset.cases}
    for c in dataset.cases:
        if c.source_id and by_id[c.source_id].split!=c.split:
            finding('source crosses split','block',case=c.id,source=c.source_id)
    prompt_words=normalize(prompt).split()
    for c in held:
        words=normalize(c.issue).split()
        copied=[' '.join(words[i:i+COPIED_WORDS]) for i in range(len(words)-COPIED_WORDS+1)
                if any(prompt_words[j:j+COPIED_WORDS]==words[i:i+COPIED_WORDS]
                       for j in range(len(prompt_words)-COPIED_WORDS+1))]
        if copied:finding('held-out excerpt in prompt','review',case=c.id,excerpt=copied[0])
    if locked is not None:
        if locked.dataset_name!=dataset.name:raise ValueError('lock belongs to another dataset')
        for id,digest in locked.held_out.items():
            c=by_id.get(id)
            if c is None:finding('frozen split changed','block',case=id,reason='removed')
            elif c.split!='held_out':finding('frozen split changed','block',case=id,reason='moved')
            elif case_hash(c)!=digest:finding('frozen split changed','block',case=id,reason='edited')
        for c in held:
            if c.id not in locked.held_out:finding('frozen split changed','block',case=c.id,reason='added')
    severity={r['severity'] for r in rows}
    return {'dataset':dataset.name,'version':dataset.version,
            'cases':{'development':len(dev),'held_out':len(held)},
            'decision':'block' if 'block' in severity else 'review' if rows else 'pass','findings':rows}

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('cases',type=Path)
    parser.add_argument('--lock',type=Path)
    parser.add_argument('--prompt',type=Path)
    args=parser.parse_args()
    data=SplitDataset.model_validate_json(args.cases.read_text())
    locked=FrozenSplit.model_validate_json(args.lock.read_text()) if args.lock else None
    report=check(data,args.prompt.read_text() if args.prompt else '',locked)
    print(json.dumps(report,indent=2));raise SystemExit(1 if report['decision']=='block' else 0)
