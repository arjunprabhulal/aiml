"""Trusted local fixture; not configurable through HTTP."""
from app import create_app
from tools import DocumentationTools
class FailingTools(DocumentationTools):
    def search(self,**kwargs):raise RuntimeError('SENSITIVE_ERROR_SENTINEL')
app=create_app(FailingTools)
