"""Trusted controlled fixtures, never selected by public request fields."""
from inspector_app import create_inspector_app

delayed_app=create_inspector_app(fixture_delay_seconds=.35)
fault_app=create_inspector_app(controlled_fault=True)
