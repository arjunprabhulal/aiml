"""A bounded task-specific Ollama adapter. Imported clients are used only after review."""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime,timezone
import json
import socket
import time
import httpx
from baseline_lib import CONFIG,EMBED,MODEL,MODEL_DIGESTS,Reply,query_text,digest

BASE='http://127.0.0.1:11434'


class LimitError(RuntimeError):pass


class CallGuard:
 def __init__(self,plan,passages,save=lambda:None):
  self.plan=plan;self.passages=passages;self.save=save
  self.stage=None;self.case_id=None;self.expected_input=None;self.expected_messages=None
  self.counts={'documents':0,'queries':{},'generation':{},'metadata':0}
  self.http=[];self.network=[]
 def expect(self,stage,case_id=None,text=None,messages=None):
  self.stage,self.case_id,self.expected_input,self.expected_messages=stage,case_id,text,messages
 def before(self,request):
  if request.url.scheme!='http' or request.url.host not in ('127.0.0.1','localhost','::1') or request.url.port!=11434 or request.url.query:
   raise LimitError('Only existing Ollama loopback11434 is allowed')
  body=json.loads(request.content)if request.content else None
  path=request.url.path
  if path in ('/api/embed','/api/chat'):
   total=self.counts['documents']+sum(self.counts['queries'].values())+sum(self.counts['generation'].values())
   if total>=self.plan['max_inference_http_calls']:raise LimitError('Total inference call cap')
  if (request.method,path)in (('GET','/api/tags'),('POST','/api/show')):
   if self.counts['metadata']>=3:raise LimitError('Metadata call cap')
   if path=='/api/show' and body.get('model',body.get('name'))not in (EMBED,MODEL):raise LimitError('Wrong metadata model')
   self.counts['metadata']+=1
  elif request.method=='POST' and path=='/api/embed':
   if body.get('model')!=EMBED:raise LimitError('Unexpected embedding model')
   inp=body.get('input');actual=inp if isinstance(inp,list)else[inp]
   if self.stage=='documents':
    if self.counts['documents'] or actual!=self.passages:raise LimitError('One exact four-passage batch only')
    self.counts['documents']+=1
   elif self.stage=='query':
    if self.case_id not in self.plan['case_ids'] or self.case_id in self.counts['queries'] or actual!=[self.expected_input]:raise LimitError('One exact query embedding per planned case')
    self.counts['queries'][self.case_id]=1
   else:raise LimitError('Embedding outside reviewed phase')
  elif request.method=='POST' and path=='/api/chat':
   if set(body)-{'model','messages','options','stream','format','tools'}:raise LimitError('Unreviewed generation fields')
   if self.stage!='generation' or self.case_id not in self.plan['case_ids'] or self.case_id in self.counts['generation']:raise LimitError('One generation attempt per planned case')
   if body.get('model')!=MODEL or body.get('tools') or body.get('options')!={'temperature':0,'num_predict':400}:raise LimitError('Generation options/tools/model changed')
   expected=[('user' if role=='human'else role,text)for role,text in self.expected_messages]
   actual=[(m.get('role'),m.get('content'))for m in body.get('messages',[])]
   if actual!=expected or any(m.get('images')or m.get('tool_calls')for m in body['messages']):raise LimitError('Exact input prompt changed')
   if body.get('format')!=Reply.model_json_schema():raise LimitError('Reply schema changed')
   self.counts['generation'][self.case_id]=1
  else:raise LimitError('Unapproved endpoint; no pulls, downloads, generate fallback or providers')
  total=self.counts['documents']+sum(self.counts['queries'].values())+sum(self.counts['generation'].values())
  if total>self.plan['max_inference_http_calls']:raise LimitError('Total inference call cap')
  row={'at_utc':datetime.now(timezone.utc).isoformat(),'stage':self.stage,'case_id':self.case_id,
   'method':request.method,'url':str(request.url),'body':body,'headers_saved':False}
  self.http.append(row);self.save();return row

 @contextmanager
 def installed(self):
  old_send,old_asend=httpx.Client.send,httpx.AsyncClient.send
  old_connect,old_connect_ex,old_dns=socket.socket.connect,socket.socket.connect_ex,socket.getaddrinfo
  def check(address):
   allowed=isinstance(address,tuple)and len(address)>1 and address[0]in('127.0.0.1','localhost','::1')and address[1]==11434
   self.network.append({'allowed':allowed,'address':str(address)});self.save()
   if not allowed:raise LimitError('Non-Ollama socket blocked')
  def connect(sock,address):check(address);return old_connect(sock,address)
  def connect_ex(sock,address):check(address);return old_connect_ex(sock,address)
  def dns(host,port,*a,**kw):
   if host not in ('127.0.0.1','localhost','::1',b'127.0.0.1',b'localhost',b'::1') or port!=11434:
    self.network.append({'allowed':False,'dns_host':str(host),'port':str(port)});self.save();raise LimitError('External DNS blocked')
   return old_dns(host,port,*a,**kw)
  def send(client,request,*a,**kw):
   request.read();row=self.before(request);start=time.monotonic()
   try:
    response=old_send(client,request,*a,**kw);response.read()
    row.update({'status':response.status_code,'response_text':response.text,'elapsed_seconds':time.monotonic()-start});return response
   except Exception as exc:row['error']={'type':type(exc).__name__,'message':str(exc)};raise
   finally:self.save()
  async def asend(client,request,*a,**kw):
   await request.aread();row=self.before(request);start=time.monotonic()
   try:
    response=await old_asend(client,request,*a,**kw);await response.aread()
    row.update({'status':response.status_code,'response_text':response.text,'elapsed_seconds':time.monotonic()-start});return response
   except Exception as exc:row['error']={'type':type(exc).__name__,'message':str(exc)};raise
   finally:self.save()
  httpx.Client.send,httpx.AsyncClient.send=send,asend
  socket.socket.connect,socket.socket.connect_ex,socket.getaddrinfo=connect,connect_ex,dns
  try:yield
  finally:
   httpx.Client.send,httpx.AsyncClient.send=old_send,old_asend
   socket.socket.connect,socket.socket.connect_ex,socket.getaddrinfo=old_connect,old_connect_ex,old_dns


