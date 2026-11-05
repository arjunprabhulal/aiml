"""Instrument actual admitted core invocations without logging their arguments."""
from service import retrieve
from tools import DocumentationTools

def traced_retrieve(payload,snapshot,recorder,factory=DocumentationTools):
    class TracedTools:
        def __init__(self,snapshot):self.inner=factory(snapshot)
        def __getattr__(self,name):return getattr(self.inner,name)
        def search(self,**kwargs):
            with recorder.span('admission'):pass
            try:
                with recorder.span('search'):return self.inner.search(**kwargs)
            except Exception:
                with recorder.span('error'):pass
                raise
        def read(self,handle):
            with recorder.span('admission'):pass
            try:
                with recorder.span('read'):return self.inner.read(handle)
            except Exception:
                with recorder.span('error'):pass
                raise
    code,body=retrieve(payload,snapshot,TracedTools)
    if body['status']=='limited':
        with recorder.span('admission') as row:row['status']='denied'
    return code,body
