from app import create_app
from tools import DocumentationTools
class BrokenTools(DocumentationTools):
    def __init__(self,snapshot):raise RuntimeError('trusted_constructor_failure')
app=create_app(BrokenTools)