class FreshModels:
 mode='fresh_local_inference'
 def __init__(self,guard):
  self.guard=guard
  with httpx.Client(trust_env=False,follow_redirects=False,timeout=15)as c:tags=c.get(BASE+'/api/tags').json()
  found={m.get('name',m.get('model')):m.get('digest')for m in tags.get('models',[])}
  if any(found.get(k)!=v for k,v in MODEL_DIGESTS.items()):raise LimitError('Installed model missing/digest drift; no pull or fallback')
  self.models=dict(MODEL_DIGESTS)
  from langchain_ollama import ChatOllama,OllamaEmbeddings
  self.embedder=OllamaEmbeddings(model=EMBED,base_url=BASE,client_kwargs={'timeout':120,'trust_env':False,'follow_redirects':False})
  self.model=ChatOllama(model=MODEL,base_url=BASE,temperature=0,num_predict=400,
   client_kwargs={'timeout':180,'trust_env':False,'follow_redirects':False}).with_structured_output(Reply,include_raw=True)
 def documents(self,texts):
  self.guard.expect('documents');return self.embedder.embed_documents(texts)
 def query(self,case_id,question):
  text=query_text(question);self.guard.expect('query',case_id,text=text);return self.embedder.embed_query(text)
 def generate(self,case_id,question,messages):
  self.guard.expect('generation',case_id,messages=messages)
  value=self.model.invoke(messages)
  return {'raw':value['raw'].model_dump(mode='json',exclude_none=True),'parsed':None if value['parsed']is None else value['parsed'].model_dump(),
   'parsing_error':None if value['parsing_error']is None else str(value['parsing_error'])}
