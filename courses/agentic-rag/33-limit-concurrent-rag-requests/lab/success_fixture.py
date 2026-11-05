from delay_fixture import DelayedTools
from app import create_app
app=create_app(DelayedTools,wait_seconds=1)
