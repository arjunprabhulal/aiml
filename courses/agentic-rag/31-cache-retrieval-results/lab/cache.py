"""Thread-safe bounded TTL/LRU for completed materialized retrieval results."""
import copy
import json
import math
import threading
import time
from collections import OrderedDict

class ResultCache:
    def __init__(self, *, ttl=1.0,max_entries=4,max_bytes=65536,clock=time.monotonic):
        if isinstance(ttl,bool) or not isinstance(ttl,(int,float)) or not math.isfinite(ttl) or not 0<ttl<=3600:raise ValueError('invalid_ttl')
        if type(max_entries) is not int or not 1<=max_entries<=1024 or type(max_bytes) is not int or not 1<=max_bytes<=1048576:raise ValueError('invalid_capacity')
        self.ttl=ttl;self.max_entries=max_entries;self.max_bytes=max_bytes;self.clock=clock;self.entries=OrderedDict();self.bytes=0;self.lock=threading.RLock()
    def _drop(self,key):self.bytes-=self.entries.pop(key)[2]
    def _expire(self):
        now=self.clock()
        for key,(deadline,_,_) in list(self.entries.items()):
            if deadline<=now:self._drop(key)
    def get(self,key):
        with self.lock:
            self._expire()
            if key not in self.entries:return None
            self.entries.move_to_end(key)
            return copy.deepcopy(self.entries[key][1])
    def put(self,key,value):
        if not isinstance(value,dict) or value.get('status')!='completed':return False
        frozen=copy.deepcopy(value);size=len(json.dumps(frozen,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8'))+len(key.encode('utf-8'))
        with self.lock:
            self._expire()
            if key in self.entries:self._drop(key)
            if size>self.max_bytes:return False
            self.entries[key]=(self.clock()+self.ttl,frozen,size);self.bytes+=size
            while len(self.entries)>self.max_entries or self.bytes>self.max_bytes:self._drop(next(iter(self.entries)))
            return True
    def clear(self):
        with self.lock:self.entries.clear();self.bytes=0
