"""Evaluate the developer assistant on explicit application cases, without a model by default."""
import argparse
import json
from pathlib import Path
from assistant import Assistant, Ask, Denied, digest

ROOT = Path(__file__).parent

def evaluate(service=None):
    service = service or Assistant()
    cases = json.loads((ROOT/'cases.json').read_text())
    rows = []
    for case in cases:
        request = Ask(question=case['question'],version=case.get('version','3.5'),collection=case.get('collection','handbook'))
        try:
            result = service.ask('eval-'+case['id'],case.get('role','reader'),request)
            documents = {s['document'] for s in result['sources']}
            citation_documents = {c['source_id'].split(':')[0] for c in result['citations']}
            passed = result['status']==case['status']
            if 'source' in case: passed = passed and case['source'] in citation_documents
            if case['status']=='abstain': passed = passed and not result['citations'] and not result['sources']
            if 'answer_contains' in case: passed = passed and case['answer_contains'] in result['answer']
            rows.append({'id':case['id'],'pass':bool(passed),'result':result})
        except Denied:
            rows.append({'id':case['id'],'pass':case['status']=='denied','status':'denied'})
    return {'provider':service.provider.name,'snapshot':service.corpus.snapshot,'cases_sha256':digest(cases),
        'passed':sum(r['pass'] for r in rows),'total':len(rows),'rows':rows}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',default='runs/evaluation.json');args=p.parse_args()
    report=evaluate();target=Path(args.output);target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(report,indent=2)+'\n')
    for r in report['rows']:print(('PASS' if r['pass'] else 'FAIL')+' '+r['id'])
    print(f"{report['passed']}/{report['total']} application cases passed ({report['provider']}).")
    raise SystemExit(0 if report['passed']==report['total'] else 1)
if __name__=='__main__':main()
