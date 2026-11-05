"""Exercise docuctl delegation with authored tool proposals; no model or network call."""
import json
import docuctl_boundary as boundary
import tokens


def run():
    clock = boundary.FixedClock(1_800_000_000)
    gateway, services = boundary.build(clock)
    cases = [
        ('maintainer-read', 'ana', {'name': 'read_page', 'arguments': {'page_id': 'deploy-35'}}),
        ('viewer-publish', 'ben', {'name': 'publish_page', 'arguments': {'page_id': 'deploy-35', 'reason': 'release'}}),
        ('cross-tenant-read', 'ana', {'name': 'read_page', 'arguments': {'page_id': 'private-page'}}),
        ('missing-page', 'ana', {'name': 'read_page', 'arguments': {'page_id': 'missing'}}),
        ('tenant-in-arguments', 'ana', {'name': 'read_page', 'arguments': {'page_id': 'deploy-35', 'tenant': 'another-team'}}),
        ('unknown-tool', 'ana', {'name': 'export_all', 'arguments': {}}),
        ('maintainer-publish', 'ana', {'name': 'publish_page', 'arguments': {'page_id': 'deploy-35', 'reason': 'correction'}}),
    ]
    rows = []
    for name, who, call in cases:
        before = gateway.minted
        status, result = gateway.call_tool(boundary.session_token(who, clock), call)
        rows.append({'case': name, 'status': status, 'minted': gateway.minted-before, 'result': result})
    user = tokens.verify(boundary.session_token('ana', clock), tokens.ISSUER, 'session+jwt', clock())
    rule = boundary.POLICY['tools']['read_page']
    token, _ = gateway.delegate(user, rule)
    rows.append({'case': 'delegated-first-use', 'status': 200, 'result': services['docs-service'].handle(token, 'read_page', {'page_id': 'deploy-35'})})
    def attempt(name, service, value):
        try:
            service.handle(value, 'read_page', {'page_id': 'deploy-35'})
            raise AssertionError('expected rejection')
        except boundary.Refused as error:
            rows.append({'case': name, 'status': error.status, 'check': error.check})
    attempt('delegated-replay', services['docs-service'], token)
    token, _ = gateway.delegate(user, rule)
    attempt('wrong-audience', services['publish-service'], token)
    attempt('session-at-tool', services['docs-service'], boundary.session_token('ana', clock))
    token, _ = gateway.delegate(user, rule)
    clock.advance(boundary.POLICY['delegated_token_seconds'])
    attempt('exact-expiry', services['docs-service'], token)
    return {'execution_mode': 'authored proposals; local simulated services; no model request',
            'clock': 'simulated Unix seconds', 'tool_effects': 'returned data only; no page is published',
            'cases': rows, 'audit': gateway.audit}

if __name__ == '__main__':
    print(json.dumps(run(), indent=2))
