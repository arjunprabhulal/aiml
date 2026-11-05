"""Exercise the real inspector in installed Chrome against local Uvicorn servers."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import urllib.request
from websockets.sync.client import connect
from loopback import running_server

QUESTION='Will write_text replace the contents of an existing file?'

def chrome_path():
    candidates=[os.environ.get('CHROME_PATH'),shutil.which('chromium'),shutil.which('google-chrome'),'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome']
    for path in candidates:
        if path and Path(path).is_file():return path
    raise RuntimeError('Set CHROME_PATH to an already installed Chrome/Chromium; this runner downloads nothing.')

def run(output,captures):
    output.parent.mkdir(parents=True,exist_ok=True);captures.mkdir(parents=True,exist_ok=True)
    records=[];loading=[];refusals=[];browser_errors=[];browser_version=None
    with running_server('inspector_fixtures:delayed_app') as (client,lifecycle),running_server('inspector_fixtures:fault_app') as (fault_client,fault_lifecycle),tempfile.TemporaryDirectory(prefix='rag-inspector-chrome-') as folder:
        profile=Path(folder)
        chrome=subprocess.Popen([chrome_path(),'--headless=new','--no-first-run','--no-default-browser-check','--remote-debugging-port=0',f'--user-data-dir={profile}','about:blank'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            for _ in range(150):
                if (profile/'DevToolsActivePort').exists():break
                if chrome.poll() is not None:raise RuntimeError('chrome_exited')
                time.sleep(.05)
            port=(profile/'DevToolsActivePort').read_text().splitlines()[0]
            target=json.load(urllib.request.urlopen(urllib.request.Request(f'http://127.0.0.1:{port}/json/new?about:blank',method='PUT')))
            with connect(target['webSocketDebuggerUrl'],max_size=10_000_000) as ws:
                sequence=0;events=[];pending={}
                def call(method,params=None):
                    nonlocal sequence
                    sequence+=1;number=sequence;ws.send(json.dumps({'id':number,'method':method,'params':params or {}}))
                    while number not in pending:
                        message=json.loads(ws.recv(timeout=30))
                        if 'id' in message:pending[message['id']]=message
                        else:events.append(message)
                    message=pending.pop(number)
                    if 'error' in message:raise RuntimeError(message)
                    return message.get('result',{})
                def js(expression):
                    result=call('Runtime.evaluate',{'expression':expression,'returnByValue':True,'awaitPromise':True})
                    if 'exceptionDetails' in result:raise RuntimeError(result)
                    return result['result'].get('value')
                def wait(expression):
                    for _ in range(250):
                        value=js(expression)
                        if value:return value
                        time.sleep(.025)
                    raise RuntimeError('browser_state_timeout: '+expression)
                def screenshot(name,full=False):
                    if full:
                        clip=js("(()=>{const r=document.querySelector('main').getBoundingClientRect();return {x:r.left+scrollX,y:r.top+scrollY,width:r.width,height:r.height,scale:1}})()")
                        if js('innerWidth')<=600:clip.update(x=0,width=js('innerWidth'))
                        if clip['height']*2>15000:raise RuntimeError('report exceeds native capture size')
                        options={'format':'png','clip':clip,'captureBeyondViewport':True}
                    else:options={'format':'png'}
                    target=captures/name;target.write_bytes(base64.b64decode(call('Page.captureScreenshot',options)['data']));return target
                def navigate(origin,width):
                    call('Emulation.setDeviceMetricsOverride',{'width':width,'height':1100,'deviceScaleFactor':2,'mobile':False})
                    call('Browser.grantPermissions',{'origin':origin,'permissions':['clipboardReadWrite','clipboardSanitizedWrite']})
                    call('Page.navigate',{'url':origin+'/inspector'})
                    wait("document.querySelector('#status')?.dataset.state==='ready'")
                    js('document.fonts.ready.then(()=>new Promise(r=>requestAnimationFrame(r)))')
                def set_request(question=QUESTION,version='3.12',steps=6):
                    js("(()=>{document.querySelector('#question').value="+json.dumps(question)+";document.querySelector('#version').value="+json.dumps(version)+";document.querySelector('#max_steps').value="+str(steps)+";})()")
                def submit():
                    start=len(events);js("document.querySelector('#retrieval-form').requestSubmit()")
                    return start
                def exchange(start):
                    reqs=[e['params'] for e in events[start:] if e.get('method')=='Network.requestWillBeSent' and e['params']['request']['url'].endswith('/retrieve')]
                    if len(reqs)!=1:raise RuntimeError('expected one actual browser POST: '+str(len(reqs)))
                    req=reqs[0];request_id=req['requestId']
                    responses=[e['params']['response'] for e in events[start:] if e.get('method')=='Network.responseReceived' and e['params']['requestId']==request_id]
                    if len(responses)!=1:raise RuntimeError('missing browser HTTP response')
                    body=call('Network.getResponseBody',{'requestId':request_id});raw=base64.b64decode(body['body']).decode() if body.get('base64Encoded') else body['body'];response=responses[0]
                    digest=next((v for k,v in response['headers'].items() if k.lower()=='x-retrieval-body-sha256'),None)
                    return {'http_status':int(response['status']),'request':json.loads(req['request']['postData']),'response':json.loads(raw),'raw_response_text':raw,'raw_body_sha256':hashlib.sha256(raw.encode()).hexdigest(),'body_sha256_header':digest}
                call('Page.enable');call('Runtime.enable');call('Network.enable');call('Page.bringToFront');call('Emulation.setFocusEmulationEnabled',{'enabled':True})
                browser_version=call('Browser.getVersion')
                origin=str(client.base_url).rstrip('/');fault_origin=str(fault_client.base_url).rstrip('/')
                for width,name in [(1440,'output.png'),(390,'output-mobile.png'),(320,'output-small.png')]:
                    navigate(origin,width);screenshot(f'{width}-ready.png')
                    set_request();start=submit()
                    state=js("({state:document.querySelector('#status').dataset.state,disabled:document.querySelector('#request-fields').disabled,resultHidden:document.querySelector('#result').hidden})")
                    assert state=={'state':'loading','disabled':True,'resultHidden':True},state
                    js("document.querySelector('#retrieval-form').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}))")
                    assert js("document.querySelector('#status').dataset.state==='loading'")
                    js("document.querySelector('#status').scrollIntoView({block:'center'})");screenshot(f'{width}-loading.png');loading.append({'width':width,**state,'delay_fixture_ms':350})
                    wait("document.querySelector('#status').dataset.state==='result'")
                    observed=exchange(start);packet=observed['response'];dom=js("JSON.parse(document.querySelector('#raw').textContent)")
                    assert dom==packet and observed['raw_body_sha256']==observed['body_sha256_header']
                    assert packet['status']=='completed' and [r['source_id'] for r in packet['evidence']]==['path-read','path-write']
                    ui=js("({overflow:document.documentElement.scrollWidth>innerWidth,sourceCount:document.querySelectorAll('.source').length,status:document.querySelector('#status').textContent,externalLinks:[...document.querySelectorAll('.source a')].map(a=>a.href),requestId:document.querySelector('#request-id').textContent})")
                    assert not ui['overflow'] and ui['sourceCount']==len(packet['evidence'])
                    screenshot(f'{width}-completed.png');source=screenshot(f'{width}-whole-inspector.png',full=True);shutil.copyfile(source,output.parent/name)
                    js("document.querySelector('.table-scroll').scrollIntoView({block:'center'});document.querySelector('.table-scroll').focus()")
                    table=js("(()=>{const t=document.querySelector('.table-scroll');return {width:t.clientWidth,scrollWidth:t.scrollWidth,outline:getComputedStyle(t).outlineStyle}})()")
                    assert table['outline']=='solid'
                    call('Input.dispatchKeyEvent',{'type':'keyDown','key':'ArrowRight','code':'ArrowRight','windowsVirtualKeyCode':39});call('Input.dispatchKeyEvent',{'type':'keyUp','key':'ArrowRight','code':'ArrowRight','windowsVirtualKeyCode':39});time.sleep(.15)
                    table['keyboard_scrolled']=js("document.querySelector('.table-scroll').scrollLeft>0")
                    if table['scrollWidth']>table['width']:assert table['keyboard_scrolled']
                    ui['table']=table;screenshot(f'{width}-table-focus.png')
                    js("document.querySelector('#raw-details summary').focus()")
                    call('Input.dispatchKeyEvent',{'type':'keyDown','key':'Enter','code':'Enter','windowsVirtualKeyCode':13,'text':'\r'});call('Input.dispatchKeyEvent',{'type':'keyUp','key':'Enter','code':'Enter','windowsVirtualKeyCode':13})
                    assert js("document.querySelector('#raw-details').open&&document.querySelector('#raw-details summary').getBoundingClientRect().height>=44")
                    js("document.querySelector('#copy').click()")
                    wait("document.querySelector('#copy').textContent==='Copied'")
                    assert js("navigator.clipboard.readText().then(t=>t===document.querySelector('#raw').textContent)")
                    js("document.querySelector('#raw').focus();document.querySelector('#raw').scrollIntoView({block:'center'})")
                    assert js("getComputedStyle(document.activeElement).outlineStyle==='solid'")
                    call('Input.dispatchKeyEvent',{'type':'keyDown','key':'ArrowDown','code':'ArrowDown','windowsVirtualKeyCode':40});call('Input.dispatchKeyEvent',{'type':'keyUp','key':'ArrowDown','code':'ArrowDown','windowsVirtualKeyCode':40});time.sleep(.15)
                    assert js("document.querySelector('#raw').scrollTop>0")
                    screenshot(f'{width}-raw-focus.png');records.append({'width':width,'scenario':'completed','ui':ui,'rendered_body_matches_wire':True,'copy_matches_raw_json':True,'duplicate_submit_posts':1,**observed})
                    for scenario,version,steps in [('empty','9.99',6),('limited','3.12',0)]:
                        set_request(version=version,steps=steps);start=submit();wait("document.querySelector('#status').dataset.state==='result'");observed=exchange(start)
                        expected='incomplete' if scenario=='empty' else 'limited';assert observed['response']['status']==expected and observed['response']['evidence']==[]
                        assert js("document.querySelector('#no-evidence').hidden===false&&document.querySelectorAll('.source').length===0")
                        js("document.querySelector('#result').scrollIntoView({block:'start'});window.scrollBy(0,-40)");screenshot(f'{width}-{scenario}.png');records.append({'width':width,'scenario':scenario,'rendered_body_matches_wire':js("JSON.parse(document.querySelector('#raw').textContent)")==observed['response'],**observed})
                    question='<img src=x onerror="globalThis.__retrievalProbe=1"> json';set_request(question=question);start=submit();wait("document.querySelector('#status').dataset.state==='result'");observed=exchange(start)
                    assert js("!globalThis.__retrievalProbe&&document.querySelector('#returned-question').querySelectorAll('img').length===0&&document.querySelector('#returned-question').textContent.includes('<img')")
                    records.append({'width':width,'scenario':'literal_question_markup','literal_text_not_html':True,**observed})
                    # Controlled browser fault: retain actual server digest while changing body.
                    call('Fetch.enable',{'patterns':[{'urlPattern':'*/retrieve','requestStage':'Response'}]});set_request();start=submit()
                    paused=None
                    for _ in range(200):
                        js('true');paused=next((e['params'] for e in events[start:] if e.get('method')=='Fetch.requestPaused'),None)
                        if paused:break
                        time.sleep(.01)
                    assert paused is not None
                    body=call('Fetch.getResponseBody',{'requestId':paused['requestId']});raw=base64.b64decode(body['body']).decode() if body.get('base64Encoded') else body['body'];changed=json.loads(raw);changed['reason']='controlled_wire_mutation';changed_raw=json.dumps(changed,separators=(',',':'),ensure_ascii=False)
                    headers=[h for h in paused['responseHeaders'] if h['name'].lower() not in ('content-length','transfer-encoding')]
                    call('Fetch.fulfillRequest',{'requestId':paused['requestId'],'responseCode':paused['responseStatusCode'],'responseHeaders':headers,'body':base64.b64encode(changed_raw.encode()).decode()});call('Fetch.disable')
                    wait("document.querySelector('#status').dataset.state==='error'")
                    error=js("({text:document.querySelector('#status').textContent,resultHidden:document.querySelector('#result').hidden,enabled:!document.querySelector('#request-fields').disabled})")
                    assert 'Response bytes do not match' in error['text'] and error['resultHidden'] and error['enabled']
                    js("document.querySelector('#status').scrollIntoView({block:'center'})");screenshot(f'{width}-wire-refusal.png');refusals.append({'width':width,'scenario':'controlled_browser_wire_mutation','original_body_sha256':hashlib.sha256(raw.encode()).hexdigest(),'changed_body_sha256':hashlib.sha256(changed_raw.encode()).hexdigest(),'retained_headers':headers,'ui':error,'scope':'Deliberate browser interception of an actual server response, not an observed service corruption.'})
                    navigate(fault_origin,width);set_request();start=submit();wait("document.querySelector('#status').dataset.state==='error'");observed=exchange(start)
                    assert observed['http_status']==503 and observed['response']['status']=='failed' and observed['response']['evidence']==[]
                    ui=js("({text:document.querySelector('#status').textContent,resultHidden:document.querySelector('#result').hidden,enabled:!document.querySelector('#request-fields').disabled})");assert ui['resultHidden'] and ui['enabled'] and 'HTTP 503' in ui['text']
                    js("document.querySelector('#status').scrollIntoView({block:'center'})");screenshot(f'{width}-http-error.png');records.append({'width':width,'scenario':'trusted_controlled_http_failure','ui':ui,**observed})
                browser_errors=[e for e in events if e.get('method')=='Network.loadingFailed' and not e['params'].get('canceled')]
                asset_errors=[e['params']['response'] for e in events if e.get('method')=='Network.responseReceived' and e['params']['response']['status']>=400 and not e['params']['response']['url'].endswith('/retrieve')]
                runtime_exceptions=[e for e in events if e.get('method')=='Runtime.exceptionThrown']
                assert not browser_errors and not asset_errors and not runtime_exceptions,(browser_errors,asset_errors,runtime_exceptions)
        finally:
            chrome.terminate();chrome.wait(timeout=8)
    result={'execution_mode':'actual-installed-browser-to-loopback-fastapi','model_called':False,'browser_version':browser_version,'loading_observations':loading,'scenarios':records,'controlled_wire_refusals':refusals,'local_network_errors':browser_errors,'asset_http_errors':asset_errors,'runtime_exceptions':runtime_exceptions,'lifecycle':lifecycle,'fault_lifecycle':fault_lifecycle,'scope':'Actual same-origin inspector and HTTP responses; source retrieval only, no generated answer or model run. A350ms trusted fixture delay exposes loading; it is not a latency result. Wire mutation is a deliberate browser fixture.'}
    output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--captures',type=Path,required=True);args=parser.parse_args();result=run(args.output,args.captures);print(json.dumps({'execution_mode':result['execution_mode'],'scenarios':len(result['scenarios']),'controlled_wire_refusals':len(result['controlled_wire_refusals']),'widths':[r['width'] for r in result['loading_observations']],'network_errors':len(result['local_network_errors'])},sort_keys=True))
