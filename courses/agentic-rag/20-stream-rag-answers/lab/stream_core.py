"""Locally derived application-frame replay of complete preserved model replies."""
import codecs
import hashlib
import json
from pathlib import Path

RECORDING_SHA256='193d4c3c91e66432d3717bf85dced0034b572e804cd50efc246042b574baeaa0'
DEVELOPMENT_CASES=('utf8-write','replace-file','json-result-type','backup-schedule')
MAX_TOTAL_BYTES=65536
MAX_FRAME_BYTES=8192
MAX_CONTENT_CHARS=16384
MAX_FRAMES=1000

class StreamError(ValueError):pass

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode('utf-8')).hexdigest()

def strict_json(text):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError('duplicate_json_key')
            result[key]=value
        return result
    def constant(value):raise ValueError('invalid_json_constant')
    return json.loads(text,object_pairs_hook=pairs,parse_constant=constant)

def load_binding(case_id):
    if case_id not in DEVELOPMENT_CASES:raise ValueError('development_case_required')
    raw=(Path(__file__).parent/'fixtures/recording.json').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=RECORDING_SHA256:raise ValueError('recording_hash_mismatch')
    recording=json.loads(raw)
    metadata=recording['responses'][case_id][0]['metadata']
    events=metadata['trace']['events']
    event=lambda kind:next(e for e in events if e['kind']==kind)
    request=event('model_request_ready');selected=event('context_selected')
    candidates={row['chunk_id']:row for row in event('retrieval_completed')['candidates']}
    context=[{key:candidates[chunk][key] for key in ('chunk_id','source_id','text','url')} for chunk in selected['chunk_ids']]
    messages=request['messages']
    if digest(messages)!=request['request_sha256'] or request['request_sha256']!=metadata['request_sha256']:raise ValueError('recorded_request_mismatch')
    supplied=strict_json(messages[-1][1])
    if supplied['context']!=[{'id':row['source_id'],'text':row['text']} for row in context]:raise ValueError('recorded_context_mismatch')
    binding={'case_id':case_id,'request_sha256':request['request_sha256'],'messages':messages,'schema':request['schema'],'corpus_identity':event('request_accepted')['identity'],'selected_context':context}
    return binding,metadata['raw_message']['content']

def checked_binding(binding):
    if not isinstance(binding,dict):raise ValueError('request_binding_mismatch')
    try:original,_=load_binding(binding['case_id'])
    except (KeyError,TypeError) as error:raise ValueError('request_binding_mismatch') from error
    if digest(binding)!=digest(original):raise ValueError('request_binding_mismatch')
    return original

