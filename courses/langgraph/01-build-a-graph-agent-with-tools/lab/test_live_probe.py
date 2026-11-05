"""Offline probe guards and real SDK serialization. No inference."""
import json
import socket
import sys
from types import SimpleNamespace
import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage
import live_probe as probe

@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    def refuse(*a, **k): raise AssertionError('offline network attempt')
    monkeypatch.setattr(socket.socket, 'connect', refuse)

class Scripted(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs): return self

def reply(text='', calls=None, reason='STOP', usage=True):
    return AIMessage(text, tool_calls=calls or [], response_metadata={'finish_reason':reason},
        usage_metadata={'input_tokens':10,'output_tokens':20,'total_tokens':30} if usage else None)

def call(name): return {'name':name,'args':{'number':415},'id':name+'-415'}

def test_default_refuses_before_sdk_construction(monkeypatch,capsys):
    monkeypatch.delenv('LG_LIVE_SCOPE_SHA256',raising=False)
    monkeypatch.setattr(probe,'make_model',lambda:pytest.fail('constructed SDK'))
    assert probe.main([])==2
    assert json.loads(capsys.readouterr().out)['reason']=='external_guard_required'

@pytest.mark.parametrize('marker',[None,'b'*64,True])
def test_guard_requires_exact_scope(monkeypatch,marker):
    monkeypatch.setenv('LG_LIVE_SCOPE_SHA256','a'*64)
    monkeypatch.setattr(sys,'_aiml_langgraph_guard_active',marker,raising=False)
    with pytest.raises(probe.ProbeStopped,match='external_guard_scope_mismatch'):probe.approve_guard()

def test_guard_accepts_operator_scope(monkeypatch):
    monkeypatch.setenv('LG_LIVE_SCOPE_SHA256','a'*64)
    monkeypatch.setattr(sys,'_aiml_langgraph_guard_active','a'*64,raising=False)
    assert probe.approve_guard()=='a'*64

@pytest.mark.parametrize('message,reason',[
 (reply(reason='MAX_TOKENS'),'incomplete_max_tokens'),
 (reply('partial',reason='MAX_TOKENS'),'incomplete_max_tokens'),
 (reply('blocked',reason='SAFETY'),'incomplete_finish_reason'),
 (AIMessage('missing metadata'),'incomplete_finish_reason'),
 (reply(),'incomplete_empty_answer'),
 (reply('no usage',usage=False),'incomplete_unknown_usage'),
 (reply(calls=[{'name':'get_diff','args':{'number':418},'id':'other'}]),'unexpected_tool_request')])
def test_incomplete_stops_before_tools(message,reason):
    events=[]
    model=probe.GuardedModel(Scripted(messages=iter([message])),events=lambda event,**data:events.append((event,data)))
    with pytest.raises(probe.ProbeStopped,match=reason):model.invoke([HumanMessage('q')])
    assert events[-1][0]=='model_response'

def test_fourth_call_refused_before_delegate():
    model=probe.GuardedModel(Scripted(messages=iter([reply('a')]*3)),events=lambda *a,**k:None)
    for _ in range(3):model.invoke([HumanMessage('q')])
    with pytest.raises(probe.ProbeStopped,match='model_call_limit'):model.invoke([HumanMessage('q')])
    assert model.calls[0]==3

def test_native_graph_executes_both_tools_with_matching_ids():
    model=Scripted(messages=iter([reply(calls=[call('get_diff'),call('get_ci_status')]),
        reply('PR #415 changes DEFAULT_TIMEOUT from 10 to 30; test_default_timeout expects 10.')]))
    events=[]
    result=probe.run_probe(model,events=lambda event,**data:events.append((event,data)))
    assert result['status']=='completed_requires_semantic_review' and result['model_calls']==2
    steps=[d for e,d in events if e=='graph_step']
    assert [s['node'] for s in steps]==['agent','tools','agent']
    assert {m['tool_call_id'] for m in steps[1]['messages']}=={'get_diff-415','get_ci_status-415'}
    assert 'DEFAULT_TIMEOUT = 10 -> DEFAULT_TIMEOUT = 30' in steps[1]['messages'][0]['text']

def test_missing_required_tool_evidence_is_incomplete():
    with pytest.raises(probe.ProbeStopped,match='incomplete_missing_required_tool_evidence'):
        probe.run_probe(Scripted(messages=iter([reply('PR415 DEFAULT_TIMEOUT 10 to30 test_default_timeout')])),events=lambda *a,**k:None)

def test_actual_sdk_configuration_and_max_tokens_adapter():
    from google.genai import types
    from langchain_google_genai import ChatGoogleGenerativeAI
    from graph import TOOLS
    model=ChatGoogleGenerativeAI(model=probe.MODEL,api_key='offline-placeholder-not-a-credential',vertexai=False,
       thinking_level='low',max_output_tokens=4096,max_retries=0,timeout=45)
    bound=model.bind_tools(TOOLS)
    request=model._prepare_request([HumanMessage(probe.QUESTION)],**bound.kwargs)
    config=request['config'].model_dump(mode='json',exclude_none=True)
    assert config['max_output_tokens']==4096
    assert config['thinking_config']=={'thinking_level':'LOW'}
    assert config['http_options']['timeout']==45000
    assert config['http_options']['retry_options']['attempts']==0
    assert {f['name'] for f in config['tools'][0]['function_declarations']}=={t.name for t in TOOLS}
    synthetic=types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(role='model',parts=[types.Part(text='')]),finish_reason=types.FinishReason.MAX_TOKENS)])
    model.client=SimpleNamespace(models=SimpleNamespace(generate_content=lambda **kwargs:synthetic))
    assert bound.invoke([HumanMessage(probe.QUESTION)]).response_metadata['finish_reason']=='MAX_TOKENS'


def test_public_projection_omits_opaque_provider_fields_and_thought_signatures():
    message=reply('Readable answer.').model_copy(update={
        'additional_kwargs':{'thought_signature':'opaque-secret','reasoning':'private'},
        'response_metadata':{'finish_reason':'STOP','opaque':'opaque-secret'}})
    projected=probe.public_message(message)
    output=json.dumps(projected)
    assert projected['text']=='Readable answer.' and projected['finish_reason']=='STOP'
    assert 'opaque-secret' not in output and 'additional_kwargs' not in output and 'reasoning' not in output


def test_approved_entrypoint_prints_exact_task_before_model_construction(monkeypatch,capsys):
    monkeypatch.setattr(probe,'approve_guard',lambda:'a'*64)
    def stop_before_construction():
        task=json.loads(capsys.readouterr().out)
        assert task['event']=='task' and task['question']==probe.QUESTION
        raise probe.ProbeStopped('offline_stop_before_model')
    monkeypatch.setattr(probe,'make_model',stop_before_construction)
    assert probe.main([])==2
