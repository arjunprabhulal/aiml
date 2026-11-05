"""Local service metrics, finalized-outcome evaluation and drift investigation."""
import argparse
from collections import Counter
import json
import math
from pathlib import Path
import time
import workflow as w
import foundations as f
import serving


def measure(bundle,rows):
    predictor=serving.Predictor(bundle);events=[];predictions=[]
    for row in rows:
        start=time.perf_counter()
        try:
            result=predictor.predict(row);predictions.append(result)
            event={'status':'ok','bundle_id':predictor.bundle_id,'id':result['id'],'feature_at':result['feature_at'],'predict_at':result['predict_at']}
        except ValueError:event={'status':'invalid','bundle_id':predictor.bundle_id}
        event['elapsed_ms']=(time.perf_counter()-start)*1000;events.append(event)
    return events,predictions


def service_report(events):
    if not isinstance(events,list) or not 1<=len(events)<=1000:raise ValueError('report requires 1 to 1000 events')
    for event in events:
        if event.get('status') not in ['ok','invalid','error']:raise ValueError('unknown event status')
        value=event.get('elapsed_ms')
        if type(value) not in (int,float) or not math.isfinite(value) or value<0:raise ValueError('invalid elapsed time')
    values=sorted(e['elapsed_ms'] for e in events)
    return {'requests':len(events),'status_counts':dict(Counter(e['status'] for e in events)),
            'p50_ms':values[math.ceil(len(values)*.5)-1],'p95_ms':values[math.ceil(len(values)*.95)-1],
            'quantile':'nearest rank; whole local prediction call, excluding model load',
            'window':'this supplied bounded batch','prediction_quality_measured':False}


def evaluate_delayed(predictions,fixture,as_of):
    w.availability.validate(fixture['observations'],[],fixture['labels'])
    now=w.availability.instant(as_of);labels={x['id']:x for x in fixture['labels']}
    if len(labels)!=len(fixture['labels']):raise ValueError('duplicate label identity')
    observations={o['id']:o for o in fixture['observations']}
    ids=set();scored=[];pending=unknown=0
    for p in predictions:
        if p['id'] in ids:raise ValueError('duplicate prediction identity')
        ids.add(p['id']);o=observations.get(p['id']);label=labels.get(p['id'])
        if o is None or label is None:unknown+=1;continue
        if (p['entity']!=o['entity'] or w.availability.instant(p['predict_at'])!=w.availability.instant(o['predict_at'])):raise ValueError('prediction and observation differ')
        if w.partition(p['predict_at'])=='test':raise ValueError('this workshop preserves the final test')
        if now<w.availability.instant(p['predict_at']):raise ValueError('prediction lies after evaluation time')
        if now<w.availability.instant(label['ready_at']):pending+=1;continue
        # Validate label schema and its full 26-hour readiness contract.
        w.availability.validate([o],[],[label])
        from datetime import timedelta
        if w.availability.instant(label['ready_at'])<w.availability.instant(o['predict_at'])+timedelta(hours=26):
            raise ValueError('label violates the declared reporting delay')
        if type(p['predicted_return']) is not int or p['predicted_return'] not in [0,1]:raise ValueError('invalid prediction decision')
        probability=p['return_probability']
        if type(probability) not in (int,float) or not math.isfinite(probability) or not 0<=probability<=1:raise ValueError('invalid prediction probability')
        scored.append(dict(correct=int(p['predicted_return']==label['value']),bundle_id=p['bundle_id']))
    grouped={key:{'rows':sum(s['bundle_id']==key for s in scored),'correct':sum(s['correct'] for s in scored if s['bundle_id']==key)} for key in sorted({s['bundle_id'] for s in scored})}
    return {'as_of':as_of,'received':len(predictions),'pending':pending,'unknown':unknown,'scored':len(scored),
            'correct':sum(s['correct'] for s in scored),'accuracy':sum(s['correct'] for s in scored)/len(scored) if scored else None,
            'by_bundle':grouped,'final_test_used':False,'population':'the same synthetic validation observations; not a new held-out estimate'}


def distribution(reference,current):
    # Fixed bins: zero, one-to-two, three-to-five, six or more known events.
    def hist(values):
        if not values:raise ValueError('empty feature sample')
        counts=[0,0,0,0]
        for value in values:
            w.count(value);counts[0 if value==0 else 1 if value<3 else 2 if value<6 else 3]+=1
        return [v/len(values) for v in counts]
    a,b=hist(reference),hist(current);distance=sum(abs(x-y) for x,y in zip(a,b))/2
    return {'bins':['0','1–2','3–5','6–1000'],'reference_rows':len(reference),'current_rows':len(current),
            'reference_fraction':a,'current_fraction':b,'total_variation':distance,'investigation_threshold':0.2,
            'investigate':distance>0.2,'retraining_authorized':False,'quality_measured':False}


def investigate(reference,current,quality):
    try:drift=distribution(reference,current)
    except ValueError as e:return {'decision':'repair data before retraining','reason':str(e),'retrain':False}
    if quality['scored']==0:return {'decision':'wait for finalized outcomes','drift':drift,'retrain':False}
    if quality['accuracy']<0.60:return {'decision':'investigate data and candidate errors; evaluate any new model with the same gate','drift':drift,'retrain':False}
    return {'decision':'investigate distribution change' if drift['investigate'] else 'continue observing','drift':drift,'retrain':False}
