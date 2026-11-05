"""Trusted test-only failing factory; no public request fault switch."""
from app import create_app
from authorization import Authorization

def fail(snapshot):raise RuntimeError('private fixture detail must not leave server')
app=create_app(engine_factory=lambda:Authorization(tool_factory=fail))
