// Real same-origin HTTP inspector. No model or browser-side retrieval fallback.
export const bounds = Object.freeze({max_steps:12,max_searches:3,max_reads:3,max_source_bytes:4096});
export function readRequest(values) {
  const question=values.question,version=values.version;
  if(typeof question!=='string'||!question.trim()||Array.from(question).length>512)throw new Error('Enter a nonblank question within the supported length.');
  if(typeof version!=='string'||version.length>16||!/^\d+\.\d+$/.test(version))throw new Error('Use a documentation version such as 3.12.');
  const request={question,version};
  for(const [key,max] of Object.entries(bounds)) {
    const value=values[key];
    if(typeof value!=='string'||!/^\d+$/.test(value))throw new Error('Use whole numbers for every allowance.');
    const number=Number(value);
    if(!Number.isSafeInteger(number)||number<0||number>max)throw new Error('An allowance is outside its supported range.');
    request[key]=number;
  }
  return request;
}
export function canonical(value) {
  if(Array.isArray(value))return '['+value.map(canonical).join(',')+']';
  if(value!==null&&typeof value==='object')return '{'+Object.keys(value).sort().map(k=>JSON.stringify(k)+':'+canonical(value[k])).join(',')+'}';
  return JSON.stringify(value);
}
export async function textDigest(text) {
  const bytes=new TextEncoder().encode(text);
  return [...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(b=>b.toString(16).padStart(2,'0')).join('');
}
export async function requestDigest(request,corpusId) {return textDigest(canonical({request,corpus_id:corpusId}));}
export async function decodeWire(text,digest) {
  if(typeof text!=='string'||new TextEncoder().encode(text).length>200000||typeof digest!=='string'||!/^[a-f0-9]{64}$/.test(digest))throw new Error('Missing or oversized response receipt.');
  if(await textDigest(text)!==digest)throw new Error('Response bytes do not match the server receipt.');
  return JSON.parse(text);
}
export async function validateResponse(packet,request,corpusId) {
  if(!packet||typeof packet!=='object'||packet.model_called!==false||packet.schema_version!==1||packet.execution_mode!=='offline-scripted-retrieval-http')throw new Error('Unsupported response contract.');
  if(packet.corpus_id!==corpusId||canonical(packet.request)!==canonical(request)||packet.request_id!==await requestDigest(request,corpusId))throw new Error('Response does not match this request and corpus.');
  const limits=Object.fromEntries(Object.keys(bounds).map(k=>[k,request[k]]));
  if(packet.admission?.accepted!==true||canonical(packet.admission.limits)!==canonical(limits))throw new Error('Response admission settings changed.');
  if(!['completed','incomplete','limited','failed'].includes(packet.status)||typeof packet.reason!=='string'||!/^[a-f0-9]{64}$/.test(packet.result_sha256))throw new Error('Invalid result status.');
  if(!Array.isArray(packet.trace)||!Array.isArray(packet.evidence)||packet.trace.length>request.max_steps+1||packet.evidence.length>request.max_reads)throw new Error('Invalid result collections.');
  for(const key of ['steps','searches','reads','reserved_source_bytes','delivered_source_bytes'])if(!Number.isSafeInteger(packet.usage?.[key])||packet.usage[key]<0)throw new Error('Invalid usage counters.');
  if(packet.usage.steps>request.max_steps||packet.usage.searches>request.max_searches||packet.usage.reads>request.max_reads||packet.usage.reserved_source_bytes>request.max_source_bytes||packet.usage.delivered_source_bytes>packet.usage.reserved_source_bytes)throw new Error('Usage exceeds the admitted request.');
  for(const row of packet.evidence) {
    if(!row||row.corpus_id!==corpusId||row.version!==request.version||typeof row.source_id!=='string'||typeof row.text!=='string'||!/^[a-f0-9]{64}$/.test(row.passage_id)||!/^[a-f0-9]{64}$/.test(row.text_sha256)||!Number.isSafeInteger(row.start_line)||row.start_line<1||!Number.isSafeInteger(row.end_line)||row.end_line<row.start_line)throw new Error('Invalid evidence metadata.');
    if(new TextEncoder().encode(row.text).length!==row.byte_count||await textDigest(row.text)!==row.text_sha256)throw new Error('Source text does not match its byte and hash receipt.');
    let url;try{url=new URL(row.url);}catch{throw new Error('Invalid source link.');}
    if(url.protocol!=='https:')throw new Error('Unsupported source link scheme.');
  }
  return packet;
}
function element(tag,text,className) {const node=document.createElement(tag);if(text!==undefined)node.textContent=String(text);if(className)node.className=className;return node;}
export function renderResult(packet) {
  const result=document.querySelector('#result');
  document.querySelector('#outcome').textContent=packet.status+' · '+packet.reason;
  document.querySelector('#request-id').textContent='Request '+packet.request_id;
  document.querySelector('#returned-question').textContent='Question: '+packet.request.question;
  const usage=document.querySelector('#usage');usage.replaceChildren();
  const names={steps:'Admitted steps',searches:'Search attempts',reads:'Read attempts',reserved_source_bytes:'Reserved source bytes',delivered_source_bytes:'Validated delivered bytes'};
  for(const [key,name] of Object.entries(names)){const group=element('div');group.append(element('dt',name),element('dd',packet.usage[key]));usage.append(group);}
  const trace=document.querySelector('#trace');trace.replaceChildren();
  for(const event of packet.trace){const row=element('tr');const action=event.action;const label=action?.tool==='search'?action.arguments.query:action?.tool==='read'?action.arguments.handle.source_id:'not invoked';row.append(element('td',action?.tool??'refused'),element('td',label),element('td',event.decision),element('td',event.status??event.reason??''));trace.append(row);}
  const evidence=document.querySelector('#evidence');evidence.replaceChildren();
  document.querySelector('#no-evidence').hidden=packet.evidence.length!==0;
  for(const source of packet.evidence){const article=element('article',undefined,'source');article.append(element('h4',source.source_id),element('p','Documentation '+source.version+' · lines '+source.start_line+'–'+source.end_line,'provenance'),element('blockquote',source.text));const a=element('a','Open the primary documentation');a.href=source.url;a.target='_blank';a.rel='noopener noreferrer';article.append(a,element('p','Passage '+source.passage_id,'provenance'),element('p','Text SHA-256 '+source.text_sha256,'provenance'));evidence.append(article);}
  document.querySelector('#raw').textContent=JSON.stringify(packet,null,2);
  document.querySelector('#copy').textContent='Copy response JSON';
  document.querySelector('#raw-details').open=false;
  result.hidden=false;
}
async function mount() {
  const fields=document.querySelector('#request-fields'),status=document.querySelector('#status'),form=document.querySelector('#retrieval-form');let busy=false,ready=false,corpusId=null;
  function setStatus(state,text){status.dataset.state=state;status.textContent=text;}
  try{const response=await fetch('/health',{cache:'no-store',credentials:'omit'});if(!response.ok)throw new Error('Service is not ready.');const health=await response.json();if(health.status!=='ok'||health.mode!=='offline-scripted-retrieval'||!/^[a-f0-9]{64}$/.test(health.corpus_id))throw new Error('Unexpected service identity.');corpusId=health.corpus_id;document.querySelector('#corpus-id').textContent=corpusId;ready=true;fields.disabled=false;setStatus('ready','Ready for a local request.');}
  catch(error){setStatus('error','Connection failed. '+error.message);document.querySelector('#reconnect').hidden=false;}
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(busy||!ready)return;
    document.querySelector('#result').hidden=true;let request;
    try{request=readRequest(Object.fromEntries(new FormData(form)));}catch(error){setStatus('error',error.message);return;}
    busy=true;fields.disabled=true;setStatus('loading','Retrieval is running. Waiting for the local response…');
    const abort=new AbortController(),timer=setTimeout(()=>abort.abort(),10000);
    try{
      const response=await fetch('/retrieve',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(request),credentials:'omit',cache:'no-store',signal:abort.signal});
      const text=await response.text();
      if(!response.ok){let errorPacket;try{errorPacket=JSON.parse(text);}catch{}const reason=errorPacket?.error?.code??errorPacket?.reason??'request_failed';throw new Error('HTTP '+response.status+' · '+reason);}
      const packet=await decodeWire(text,response.headers.get('X-Retrieval-Body-SHA256'));
      await validateResponse(packet,request,corpusId);renderResult(packet);setStatus('result','Local response received: '+packet.status+'. Inspect the evidence and trace.');
    }catch(error){document.querySelector('#result').hidden=true;setStatus('error',error.name==='AbortError'?'Browser wait ended. The server may still be running the request.':'Request failed. '+error.message);}
    finally{clearTimeout(timer);busy=false;fields.disabled=false;}
  });
  document.querySelector('#copy').addEventListener('click',async()=>{const button=document.querySelector('#copy');try{await navigator.clipboard.writeText(document.querySelector('#raw').textContent);button.textContent='Copied';}catch{button.textContent='Select JSON to copy';}});
}
if(typeof document!=='undefined')mount();
