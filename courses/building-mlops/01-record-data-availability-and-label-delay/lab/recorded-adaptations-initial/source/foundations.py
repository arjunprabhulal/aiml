"""Adapt the published MLOps mechanisms to the shared user-return application."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import workflow as w
from vendor import partitions
import quarantine_reuse as quarantine
from history_reuse import History, COUNT, minute, source_rows, compute

HERE = Path(__file__).resolve().parent
FEATURE_CONTRACT = {'name': w.FEATURE, 'version': 1, 'entity': 'existing_user',
                    'window_seconds': 86400, 'event_cutoff': 'strictly_before_prediction',
                    'arrival_cutoff': 'strictly_before_prediction', 'aggregation': 'count',
                    'feature_order': [w.FEATURE], 'count_range': [0, 1000]}
CORE_FILES = ('workflow.py', 'foundations.py', 'scenario.json', 'vendor/__init__.py',
              'vendor/availability.py', 'vendor/baseline.py', 'vendor/partitions.py',
              'vendor/feature_math.py', 'quarantine_reuse.py', 'history_reuse.py', 'join.sql')


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def split_report(source):
    fixture = w.strict_json(source)
    # Reuse the published partition algorithm with this application's date windows.
    for name, stamp in {'START':'2026-01-03', 'TRAIN_END':'2026-01-09',
                        'VALIDATION_START':'2026-01-10', 'VALIDATION_END':'2026-01-12',
                        'TEST_START':'2026-01-13', 'END':'2026-01-15'}.items():
        setattr(partitions, name, datetime.fromisoformat(stamp).replace(tzinfo=timezone.utc))
    rows = [dict(id=o['id'], entity=o['entity'], observed_at=o['predict_at']) for o in fixture['observations']]
    parts = partitions.partition(rows, 'future')
    assigned = {row['id']:name for name, items in parts.items() for row in items}
    assert all(assigned[o['id']]==w.partition(o['predict_at']) for o in fixture['observations'])
    report = partitions.describe(parts)
    report['target'] = 'later observations for existing users'
    report['maximum_training_label_ready_at'] = max(l['ready_at'] for l in fixture['labels'] if assigned[l['id']]=='training')
    report['earliest_validation_prediction'] = report['ranges']['validation']['first']
    report['training_labels_ready_before_validation'] = (w.availability.instant(report['maximum_training_label_ready_at']) < w.availability.instant(report['earliest_validation_prediction']))
    return report


def availability_report(source):
    fixture = w.strict_json(source)
    chosen = next(o for o in fixture['observations'] if o['id']=='user-00-day-03')
    label = next(l for l in fixture['labels'] if l['id']==chosen['id'])
    at = w.availability.instant(chosen['predict_at'])
    early = w.availability.assemble([chosen], fixture['events'], [label], (at+timedelta(hours=25)).isoformat())
    ready = w.availability.assemble([chosen], fixture['events'], [label], label['ready_at'])
    known = w.availability.feature_events(chosen, fixture['events'])
    retrospective = w.availability.feature_events(chosen, fixture['events'], require_arrival=False)
    return {'observation':chosen['id'], 'predict_at':chosen['predict_at'],
            'outcome_end':(at+timedelta(hours=24)).isoformat(), 'label_ready_at':label['ready_at'],
            'available_event_count':len(known), 'retrospective_event_count':len(retrospective),
            'late_events_excluded':sorted(set(retrospective)-set(known)),
            'at_25_hours':early['exclusion_counts'], 'at_label_readiness':len(ready['rows'])}


def cost_report(cohort_path, model_path, false_positive=1.0, false_negative=3.0):
    for value in [false_positive,false_negative]:
        if type(value) not in (int,float) or not __import__('math').isfinite(value) or value < 0:
            raise ValueError('costs must be finite nonnegative values')
    cohort, model = w.cohort(cohort_path), w.load_model(model_path)
    if model['cohort_sha256']!=w.sha(cohort_path):
        raise ValueError('model and cohort identities differ')
    # Explicit illustrative costs: unnecessary analyst follow-up versus a missed return.
    # A real retention experiment must estimate these costs before threshold selection.
    rows=[r for r in cohort['rows'] if r['split']=='validation']
    if not rows: raise ValueError('validation rows are required')
    reports=[]
    for threshold in [0.3,0.5,0.7]:
        fp=fn=correct=0
        for row in rows:
            predicted=int(w.predict(model,row['feature_count'])['return_probability']>=threshold)
            fp+=int(predicted==1 and row['label']==0)
            fn+=int(predicted==0 and row['label']==1)
            correct+=int(predicted==row['label'])
        reports.append({'threshold':threshold,'correct':correct,'false_positive':fp,'false_negative':fn,
                        'total_cost':fp*false_positive+fn*false_negative})
    return {'split':'validation','rows':len(rows),'costs':{'false_positive':false_positive,'false_negative':false_negative},
            'units':'illustrative decision-cost units, not measured money',
            'candidates':reports,'selected_for_inspection':min(reports,key=lambda r:(r['total_cost'],r['threshold']))['threshold'],
            'model_threshold_unchanged':0.5,'final_test_used':False}


def validate_source(source, destination, inject_bad=False):
    fixture=w.strict_json(source)
    w.availability.validate(fixture['observations'], fixture['events'], fixture['labels'])
    raw=b''.join(encoded(e)+b'\n' for e in fixture['events'])
    if inject_bad: raw+=b'{"id":"broken"}\n'
    batch=quarantine.validate_batch(raw)
    manifest=quarantine.write_batch(batch,destination)
    return {'status':manifest['status'],'accepted':manifest['accepted'],'quarantined':manifest['quarantined'],
            'reason_counts':manifest['reason_counts'],'training_file':manifest['training_file'],
            'source_sha256':manifest['source_sha256']}


class ReturnHistory(History):
    """Retain the old history behavior; explicitly include known users with zero activity."""
    def publish(self, fixture, cutoff, published_at, mode='as_known'):
        key=self.materialize(fixture['events'],cutoff,published_at,mode)
        known=sorted({o['entity'] for o in fixture['observations']})
        with self.db:
            for entity in known:
                inserted=self.db.execute('INSERT OR IGNORE INTO history VALUES (?,?,?,?,?)',(key,entity,cutoff,published_at,0)).rowcount
                if inserted:
                    self.db.execute('''INSERT INTO online VALUES (?,?,?,?,?) ON CONFLICT(feature,entity) DO UPDATE SET cutoff=excluded.cutoff,published_at=excluded.published_at,value=excluded.value WHERE excluded.cutoff>online.cutoff OR (excluded.cutoff=online.cutoff AND excluded.published_at>online.published_at)''',(key,entity,cutoff,published_at,0))
        return key


def publish_history(source, database):
    path=Path(database)
    if path.exists(): raise FileExistsError('use a fresh history database')
    path.parent.mkdir(parents=True,exist_ok=True)
    fixture=w.strict_json(source);w.availability.validate(fixture['observations'],fixture['events'],fixture['labels'])
    store=ReturnHistory(path)
    try:
        for cutoff in sorted({minute(o['predict_at']) for o in fixture['observations']}):
            store.publish(fixture,cutoff,cutoff)
        rows=store.join(fixture['observations'],'user_events_1d@v1')
        expected={r['id']:r['feature_count'] for r in w.prepare(source)['rows']}
        matches=sum(row['feature']['value']==expected[row['id']] for row in rows)
        return {'feature':w.FEATURE,'storage_key':'user_events_1d@v1','observations':len(rows),
                'matching_assembled_counts':matches,'known_users':len({o['entity'] for o in fixture['observations']}),'known_zero_counts_are_materialized':True}
    finally: store.close()


def history_report(source, database):
    fixture=w.strict_json(source);store=ReturnHistory(database)
    try:
        o=next(o for o in fixture['observations'] if o['id']=='user-00-day-08')
        cutoff=minute(o['predict_at']);key='user_events_1d@v1'
        original=store.point_in_time(key,o['entity'],cutoff)
        store.publish(fixture,cutoff,minute('2026-01-16T13:00:00Z'),'corrected')
        historical=store.point_in_time(key,o['entity'],cutoff)
        corrected=store.point_in_time(key,o['entity'],minute('2026-01-16T14:00:00Z'))
        # point_in_time selects the newest eligible cutoff, not an arbitrary old cutoff.
        vintage=store.db.execute('SELECT value FROM history WHERE feature=? AND entity=? AND cutoff=? ORDER BY published_at DESC LIMIT 1',(key,o['entity'],cutoff)).fetchone()[0]
        return {'observation':o['id'],'original':original['value'],'historical_after_correction':historical['value'],
                'later_correction_for_same_cutoff':vintage,'original_view_preserved':original==historical,
                'latest_eligible_cutoff_at_later_read':corrected['cutoff']}
    finally:store.close()


def parity_report(source,database):
    fixture=w.strict_json(source);store=ReturnHistory(database)
    try:
        # Use the final original cutoff, so the online projection and reference address the same snapshot.
        cutoff=max(minute(o['predict_at']) for o in fixture['observations']);key='user_events_1d@v1';entity='user-00'
        now=cutoff+30;online=store.read_online(key,entity,now,60)
        original=store.point_in_time(key,entity,cutoff)
        direct=compute(COUNT,source_rows(fixture['events']),cutoff,'as_known').get(entity,0)
        corrected=compute(COUNT,source_rows(fixture['events']),cutoff,'corrected').get(entity,0)
        return {'cutoff':cutoff,'value':online['value'],'same_snapshot_parity':online['value']==original['value']==direct,
                'different_arrival_rule_value':corrected,'stale_status':store.read_online(key,entity,cutoff+61,60)['status'],
                'unknown_user_status':store.read_online(key,'unknown-user',now,60)['status']}
    finally:store.close()


def contract(source):
    files={name:w.sha(HERE/name) for name in CORE_FILES if name!='scenario.json'}
    return {'project':w.PROJECT,'format':'return-application-contract-v1',
            'dataset_sha256':w.sha(source),'feature':FEATURE_CONTRACT,'implementation':files}


def bind_contract(database, manifest, version=1):
    if type(version) is not int or version<1:raise ValueError('version must be a positive integer')
    path=Path(database);path.parent.mkdir(parents=True,exist_ok=True)
    components={'dataset':manifest['dataset_sha256'],'feature':digest({'definition':manifest['feature'],'implementation':manifest['implementation']})}
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE IF NOT EXISTS identities (kind TEXT,project TEXT,version INTEGER,digest TEXT,PRIMARY KEY(kind,project,version))')
        for kind,value in components.items():
            old=db.execute('SELECT digest FROM identities WHERE kind=? AND project=? AND version=?',(kind,w.PROJECT,version)).fetchone()
            if old and old[0]!=value:raise ValueError('version already means different '+kind)
            db.execute('INSERT OR IGNORE INTO identities VALUES (?,?,?,?)',(kind,w.PROJECT,version,value))
    return {'version':version,'contract_id':digest(manifest),'components':components}


def snapshot(source,destination):
    path=Path(destination);path.mkdir(parents=True)
    for name in CORE_FILES:
        target=path/name;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(Path(source).read_bytes() if name=='scenario.json' else (HERE/name).read_bytes())
    manifest=contract(source);w.save(path/'contract.json',manifest)
    return manifest
