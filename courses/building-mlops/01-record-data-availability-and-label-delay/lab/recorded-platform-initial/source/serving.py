"""Batch prediction and a loopback-only optional HTTP boundary."""
import argparse
import json
import math
import time
from pathlib import Path
import uuid
import workflow as w
import foundations as f
import release


def request(value):
    required={'id','entity','predict_at','feature_at','recent_event_count'}
    if not isinstance(value,dict) or set(value)!=required:raise ValueError('prediction needs exactly the declared fields')
    for key in ['id','entity']:w.availability.check_id(value[key])
    at=w.availability.instant(value['predict_at']);feature=w.availability.instant(value['feature_at'])
    if at!=feature:raise ValueError('feature must be calculated for this prediction cutoff')
    w.count(value['recent_event_count'])
    return value


class Predictor:
    def __init__(self,bundle):
        self.bundle=Path(bundle);self.model,self.manifest,self.decision=release.load_bundle(bundle)
        if not self.decision['passed']:raise ValueError('failed candidate cannot serve')
        self.bundle_id=f.digest(self.manifest)

    def predict(self,value):
        value=request(value);start=time.perf_counter()
        result=w.predict(self.model,value['recent_event_count'])
        return {'id':value['id'],'entity':value['entity'],'predict_at':value['predict_at'],
                'feature_at':value['feature_at'],'recent_event_count':value['recent_event_count'],
                **result,'bundle_id':self.bundle_id,'model_sha256':self.manifest['model_sha256'],
                'policy_sha256':self.manifest['policy_sha256'],
                'prediction_ms':(time.perf_counter()-start)*1000}


def batch(bundle,rows):
    # Validate the entire batch before generating output; reject duplicate requests.
    if not isinstance(rows,list) or not 1<=len(rows)<=1000:raise ValueError('batch requires 1 to 1000 rows')
    checked=[request(row) for row in rows]
    if len({r['id'] for r in checked})!=len(checked):raise ValueError('duplicate prediction ID')
    predictor=Predictor(bundle)
    return {'bundle_id':predictor.bundle_id,'predictions':[predictor.predict(row) for row in checked],
            'execution':'actual local batch prediction; authored feature inputs'}


def create_app(bundle):
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse
    app=FastAPI();predictor=Predictor(bundle)
    @app.get('/health')
    def health():return {'status':'ready','bundle_id':predictor.bundle_id}
    @app.post('/predict')
    async def predict_http(http:Request):
        try:
            if int(http.headers.get('content-length','0'))>65536:return JSONResponse({'error':'request too large'},status_code=413)
            raw=await http.body()
            if len(raw)>65536:return JSONResponse({'error':'request too large'},status_code=413)
            # Reuse strict JSON semantics, including duplicate fields and NaN rejection.
            def unique(pairs):
                result={}
                for k,v in pairs:
                    if k in result:raise ValueError('duplicate field')
                    result[k]=v
                return result
            def invalid(x):raise ValueError('non-finite JSON')
            data=json.loads(raw,object_pairs_hook=unique,parse_constant=invalid)
            return predictor.predict(data)
        except (ValueError,UnicodeError):return JSONResponse({'error':'invalid prediction request'},status_code=422)
    return app


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--bundle',type=Path,required=True);p.add_argument('--input',type=Path);p.add_argument('--out',type=Path);p.add_argument('--http',action='store_true');p.add_argument('--port',type=int,default=8766)
    a=p.parse_args()
    if a.http:
        import uvicorn
        uvicorn.run(create_app(a.bundle),host='127.0.0.1',port=a.port)
    else:
        if not a.input or not a.out:p.error('batch needs --input and --out')
        result=batch(a.bundle,w.strict_json(a.input));w.save(a.out,result);print(json.dumps(result,indent=2))


if __name__=='__main__':main()
