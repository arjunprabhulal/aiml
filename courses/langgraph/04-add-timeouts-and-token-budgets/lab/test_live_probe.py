"""Scoped offline tests. Actual SDK/async graph, scripted replies; never inference."""
import asyncio
import json
import socket
import sys
import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
import ci
import live_probe as probe

@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
 def deny(*a,**kw):raise AssertionError('Offline source draft forbids network')
 for name in ['connect','connect_ex']:monkeypatch.setattr(socket.socket,name,deny)
 for name in ['create_connection','getaddrinfo']:monkeypatch.setattr(socket,name,deny)

class Scripted(GenericFakeChatModel):
 def bind_tools(self,tools,**kwargs):return self

def reply(*,calls=None,text='',reason='STOP',usage=True):
 return AIMessage(text,tool_calls=calls or [],response_metadata={'finish_reason':reason},usage_metadata={'input_tokens':30,'output_tokens':20,'total_tokens':50} if usage else None)
def call(name='fetch_job_log',args=None,ident='slow'):
 return {'name':name,'args':{'job_id':815} if args is None else args,'id':ident}
def native(messages,monkeypatch,timeout=.01):
 monkeypatch.setattr(ci,'TOOL_TIMEOUT',timeout)
 events=[]
 model=Scripted(messages=iter(messages))
 result=asyncio.run(probe.run_probe(model,events=lambda e,**d:events.append((e,d))))
 return result,events

def test_default_refuses_before_sdk_or_secret(monkeypatch,capsys):
 monkeypatch.delenv('LG_LIVE_04_SCOPE_SHA256',raising=False)
 monkeypatch.setattr(probe,'make_model',lambda:pytest.fail('SDK constructor before guard'))
 assert probe.main([])==2
 assert json.loads(capsys.readouterr().out)['reason']=='external_async_guard_required'

@pytest.mark.parametrize('field',['_aiml_langgraph_04_guard_active','_aiml_langgraph_04_async_transport_guard'])
def test_async_marker_required_in_addition_to_scope(monkeypatch,field):
 monkeypatch.setenv('LG_LIVE_04_SCOPE_SHA256','a'*64)
 monkeypatch.setattr(sys,'_aiml_langgraph_04_guard_active','a'*64,raising=False)
 monkeypatch.setattr(sys,'_aiml_langgraph_04_async_transport_guard','a'*64,raising=False)
 monkeypatch.delattr(sys,field)
 with pytest.raises(probe.ProbeStopped):probe.approve_guard()

def test_exact_scoped_async_guard_is_accepted(monkeypatch):
 monkeypatch.setenv('LG_LIVE_04_SCOPE_SHA256','a'*64)
 monkeypatch.setattr(sys,'_aiml_langgraph_04_guard_active','a'*64,raising=False)
 monkeypatch.setattr(sys,'_aiml_langgraph_04_async_transport_guard','a'*64,raising=False)
 assert probe.approve_guard()=='a'*64

def test_real_tool_timeout_after_scripted_proposal_and_no_followup(monkeypatch):
 result,events=native([reply(calls=[call()])],monkeypatch)
 assert result['status']=='observed_native_tool_timeout_before_followup'
 assert result['node_path']==['agent','tools'] and result['model_calls']==1
 assert result['tools'][0]['tool_call_id']=='slow'
 assert result['tools'][0]['text']=='The tool call did not finish within 0.01s, so its result is unknown. This says nothing about the CI job itself. Do not retry.'
 assert result['reported_token_subtotal']==50 and result['usage_known'] is True
 assert len([e for e,d in events if e=='model_request'])==1
 assert any(e=='static_breakpoint' for e,d in events)

def test_an_answer_without_target_tool_is_incomplete_without_rerun(monkeypatch):
 result,events=native([reply(text='CI seems unhealthy.')],monkeypatch)
 assert result['status']=='incomplete_target_not_observed'
 assert result['accepted_tool_proposal'] is False
 assert result['classification']=='accepted model reply without a target tool proposal; incomplete'
 assert result['model_calls']==1 and result['tools']==[]

def test_list_only_is_incomplete_not_forced_into_slow_branch(monkeypatch):
 result,events=native([reply(calls=[call('list_failed_jobs',{'pr':421},'list')])],monkeypatch,timeout=.5)
 assert result['status']=='incomplete_target_not_observed'
 assert result['tools'][0]['name']=='list_failed_jobs'
 assert result['model_calls']==1

@pytest.mark.parametrize('message',[reply(calls=[call(args={'job_id':812})]),reply(reason='MAX_TOKENS'),reply(text='reply',usage=False),reply(calls=[call(),call(ident='other')])])
def test_invalid_reply_stops_before_tools_without_invented_outcome(monkeypatch,message):
 result,events=native([message],monkeypatch)
 assert result['status']=='incomplete_target_not_observed' and result['tools']==[]
 assert not any(e=='graph_step' and d['node']=='tools' for e,d in events)
 assert any(e=='graph_control_stop' for e,d in events)

def test_second_model_call_refused_before_delegate():
 model=probe.GuardedModel(Scripted(messages=iter([reply(text='One')])) ,events=lambda *a,**k:None)
 async def go():
  await model.ainvoke([])
  with pytest.raises(probe.ProbeStopped,match='model_call_limit'):await model.ainvoke([])
 asyncio.run(go());assert model.calls[0]==1

def test_provider_exception_text_does_not_leak(monkeypatch):
 class Failing:
  def bind_tools(self,*a,**kw):return self
  async def ainvoke(self,*a,**kw):raise RuntimeError('synthetic-secret-key-must-not-be-printed')
 events=[];result=asyncio.run(probe.run_probe(Failing(),events=lambda e,**d:events.append((e,d))))
 assert result['status']=='incomplete_target_not_observed'
 assert result['accepted_tool_proposal'] is False
 assert result['classification']=='no accepted model reply or tool proposal; incomplete'
 assert 'synthetic-secret-key' not in json.dumps(events)
 assert any(e=='model_failure' and d['error_type']=='RuntimeError' for e,d in events)

def test_public_projection_omits_opaque_provider_metadata():
 m=reply(text='Actual reply.').model_copy(update={'additional_kwargs':{'thought_signature':'opaque-private'},'response_metadata':{'finish_reason':'STOP','opaque':'opaque-private'}})
 p=probe.public_message(m);assert p['text']=='Actual reply.' and 'opaque-private' not in json.dumps(p)

def test_installed_sdk_request_configuration_without_generation():
 from langchain_google_genai import ChatGoogleGenerativeAI
 from langchain_core.messages import HumanMessage
 import graph
 model=ChatGoogleGenerativeAI(model=probe.MODEL,api_key='OFFLINE-NON-CREDENTIAL-PLACEHOLDER',thinking_level='low',max_output_tokens=4096,max_retries=0,timeout=45,vertexai=False)
 bound=model.bind_tools(graph.TOOLS)
 prepared=model._prepare_request([HumanMessage(probe.QUESTION)],**bound.kwargs)
 config=prepared['config'].model_dump(mode='json',exclude_none=True)
 assert config['max_output_tokens']==4096
 assert config['thinking_config']=={'thinking_level':'LOW'}
 assert config['http_options']['timeout']==45000 and config['http_options']['retry_options']['attempts']==0
 assert {d['name'] for d in config['tools'][0]['function_declarations']}=={'fetch_job_log','list_failed_jobs'}
