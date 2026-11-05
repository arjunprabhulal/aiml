"""Bounded local structured spans; deliberately no question or passage fields."""
from contextvars import ContextVar
from contextlib import contextmanager
from collections import OrderedDict
import threading
import uuid

current_trace=ContextVar('current_trace',default=None)
current_span=ContextVar('current_span',default=None)
class Recorder:
    def __init__(self,max_traces=32,max_spans=32):
        if any(type(x) is not int or not 1<=x<=1024 for x in (max_traces,max_spans)):raise ValueError('invalid_recorder_limit')
        self.max_traces=max_traces;self.max_spans=max_spans;self._traces=OrderedDict();self._lock=threading.RLock();self.dropped_traces=0;self.dropped_spans=0
    @contextmanager
    def request(self):
        trace_id=uuid.uuid4().hex
        with self._lock:
            self._traces[trace_id]=[]
            while len(self._traces)>self.max_traces:
                self._traces.popitem(last=False);self.dropped_traces+=1
        token=current_trace.set(trace_id);parent=current_span.set(None)
        try:
            with self.span('request'):yield trace_id
        finally:current_span.reset(parent);current_trace.reset(token)
    @contextmanager
    def span(self,name):
        if name not in {'request','admission','search','read','error'}:raise ValueError('invalid_span_name')
        trace_id=current_trace.get()
        if trace_id is None:raise RuntimeError('missing_request_context')
        with self._lock:
            rows=self._traces.get(trace_id)
            if rows is None or len(rows)>=self.max_spans:
                self.dropped_spans+=1;rows=None
            row={'trace_id':trace_id,'span_id':uuid.uuid4().hex,'parent_span_id':current_span.get(),'order':len(rows)+1 if rows is not None else 0,'name':name,'status':'running'}
            if rows is not None:rows.append(row)
        token=current_span.set(row['span_id'])
        try:yield row
        except BaseException:
            with self._lock:row['status']='error'
            raise
        else:
            with self._lock:
                if row['status']=='running':row['status']='ok'
        finally:current_span.reset(token)
    def snapshot(self):
        with self._lock:return {key:[dict(row) for row in rows] for key,rows in self._traces.items()}

    def mark_response(self,code):
        with self._lock:
            rows=self._traces.get(current_trace.get())
            if rows:rows[0]['status']='error' if code>=500 else 'ok'
    def stats(self):
        import json
        with self._lock:return {'retained_traces':len(self._traces),'dropped_traces':self.dropped_traces,'dropped_spans':self.dropped_spans,'serialized_utf8_bytes':len(json.dumps(self.snapshot(),separators=(',',':')).encode()),'max_traces':self.max_traces,'max_spans_per_trace':self.max_spans,'maximum_span_utf8_bytes':320,'maximum_retained_utf8_bytes':self.max_traces*(self.max_spans*320+40)+2}