def replay_frames(case_id,request=None,terminal='done'):
    binding,content=load_binding(case_id)
    if request is not None and digest(request)!=digest(binding):raise ValueError('request_binding_mismatch')
    if terminal not in ('done','error','cancel'):raise ValueError('invalid_local_terminal')
    if terminal!='done':content=content[:max(1,len(content)//2)]
    frames=[]
    for offset in range(0,len(content),13):
        frames.append({'sequence':len(frames)+1,'kind':'content_delta','binding_sha256':digest(binding),'text':content[offset:offset+13]})
    frame={'sequence':len(frames)+1,'kind':terminal,'binding_sha256':digest(binding)}
    if terminal!='done':frame['reason']='controlled_local_'+terminal
    frames.append(frame)
    return frames

def encode_frames(frames):
    return ''.join(json.dumps(frame,ensure_ascii=False,separators=(',',':'))+'\n' for frame in frames).encode('utf-8')

def byte_fragments(wire):
    """Arbitrary local transport fragments, unrelated to model tokens or timing."""
    sizes=(1,2,7,3,11);offset=0;index=0
    while offset<len(wire):
        size=sizes[index%len(sizes)];yield wire[offset:offset+size];offset+=size;index+=1

def validate_reply(content,binding):
    try:reply=strict_json(content)
    except (ValueError,TypeError,RecursionError) as error:raise StreamError('invalid_answer_json') from error
    if not isinstance(reply,dict) or set(reply)!={'status','answer','source_ids'}:raise StreamError('invalid_answer_schema')
    if reply['status'] not in ('answered','not_in_docs') or not isinstance(reply['answer'],str) or not reply['answer'].strip():raise StreamError('invalid_answer_schema')
    try:reply['answer'].encode('utf-8')
    except UnicodeError as error:raise StreamError('invalid_answer_schema') from error
    ids=reply['source_ids']
    if not isinstance(ids,list) or any(not isinstance(key,str) or not key for key in ids) or len(set(ids))!=len(ids):raise StreamError('invalid_answer_schema')
    known={row['source_id']:row for row in binding['selected_context']}
    if any(key not in known for key in ids):raise StreamError('unknown_context_citation')
    if (reply['status']=='answered' and not ids) or (reply['status']=='not_in_docs' and ids):raise StreamError('status_citation_mismatch')
    citations=[{'source_id':key,'chunk_id':known[key]['chunk_id'],'url':known[key]['url']} for key in ids]
    return reply,citations

class StreamConsumer:
    def __init__(self,binding):
        self.binding=checked_binding(binding);self.binding_hash=digest(self.binding)
        self.decoder=codecs.getincrementaldecoder('utf-8')('strict')
        self.buffer='';self.provisional='';self.frames=0;self.bytes_received=0;self.fragments_received=0
        self.terminal=None;self.reason=None;self.failure=None;self.transport_error=None;self.finished=False;self.events=[]
    def fail(self,code):
        self.failure=code;raise StreamError(code)
    def feed(self,data):
        if self.finished:self.fail('consumer_already_finished')
        if self.failure:self.fail(self.failure)
        if not isinstance(data,bytes):self.fail('transport_requires_bytes')
        self.bytes_received+=len(data);self.fragments_received+=1
        if self.bytes_received>MAX_TOTAL_BYTES:self.fail('stream_byte_limit')
        try:self.buffer+=self.decoder.decode(data,final=False)
        except UnicodeDecodeError:self.fail('invalid_utf8')
        while '\n' in self.buffer:
            line,self.buffer=self.buffer.split('\n',1)
            if len(line.encode('utf-8'))>MAX_FRAME_BYTES:self.fail('frame_byte_limit')
            self.process(line)
        if len(self.buffer.encode('utf-8'))>MAX_FRAME_BYTES:self.fail('frame_byte_limit')
    def process(self,line):
        if self.terminal is not None:self.fail('frame_after_terminal')
        try:frame=strict_json(line)
        except (ValueError,RecursionError):self.fail('invalid_frame_json')
        if not isinstance(frame,dict):self.fail('invalid_frame_schema')
        kind=frame.get('kind')
        expected={'sequence','kind','binding_sha256','text'} if kind=='content_delta' else {'sequence','kind','binding_sha256'} if kind=='done' else {'sequence','kind','binding_sha256','reason'}
        if kind not in ('content_delta','done','error','cancel') or set(frame)!=expected:self.fail('invalid_frame_schema')
        if type(frame['sequence']) is not int or frame['sequence']!=self.frames+1:self.fail('invalid_sequence')
        if frame['binding_sha256']!=self.binding_hash:self.fail('frame_request_mismatch')
        self.frames+=1
        if self.frames>MAX_FRAMES:self.fail('frame_count_limit')
        if kind=='content_delta':
            if not isinstance(frame['text'],str) or not frame['text']:self.fail('invalid_content_delta')
            try:frame['text'].encode('utf-8')
            except UnicodeError:self.fail('invalid_content_delta')
            self.provisional+=frame['text']
            if len(self.provisional)>MAX_CONTENT_CHARS:self.fail('content_limit')
            self.events.append({'kind':'provisional_content','sequence':frame['sequence'],'characters_received':len(self.provisional)})
        else:
            if kind!='done' and (not isinstance(frame['reason'],str) or not frame['reason'] or len(frame['reason'])>256):self.fail('invalid_terminal_reason')
            if kind!='done':
                try:frame['reason'].encode('utf-8')
                except UnicodeError:self.fail('invalid_terminal_reason')
            self.terminal=kind;self.reason=frame.get('reason');self.events.append({'kind':'local_terminal','status':kind,'sequence':frame['sequence']})
    def finish(self):
        if self.finished:self.fail('consumer_already_finished')
        self.finished=True;accepted=None;citations=[]
        if not self.failure:
            try:tail=self.decoder.decode(b'',final=True)
            except UnicodeDecodeError:self.failure='truncated_utf8';tail=''
            if not self.failure and (self.buffer or tail):self.failure='truncated_frame'
        if self.transport_error:status='error';reason=self.transport_error
        elif self.failure:status='invalid';reason=self.failure
        elif self.terminal is None:status='incomplete';reason='missing_terminal'
        elif self.terminal!='done':status='cancelled' if self.terminal=='cancel' else 'error';reason=self.reason
        else:
            try:
                accepted,citations=validate_reply(self.provisional,self.binding)
                status='complete';reason=None
                self.events.append({'kind':'validated_answer','status':accepted['status'],'source_ids':accepted['source_ids'],'answer':accepted,'citations':citations})
            except StreamError as error:status='invalid';reason=str(error)
        return {'status':status,'reason':reason,'accepted_answer':accepted,'citations':citations,'provisional_content':self.provisional,'local_terminal':self.terminal,'stats':{'bytes_received':self.bytes_received,'transport_fragments':self.fragments_received,'application_frames':self.frames},'events':self.events}

def consume(fragments,binding):
    consumer=StreamConsumer(binding)
    try:
        for fragment in fragments:consumer.feed(fragment)
    except StreamError:pass
    except OSError:
        consumer.transport_error='transport_io_error'
        consumer.events.append({'kind':'transport_error','reason':'transport_io_error'})
    return consumer.finish()
