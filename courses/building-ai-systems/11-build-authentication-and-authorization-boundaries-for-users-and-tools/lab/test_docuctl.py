import json
from pathlib import Path
import unittest
import tokens
import docuctl_boundary as boundary
from docuctl_demo import run

class DocuctlDelegation(unittest.TestCase):
    def setUp(self):
        self.clock = boundary.FixedClock(1_800_000_000)
        self.gateway, self.services = boundary.build(self.clock)
        self.args = {'page_id': 'deploy-35'}
        self.rule = boundary.POLICY['tools']['read_page']
        self.user = tokens.verify(boundary.session_token('ana', self.clock), tokens.ISSUER, 'session+jwt', self.clock())
    def test_viewer_cannot_publish_or_mint(self):
        status, _ = self.gateway.call_tool(boundary.session_token('ben', self.clock), {'name':'publish_page','arguments':{'page_id':'deploy-35','reason':'release'}})
        self.assertEqual((status,self.gateway.minted),(403,0))
    def test_other_tenant_and_missing_page_share_404(self):
        rows={r['case']:r for r in run()['cases']}
        self.assertEqual(rows['cross-tenant-read']['status'],404)
        self.assertEqual(rows['cross-tenant-read']['result'],rows['missing-page']['result'])
    def test_unknown_tool_and_extra_tenant_are_refused(self):
        rows={r['case']:r for r in run()['cases']}
        self.assertEqual((rows['unknown-tool']['status'],rows['tenant-in-arguments']['status']),(404,400))
    def test_session_type_and_wrong_audience_are_refused(self):
        rows={r['case']:r for r in run()['cases']}
        self.assertEqual((rows['session-at-tool']['status'],rows['wrong-audience']['status']),(401,401))
    def test_delegated_token_is_single_use_and_expires_at_boundary(self):
        rows={r['case']:r for r in run()['cases']}
        self.assertEqual([rows[x]['status'] for x in ['delegated-first-use','delegated-replay','exact-expiry']],[200,401,401])
    def test_service_requires_actor_and_own_scope(self):
        base={'sub':'ana','tenant':'docuctl','scope':'docs:read','aud':'docs-service','exp':self.clock()+60,'jti':'missing-actor'}
        with self.assertRaises(boundary.Refused) as error:self.services['docs-service'].handle(tokens.sign(base,'tool+jwt'),'read_page',self.args)
        self.assertEqual(error.exception.status,403)
        base.update(act={'sub':'docuctl-docs'},scope='docs:publish',jti='wrong-scope')
        with self.assertRaises(boundary.Refused) as error:self.services['docs-service'].handle(tokens.sign(base,'tool+jwt'),'read_page',self.args)
        self.assertEqual(error.exception.status,403)
    def test_edited_signature_and_none_algorithm_are_refused(self):
        value,_=self.gateway.delegate(self.user,self.rule);head,body,mac=value.split('.')
        other=dict(self.user,tenant='another-team',scope='docs:read',aud='docs-service',act={'sub':'docuctl-docs'},jti='edited')
        edited=tokens.sign(other,'tool+jwt').split('.')[1]
        for bad in [f'{head}.{edited}.{mac}',tokens._b64(json.dumps({'alg':'none','typ':'tool+jwt'}).encode())+'.'+body+'.']:
            with self.assertRaises(boundary.Refused):self.services['docs-service'].handle(bad,'read_page',self.args)
    def test_output_is_exact_and_audit_contains_no_tokens(self):
        saved=json.loads((Path(__file__).parent/'docuctl-output.json').read_text())
        self.assertEqual(run(),saved)
        self.assertNotIn('session+jwt',json.dumps(saved['audit']))
        self.assertTrue(all('token' not in row for row in saved['audit']))

    def test_malformed_calls_and_unknown_signed_roles_are_refused(self):
        self.assertEqual(self.gateway.call_tool(boundary.session_token('ana',self.clock),None)[0],400)
        bad=tokens.sign({'sub':'ana','tenant':'docuctl','role':'invented','aud':tokens.ISSUER,'exp':self.clock()+60},'session+jwt')
        self.assertEqual(self.gateway.call_tool(bad,{'name':'read_page','arguments':self.args})[0],401)
    def test_service_validates_its_direct_tool_arguments(self):
        value,_=self.gateway.delegate(self.user,self.rule)
        with self.assertRaises(boundary.Refused) as error:self.services['docs-service'].handle(value,'missing',{})
        self.assertEqual(error.exception.status,404)

    def test_non_text_tool_names_are_refused_at_both_boundaries(self):
        for name in [None, [], {}, 12]:
            with self.subTest(name=name):
                before=self.gateway.minted
                status,_=self.gateway.call_tool(boundary.session_token('ana',self.clock), {'name':name,'arguments':self.args})
                self.assertEqual((status,self.gateway.minted-before),(404,0))
                value,_=self.gateway.delegate(self.user,self.rule)
                with self.assertRaises(boundary.Refused) as error:self.services['docs-service'].handle(value,name,self.args)
                self.assertEqual(error.exception.status,404)
    def test_actor_and_identity_claims_are_checked(self):
        base={'sub':'ana','tenant':'docuctl','scope':'docs:read','aud':'docs-service','exp':self.clock()+60,'act':{'sub':boundary.POLICY['agent']}}
        invalid=[{'act':x} for x in [None,{},'agent',{'sub':'other-agent'}]]+[{'tenant':None},{'sub':None},{'scope':[]}]
        for i,change in enumerate(invalid):
            with self.subTest(change=change):
                value=tokens.sign(dict(base,**change,jti=f'invalid-{i}'),'tool+jwt')
                with self.assertRaises(boundary.Refused):self.services['docs-service'].handle(value,'read_page',self.args)
    def test_malformed_signed_issuer_and_replay_id_are_refused(self):
        value=tokens.sign({'sub':'ana','tenant':'docuctl','role':'maintainer','aud':tokens.ISSUER,'exp':self.clock()+60,'iss':[]},'session+jwt')
        self.assertEqual(self.gateway.call_tool(value,{'name':'read_page','arguments':self.args})[0],401)
        base={'sub':'ana','tenant':'docuctl','scope':'docs:read','aud':'docs-service','exp':self.clock()+60,'act':{'sub':boundary.POLICY['agent']},'jti':[]}
        with self.assertRaises(boundary.Refused):self.services['docs-service'].handle(tokens.sign(base,'tool+jwt'),'read_page',self.args)
