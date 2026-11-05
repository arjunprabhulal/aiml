"""Offline guarded-probe checks; synthetic replies are not model inference."""
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
    def refuse(*a,**k): raise AssertionError('offline network attempt')
    monkeypatch.setattr(socket.socket,'connect',refuse)

class Scripted(GenericFakeChatModel):
    def bind_tools(self,tools,**kwargs): return self

def reply(text='',calls=None,reason='STOP'):
    return AIMessage(text,tool_calls=calls or [],response_metadata={'finish_reason':reason},
       usage_metadata={'input_tokens':10,'output_tokens':20,'total_tokens':30})

def test_default_entrypoint_refuses_before_model_construction(monkeypatch,capsys):
    monkeypatch.delenv('LG_LIVE_02_SCOPE_SHA256',raising=False)
    monkeypatch.setattr(probe,'make_model',lambda:pytest.fail('constructed model'))
    assert probe.main([])==2
    assert json.loads(capsys.readouterr().out)['reason']=='external_guard_required'

@pytest.mark.parametrize('marker',[None,'b'*64,True])
def test_scope_mismatch_refuses(monkeypatch,marker):
    monkeypatch.setenv('LG_LIVE_02_SCOPE_SHA256','a'*64)
    monkeypatch.setattr(sys,'_aiml_langgraph_02_guard_active',marker,raising=False)
    with pytest.raises(probe.ProbeStopped,match='external_guard_scope_mismatch'):probe.approve_guard()

def test_exact_scope_handshake(monkeypatch):
    monkeypatch.setenv('LG_LIVE_02_SCOPE_SHA256','a'*64)
    monkeypatch.setattr(sys,'_aiml_langgraph_02_guard_active','a'*64,raising=False)
    assert probe.approve_guard()=='a'*64

@pytest.mark.parametrize('text',['','partial'])
def test_max_tokens_is_incomplete_even_with_text(text):
    events=[]
    guarded=probe.GuardedModel(Scripted(messages=iter([reply(text,reason='MAX_TOKENS')])),events=lambda e,**d:events.append((e,d)))
    with pytest.raises(probe.ProbeStopped,match='incomplete_max_tokens'):guarded.invoke([HumanMessage('q')])
    assert events[-1][0]=='model_response'

def test_public_projection_omits_opaque_metadata():
    m=reply('Readable.').model_copy(update={'additional_kwargs':{'thought_signature':'opaque'},'response_metadata':{'finish_reason':'STOP','signature':'opaque'}})
    assert 'opaque' not in json.dumps(probe.public_message(m))

def test_next_call_after_limit_is_refused_before_delegate():
    model=probe.GuardedModel(Scripted(messages=iter([reply('answer')]*probe.MAX_CALLS)),events=lambda *a,**k:None)
    for _ in range(probe.MAX_CALLS):model.invoke([HumanMessage('q')])
    with pytest.raises(probe.ProbeStopped,match='model_call_limit'):model.invoke([HumanMessage('q')])
    assert model.calls[0]==probe.MAX_CALLS

def test_actual_installed_sdk_serialization():
    from langchain_google_genai import ChatGoogleGenerativeAI
    model=ChatGoogleGenerativeAI(model=probe.MODEL,api_key='offline-placeholder',vertexai=False,
        thinking_level='low',max_output_tokens=4096,max_retries=0,timeout=45)
    config=model._prepare_request([HumanMessage(probe.QUESTION)])['config'].model_dump(mode='json',exclude_none=True)
    assert config['thinking_config']=={'thinking_level':'LOW'} and config['max_output_tokens']==4096
    assert config['http_options']['timeout']==45000 and config['http_options']['retry_options']['attempts']==0


def test_native_remaining_steps_stops_genuine_proposed_tools_before_execution():
    call={'name':'get_ci_status','args':{'number':415},'id':'ci-415'}
    events=[]
    result=probe.run_probe(Scripted(messages=iter([reply(calls=[call])])),events=lambda e,**d:events.append((e,d)))
    assert result['status']=='completed_native_step_limit'
    assert result['path']==['agent','stop'] and result['tool_execution_count']==0 and result['model_calls']==1
    assert result['stop_reason']=='step_limit'

def test_nominal_answer_without_tool_proposal_is_not_manufactured_into_stop():
    result=probe.run_probe(Scripted(messages=iter([reply('Need to inspect CI.')])),events=lambda *a,**k:None)
    assert result['status']=='incomplete_target_branch_not_observed' and result['path']==['agent']
    assert result['boundary'].startswith('The target step-limit branch was not observed.')
