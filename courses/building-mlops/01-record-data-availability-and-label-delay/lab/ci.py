"""Run the same offline gates locally or in a repository CI job."""
import argparse
import importlib.metadata
import io
import json
import sys
import unittest
from pathlib import Path
import workflow as w


def check():
    names=['test_workflow','test_foundations','test_tracking','test_platform']
    suite=unittest.defaultTestLoader.loadTestsFromNames(names)
    stream=io.StringIO();result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    print(stream.getvalue(),file=sys.stderr)
    return {'command':'python ci.py','tests_run':result.testsRun,'failures':len(result.failures),
            'errors':len(result.errors),'skipped':len(result.skipped),'passed':result.wasSuccessful(),
            'python':sys.version.split()[0],'packages':{p:importlib.metadata.version(p) for p in ['mlflow-skinny','prefect']},
            'execution':'actual local tests; hosted GitHub Actions job not executed'}


def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    result=check();w.save(a.out,result);print(json.dumps(result,indent=2));sys.exit(0 if result['passed'] else 1)


if __name__=='__main__':main()
