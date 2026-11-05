"""Ask the running local assistant without a browser."""
import argparse,json,urllib.request,urllib.error

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('question');parser.add_argument('--version',default='3.5')
    parser.add_argument('--collection',default='handbook');parser.add_argument('--token',default='reader-demo-token')
    parser.add_argument('--url',default='http://127.0.0.1:8120');args=parser.parse_args()
    body=json.dumps({'question':args.question,'version':args.version,'collection':args.collection}).encode()
    request=urllib.request.Request(args.url+'/api/ask',data=body,headers={'Content-Type':'application/json','Authorization':'Bearer '+args.token})
    try:
        with urllib.request.urlopen(request,timeout=45) as r: result=json.load(r)
    except urllib.error.HTTPError as e:
        print(f'HTTP {e.code}: '+e.read().decode());raise SystemExit(1)
    print(result['answer'])
    for citation in result['citations']: print(f"\n[{citation['source_id']}] {citation['quote']}")
    print(f"\nProvider: {result['trace']['provider']}; cached retrieval: {result['trace']['cache_hit']}")
if __name__=='__main__':main()
