"""Run the twelve connected local MLOps workshops in prerequisite order."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import workflow as w
import foundations as f
import pipeline
import tracking
import release
import serving
import rollout
import operations

TOPICS=['pipeline','retries','ci-checks','candidate-gate','registry','serving','rollout','rollback','monitoring','delayed-evaluation','drift','recovery']


def need(root,name):
    path=root/name
    if not path.exists():raise ValueError('complete the earlier workshop first: '+name)
    return path


def training(root):return w.strict_json(need(root,'pipeline-state.json'))


def rows(root):
    result=training(root);cohort=w.cohort(Path(result['workspace'])/'cohort.json')
    return [{'id':r['id'],'entity':r['entity'],'predict_at':r['predict_at'],'feature_at':r['predict_at'],w.FEATURE:r['feature_count']} for r in cohort['rows'] if r['split']=='validation']


def pipeline_report(root):
    result=pipeline.run(w.HERE/'scenario.json',root/'training');w.save(root/'pipeline-state.json',result)
    return {'status':result['status'],'training_rows':result['training_rows'],'validation_accuracy':result['validation_accuracy'],
            'run_id':result['run_id'],'model_sha256':result['model_sha256'],'cohort_consumed_from_history':result['prepared_cohort_sha256'],
            'receipt_attempts':result['receipt_attempts'],'final_test_used':False}


def retry_report(root):
    training(root)
    result=pipeline.run(w.HERE/'scenario.json',root/'retry-training',True)
    repeated=pipeline.run(w.HERE/'scenario.json',root/'retry-training')
    if result['receipt_attempts']!=2 or repeated['run_id']!=result['run_id']:raise ValueError('retry/reuse contract failed')
    w.save(root/'retry-state.json',result)
    return {'receipt_attempts':result['receipt_attempts'],'same_run_reused':repeated['reused'],
            'training_executions_in_attempt':len(list((Path(result['workspace'])/'tracker/runs').iterdir())),
            'run_id':result['run_id'],'failure':'controlled transient receipt-write failure; original attempt logged'}


def ci_report(root):
    import ci
    need(root,'retry-state.json');result=ci.check()
    if not result['passed']:raise ValueError('local CI checks failed; inspect raw test output')
    return result


def gate_report(root):
    need(root,'ci-checks.json');result=training(root);_,source=release.candidate_files(root/'pipeline-state.json')
    normal=release.gate(source/'outputs/cohort.json',source/'outputs/candidate.json')
    stricter=release.gate(source/'outputs/cohort.json',source/'outputs/candidate.json',dict(release.POLICY,minimum_accuracy=0.99))
    w.save(root/'decision.json',normal)
    return {'declared_policy':normal['policy'],'checks':normal['checks'],'passed':normal['passed'],
            'validation_correct':normal['validation']['correct'],'majority_correct':normal['validation']['majority_correct'],
            'strict_alternative_passed':stricter['passed'],'cost_at_threshold_0_5':normal['cost_comparison']['candidates'][1]['total_cost'],
            'permission':normal['permission'],'final_test_used':False}


def registry_report(root):
    need(root,'decision.json');result=training(root);tracker=Path(result['workspace'])/'tracker'
    first=release.package_candidate(root/'pipeline-state.json',root/'bundle-v1')
    one=release.register(root/'bundle-v1',tracker)
    # A second real execution yields the same fitted values. It exercises release
    # identity, not a claim that repeated training improves quality.
    source=Path(result['workspace'])/'accepted-scenario.json'
    second=tracking.execute(source,tracker,prepared_cohort=Path(result['workspace'])/'cohort.json')
    second['workspace']=result['workspace'];w.save(root/'candidate-v2-state.json',second)
    release.package_candidate(root/'candidate-v2-state.json',root/'bundle-v2')
    two=release.register(root/'bundle-v2',tracker)
    selected,version=release.selected(tracker)
    w.save(root/'registry-state.json',{'tracker':str(tracker),'stable_version':one['version'],'candidate_version':two['version']})
    return {'registered_versions':[one['version'],two['version']],'review_alias_version':version,
            'format':'custom user_return MLflow flavor; release.load_bundle loader',
            'model_bytes_equal':first['model_sha256']==second['model_sha256'],
            'bundle_ids_distinct':one['bundle_sha256']!=two['bundle_sha256'],'traffic_changed':False}


def serving_report(root):
    need(root,'registry-state.json');requests=rows(root)
    w.save(root/'requests.json',requests)
    result=serving.batch(root/'bundle-v1',requests);w.save(root/'predictions.json',result)
    # A fresh uvicorn process proves the HTTP boundary, not just TestClient.
    import httpx
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    with (root/'http.stdout.txt').open('x') as log:
        process=subprocess.Popen([sys.executable,'serving.py','--bundle',str(root/'bundle-v1'),'--http','--port',str(port)],cwd=w.HERE,stdout=log,stderr=subprocess.STDOUT)
        try:
            with httpx.Client(base_url=f'http://127.0.0.1:{port}',timeout=3,trust_env=False) as client:
                for _ in range(200):
                    if process.poll() is not None:raise ValueError('HTTP process exited before readiness')
                    try:
                        if client.get('/health').status_code==200:break
                    except httpx.HTTPError:pass
                    time.sleep(.05)
                else:raise ValueError('HTTP readiness timeout')
                response=client.post('/predict',json=requests[0]);response.raise_for_status()
                rejected=client.post('/predict',content='null')
                parity=response.json()['return_probability']==result['predictions'][0]['return_probability']
                if not parity or rejected.status_code!=422:raise ValueError('HTTP parity or validation failed')
                w.save(root/'http-response.json',response.json())
        finally:process.terminate();process.wait(timeout=8)
    return {'batch_rows':len(result['predictions']),'fresh_http_process':True,'http_status':response.status_code,
            'null_status':rejected.status_code,'batch_http_probability_equal':parity,'bundle_id':result['bundle_id'],
            'external_service_deployed':False}


def rollout_report(root):
    need(root,'predictions.json');routing=rollout.Routing(root/'routing.sqlite')
    try:
        first=routing.stage(root/'bundle-v1',root/'bundle-v1',0,0)
        canary=routing.stage(root/'bundle-v1',root/'bundle-v2',25,first['generation'])
        predictions=[routing.predict(row) for row in rows(root)]
        counts=dict(__import__('collections').Counter(p['route'] for p in predictions))
        if len(counts)!=2:raise ValueError('fixture did not exercise both routes')
        full=routing.stage(root/'bundle-v1',root/'bundle-v2',100,canary['generation'])
        w.save(root/'routed-predictions.json',{'predictions':predictions})
        return {'staged_generation':canary['generation'],'candidate_bucket_percent':25,'observed_routes':counts,
                'full_candidate_generation':full['generation'],'routing':'local calls through one transactional routing table',
                'quality_improvement_claimed':False}
    finally:routing.close()


def rollback_report(root):
    need(root,'routed-predictions.json');routing=rollout.Routing(root/'routing.sqlite')
    candidate=root/'bundle-v2';held=root/'bundle-v2-held-during-drill'
    try:
        current=routing.current();candidate.rename(held)
        try:
            try:routing.predict(rows(root)[0])
            except FileNotFoundError:failure='selected candidate files unavailable in controlled drill'
            else:raise ValueError('controlled missing-artifact failure did not occur')
            restored=routing.rollback(1,current['generation'])
            prediction=routing.predict(rows(root)[0])
        finally:held.rename(candidate)
        return {'observed_failure':failure,'restored_generation':restored['generation'],
                'restored_candidate_percent':restored['percent'],'prediction_route':prediction['route'],
                'release_history_rows':routing.db.execute('SELECT count(*) FROM releases').fetchone()[0]}
    finally:routing.close()


def monitoring_report(root):
    need(root,'rollback.json');events,predictions=operations.measure(root/'bundle-v1',rows(root)+[None])
    w.save(root/'service-events.json',{'events':events});w.save(root/'observed-predictions.json',{'predictions':predictions})
    return operations.service_report(events)


def delayed_report(root):
    predictions=w.strict_json(need(root,'observed-predictions.json'))['predictions'];fixture=w.strict_json(w.HERE/'scenario.json')
    first=[p for p in predictions if p['predict_at'].startswith('2026-01-10')]
    early=operations.evaluate_delayed(first,fixture,'2026-01-11T13:00:00Z')
    final=operations.evaluate_delayed(predictions,fixture,'2026-01-13T14:00:00Z')
    return {'before_reporting_delay':early,'after_labels_finalize':final}


def drift_report(root):
    quality=w.strict_json(need(root,'delayed-evaluation.json'))['after_labels_finalize'];reference=[r[w.FEATURE] for r in rows(root)]
    return {'unchanged':operations.distribution(reference,reference),
            'controlled_shift':operations.distribution(reference,[0]*len(reference)),
            'investigation':operations.investigate(reference,[0]*len(reference),quality),
            'invalid_input':operations.investigate(reference,[True],quality)}


def recovery_report(root):
    need(root,'drift.json');routing=rollout.Routing(root/'routing.sqlite')
    try:before=routing.current()
    finally:routing.close()
    # Operator chooses the original valid source after the invalid-input drill.
    # This is a fresh actual fit, not approval to switch traffic.
    result=pipeline.run(w.HERE/'scenario.json',root/'recovery-training')
    w.save(root/'recovery-state.json',result);_,source=release.candidate_files(root/'recovery-state.json')
    decision=release.gate(source/'outputs/cohort.json',source/'outputs/candidate.json')
    w.save(root/'recovery-gate.json',decision)
    routing=rollout.Routing(root/'routing.sqlite')
    try:after=routing.current()
    finally:routing.close()
    if before!=after:raise ValueError('recovery unexpectedly changed traffic')
    return {'source':'original valid authored scenario; invalid drill inputs excluded','new_training_run':result['run_id'],
            'gate_passed':decision['passed'],'policy_unchanged':decision['policy']==release.POLICY,
            'traffic_unchanged':before==after,'automatic_promotion':False,'final_test_used':False}

HANDLERS=dict(zip(TOPICS,[pipeline_report,retry_report,ci_report,gate_report,registry_report,serving_report,rollout_report,rollback_report,monitoring_report,delayed_report,drift_report,recovery_report]))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('topic',choices=TOPICS);p.add_argument('--workspace',type=Path,default=Path('work/course'));p.add_argument('--out',type=Path)
    a=p.parse_args();root=a.workspace.resolve();root.mkdir(parents=True,exist_ok=True)
    try:
        output=root/(a.topic+'.json')
        if output.exists():raise FileExistsError('topic output already exists; retain it and choose a fresh full workspace for another sequence')
        result=HANDLERS[a.topic](root);w.save(output,result)
        if a.out:w.save(a.out,result)
        print(json.dumps(result,indent=2,allow_nan=False))
    except (ValueError,OSError) as e:p.exit(2,str(e)+'\n')


if __name__=='__main__':main()
