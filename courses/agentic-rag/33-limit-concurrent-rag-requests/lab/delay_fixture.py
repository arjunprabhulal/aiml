"""Trusted delay creates visible overlap; not a production latency measurement."""
import time
from app import create_app
from tools import DocumentationTools
class DelayedTools(DocumentationTools):
    def __init__(self,snapshot):super().__init__(snapshot);self.delayed=False
    def search(self,**kwargs):
        if not self.delayed:self.delayed=True;time.sleep(0.35)
        return super().search(**kwargs)
app=create_app(DelayedTools)
