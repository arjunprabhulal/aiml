"""Bind the local release check to code, docs, configuration and application cases."""
import argparse,hashlib,json
from pathlib import Path
from assistant import digest
from evaluate import evaluate
ROOT=Path(__file__).parent

def inputs():
    names=[p.name for p in ROOT.glob('*.py')]+['requirements-lock.txt','cases.json']+[str(p.relative_to(ROOT)) for p in (ROOT/'docs').rglob('*') if p.is_file()]+[str(p.relative_to(ROOT)) for p in (ROOT/'static').glob('*')]
    return {n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in sorted(names)}

def seal():
    result=evaluate()
    if result['passed']!=result['total']:raise ValueError('Application case failed')
    return {'files':inputs(),'evaluation':{'provider':result['provider'],'snapshot':result['snapshot'],
        'cases_sha256':result['cases_sha256'],'passed':result['passed'],'total':result['total']}}

def check(saved):
    # Recompute the application checks; do not trust a saved pass boolean.
    current=seal()
    if saved!=current:raise ValueError('Release inputs or evaluation changed; rerun the checks')
    return current

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['seal','verify']);p.add_argument('--manifest',default='runs/release.json');args=p.parse_args();target=Path(args.manifest)
    if args.action=='seal':
        target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(seal(),indent=2)+'\n');print('Local release manifest written.')
    else:check(json.loads(target.read_text()));print('Local release check passed: current files and offline application cases match.')
if __name__=='__main__':main()
