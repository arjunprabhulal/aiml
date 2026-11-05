const byId=id=>document.getElementById(id);
const form=byId('ask-form');let current=null,active=null,generation=0;
const headers=()=>({'Content-Type':'application/json',Authorization:'Bearer '+byId('token').value});
function reset(){generation++;active?.abort();byId('submit').disabled=false;byId('result').hidden=true;byId('error').hidden=true;byId('empty-state').hidden=false;byId('status').textContent='Ready for your question.';current=null;}
for(const id of ['token','version','collection'])byId(id).addEventListener('change',reset);
for(const button of document.querySelectorAll('[data-question]'))button.addEventListener('click',()=>{byId('question').value=button.dataset.question;byId('question').focus();});
function text(tag,value){const e=document.createElement(tag);e.textContent=value;return e;}
form.addEventListener('submit',async event=>{
 event.preventDefault();const epoch=++generation;active?.abort();active=new AbortController();byId('submit').disabled=true;byId('error').hidden=true;byId('result').hidden=true;byId('empty-state').hidden=true;byId('status').textContent='Searching the selected documentation…';
 try{
  const response=await fetch('/api/ask',{method:'POST',signal:active.signal,headers:headers(),body:JSON.stringify({question:byId('question').value,version:byId('version').value,collection:byId('collection').value})});
  const data=await response.json();if(epoch!==generation)return;if(!response.ok)throw new Error(data.error||'Request failed');current=data;
  byId('answer').textContent=data.answer;byId('sources').replaceChildren();
  for(const citation of data.citations){
   const source=data.sources.find(s=>s.id===citation.source_id);const li=text('li',source.title+' · docuctl '+source.version);li.append(text('blockquote',citation.quote));
   const details=document.createElement('details');details.append(text('summary','Read the source document'));const pre=text('pre','Open to load the document.');details.append(pre);
   details.addEventListener('toggle',async()=>{if(!details.open||details.dataset.loaded)return;try{const r=await fetch('/api/sources/'+encodeURIComponent(source.document),{headers:headers()});const d=await r.json();if(!r.ok)throw new Error(d.error||'Source unavailable');pre.textContent=d.text;details.dataset.loaded='true';}catch(e){pre.textContent=e.message;}});li.append(details);byId('sources').append(li);
  }
  byId('trace').replaceChildren();for(const [label,value] of Object.entries({Provider:data.trace.provider,'Retrieval cache':data.trace.cache_hit?'Hit':'Miss',Searches:data.trace.searches,'Source reads':data.trace.source_reads,'Context bytes':data.trace.context_bytes,'Model requests':data.trace.model_requests})){byId('trace').append(text('dt',label),text('dd',String(value)));}
  byId('result').hidden=false;byId('status').textContent=data.status==='answered'?'Answer ready. Check the supporting sources below.':'No supporting documentation found.';
 }catch(e){if(epoch!==generation)return;byId('error').textContent=e.message;byId('error').hidden=false;byId('status').textContent='No answer accepted.';}
 finally{if(epoch===generation)byId('submit').disabled=false;}
});
byId('copy-answer').addEventListener('click',async()=>{if(!current)return;try{await navigator.clipboard.writeText(current.answer);byId('copy-answer').textContent='Copied';setTimeout(()=>byId('copy-answer').textContent='Copy answer',1400);}catch{byId('status').textContent='Select the answer text to copy it.';}});
fetch('/health').then(r=>r.json()).then(d=>byId('provider').textContent=d.provider==='extractive'?'Extractive baseline':'Gemini').catch(()=>byId('provider').textContent='Unavailable');
