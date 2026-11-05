"""Saved artifact and failure-boundary checks. No SDK request or new inference."""
import hashlib
import json
from pathlib import Path
import struct

ROOT = Path(__file__).parent
GOOD = ROOT / 'runs/20261023-genuine-gemini'
FAILED = ROOT / 'runs/20261023-incomplete-preflight'

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def test_recorded_genuine_tool_timeout_matches_proposal():
    manifest = json.loads((GOOD / 'manifest.json').read_text())
    events = json.loads((GOOD / 'events.json').read_text())
    assert events == [json.loads(line) for line in (GOOD / 'stdout.txt').read_text().splitlines()]
    model = next(e['message'] for e in events if e['event'] == 'model_response')
    tool = next(e['messages'][0] for e in events if e['event'] == 'graph_step' and e['node'] == 'tools')
    assert model['finish_reason'] == 'STOP'
    assert model['tool_calls'] == [{'name': 'fetch_job_log', 'args': {'job_id': 815}, 'id': 'call_97095'}]
    assert tool['tool_call_id'] == model['tool_calls'][0]['id']
    assert tool['status'] == 'error' and 'did not finish within 3s' in tool['text']
    assert manifest['node_path'] == ['agent', 'tools'] and manifest['static_breakpoint_after'] == 'tools'
    assert manifest['generation_requests'] == manifest['token_count_requests'] == 1
    assert manifest['followup_generation_requests'] == 0
    assert manifest['provider_usage']['total_tokens'] == 224 + 20 + 159 == 403
    assert sha(GOOD / 'stdout.txt') == manifest['stdout_sha256']
    assert sha(GOOD / 'events.json') == manifest['events_sha256']
    for name, digest in manifest['source_sha256'].items():
        assert sha(ROOT / name) == digest

def test_recorded_preflight_failure_is_not_inference():
    manifest = json.loads((FAILED / 'manifest.json').read_text())
    events = json.loads((FAILED / 'events.json').read_text())
    assert manifest['generation_requests'] == 0 and manifest['count_requests'] == 1
    assert manifest['provider_generation_usage'] is None
    assert manifest['accepted_model_replies'] == manifest['tool_executions'] == 0
    assert manifest['native_tool_timeout_observed'] is False
    assert not any(e['event'] == 'model_response' for e in events)
    assert not any(e['event'] == 'graph_step' and e['node'] == 'tools' for e in events)
    assert events[-1]['status'] == 'incomplete_target_not_observed'
    assert events[-1]['usage_known'] is False and events[-1]['reported_token_subtotal'] == 0
    assert sha(FAILED / 'stdout.txt') == manifest['stdout_sha256']
    assert sha(FAILED / 'events.json') == manifest['events_sha256']

def test_original_completed_images_match_saved_hashes_and_dimensions():
    manifest = json.loads((GOOD / 'manifest.json').read_text())
    assert len(manifest['images']) == 3
    for image in manifest['images']:
        path = GOOD / image['file']
        assert sha(path) == image['sha256']
        width, height = struct.unpack('>II', path.read_bytes()[16:24])
        assert (width, height) == (image['width_pixels'], image['height_pixels'])
        assert width == image['width_css'] * image['device_scale_factor']
