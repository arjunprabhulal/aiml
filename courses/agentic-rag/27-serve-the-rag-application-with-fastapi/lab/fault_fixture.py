"""Trusted local test app; failure cannot be requested through an HTTP field."""
from app import create_app
from tools import DocumentationTools

class ControlledFaultTools(DocumentationTools):
    def search(self,**arguments):
        super().search(**arguments)
        raise RuntimeError('controlled fault after native search; private-detail-must-not-leak')

app=create_app(tool_factory=ControlledFaultTools)
