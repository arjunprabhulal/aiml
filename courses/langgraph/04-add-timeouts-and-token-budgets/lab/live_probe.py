"""Draft one-proposal async timeout observation. Requires a separate approved async guard.

This program supplies no approval. A static tools breakpoint prevents a second
model call. If the model never proposes the slow tool, the target is incomplete.
"""
from __future__ import annotations
import argparse
import asyncio
import json
import os
import sys
import time

MODEL = 'gemini-3.8-flash'
QUESTION = ("The local CI fixture says pull request #421 has failed job 815. "
            "Fetch the log for job 815 directly with fetch_job_log. Do not retry a tool, "
            "edit files, or contact a real CI service. This observation pauses after tools.")
POLICY = {'lesson': '04', 'model': MODEL, 'max_model_calls': 1,
          'max_output_tokens': 4096, 'thinking_level': 'low',
          'http_timeout_seconds': 45, 'max_retries': 0, 'vertexai': False,
          'graph_model_timeout_seconds': 60, 'interrupt_after': ['tools']}

class ProbeStopped(RuntimeError):
    """Named incomplete observation, never fabricated model output."""

def emit(event, **fields):
    print(json.dumps({'event': event, **fields}, ensure_ascii=False), flush=True)

def approve_guard():
    expected = os.environ.get('LG_LIVE_04_SCOPE_SHA256', '')
    if len(expected) != 64 or any(c not in '0123456789abcdef' for c in expected):
        raise ProbeStopped('external_async_guard_required')
    if getattr(sys, '_aiml_langgraph_04_guard_active', None) != expected:
        raise ProbeStopped('external_async_guard_scope_mismatch')
    # The external marker must certify an async guard, not the earlier sync guard.
    if getattr(sys, '_aiml_langgraph_04_async_transport_guard', None) != expected:
        raise ProbeStopped('external_async_transport_guard_required')
    return expected

def make_model():
    from langchain_google_genai import ChatGoogleGenerativeAI
    return ChatGoogleGenerativeAI(model=MODEL, thinking_level='low', max_output_tokens=4096,
                                 max_retries=0, timeout=45, vertexai=False)

def public_message(message):
    result = {'type': message.type, 'text': message.text}
    if message.type == 'ai':
        result.update(tool_calls=[{'name': c['name'], 'args': c['args'], 'id': c['id']}
                                  for c in message.tool_calls],
                      usage=message.usage_metadata,
                      finish_reason=message.response_metadata.get('finish_reason'))
    elif message.type == 'tool':
        result.update(name=message.name, tool_call_id=message.tool_call_id, status=message.status)
    return result

class GuardedModel:
    def __init__(self, model, *, calls=None, events=emit):
        self.model, self.calls, self.events = model, calls if calls is not None else [0], events

    def bind_tools(self, tools, **kwargs):
        return GuardedModel(self.model.bind_tools(tools, **kwargs), calls=self.calls, events=self.events)

    async def ainvoke(self, messages):
        if self.calls[0] >= 1:
            raise ProbeStopped('model_call_limit')
        self.calls[0] += 1
        self.events('model_request', ordinal=self.calls[0], policy=POLICY)
        try:
            reply = await self.model.ainvoke(messages)
        except Exception as error:
            # Never let provider exception strings reach graph.py's error message.
            self.events('model_failure', error_type=type(error).__name__)
            raise ProbeStopped('model_request_failed') from None
        self.events('model_response', ordinal=self.calls[0], message=public_message(reply))
        if reply.response_metadata.get('finish_reason') != 'STOP':
            raise ProbeStopped('incomplete_finish_reason')
        usage = reply.usage_metadata
        total = usage.get('total_tokens') if isinstance(usage, dict) else None
        if type(total) is not int or total < 0:
            raise ProbeStopped('incomplete_unknown_usage')
        seen, call_ids = set(), set()
        for call in reply.tool_calls:
            if not call.get('id') or call['id'] in call_ids:
                raise ProbeStopped('invalid_tool_call_id')
            call_ids.add(call['id'])
            pair = (call['name'], json.dumps(call['args'], sort_keys=True))
            if pair in seen:
                raise ProbeStopped('duplicate_tool_request')
            seen.add(pair)
            if not ((call['name'] == 'fetch_job_log' and call['args'] == {'job_id': 815}) or
                    (call['name'] == 'list_failed_jobs' and call['args'] == {'pr': 421})):
                raise ProbeStopped('unexpected_tool_request')
        return reply

async def run_probe(model, *, events=emit):
    from langchain_core.messages import HumanMessage
    import ci
    import graph
    guarded = GuardedModel(model, events=events)
    compiled = graph.build_graph(guarded, token_budget=1_000_000,
                                 model_timeout=POLICY['graph_model_timeout_seconds'])
    # The high graph budget avoids mislabeling this isolated tool-timeout task as
    # a token-budget demonstration. Only the future external operator bounds spend.
    state, path, proposals, tools = None, [], [], []
    started = time.perf_counter()
    async for kind, update in compiled.astream(
        {'messages': [HumanMessage(QUESTION)], 'tokens': 0}, {'recursion_limit': 5},
        stream_mode=['updates', 'values'], interrupt_after=['tools']):
        if kind == 'values':
            state = update
            continue
        for node, delta in update.items():
            if node == '__interrupt__':
                events('static_breakpoint', after='tools')
                continue
            path.append(node)
            if node.startswith('__error_handler__'):
                # This is control flow, not a replacement or projection of model output.
                events('graph_control_stop', node=node, status='incomplete',
                       stop_reason=delta.get('stop_reason', 'model_error'), provider_error_text_omitted=True)
                continue
            messages = [public_message(m) for m in delta.get('messages', [])]
            events('graph_step', node=node, messages=messages)
            if node == 'agent':
                proposals.extend(c for m in messages for c in m.get('tool_calls', []))
            if node == 'tools':
                tools.extend(messages)
    expected = graph.tool_timed_out(TimeoutError())
    call_ids = {c['id'] for c in proposals if c['name'] == 'fetch_job_log'}
    timeout_messages = [m for m in tools if m.get('name') == 'fetch_job_log'
                        and m.get('tool_call_id') in call_ids and m['text'] == expected]
    observed = len(timeout_messages) == 1 and path == ['agent', 'tools']
    if observed:
        classification = 'accepted tool proposal and native timeout observed; model provenance requires external HTTP receipts; no follow-up model answer'
    elif proposals:
        classification = 'accepted tool proposal but target timeout not observed; incomplete; model provenance requires external HTTP receipts'
    elif 'agent' in path:
        classification = 'accepted model reply without a target tool proposal; incomplete'
    else:
        classification = 'no accepted model reply or tool proposal; incomplete'
    result = {'status': 'observed_native_tool_timeout_before_followup' if observed else 'incomplete_target_not_observed',
              'classification': classification, 'accepted_tool_proposal': bool(proposals),
              'node_path': path, 'model_calls': guarded.calls[0], 'tool_timeout_seconds': ci.TOOL_TIMEOUT,
              'fixture_job_delay_seconds': ci.JOBS[815]['delay'], 'tools': tools,
              'reported_token_subtotal': state.get('tokens') if state else None,
              'usage_known': state.get('usage_known', False) if state else False,
              'elapsed_seconds': time.perf_counter() - started,
              'no_automatic_rerun': True, 'no_followup_model_call': True}
    events('completion', **result)
    return result

def main(argv=None):
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    try:
        approve_guard()
        emit('task', question=QUESTION, policy=POLICY)
        result = asyncio.run(run_probe(make_model()))
        return 0 if result['status'] == 'observed_native_tool_timeout_before_followup' else 2
    except ProbeStopped as error:
        emit('completion', status='incomplete', reason=str(error))
        return 2
    except Exception as error:
        emit('completion', status='failed', error_type=type(error).__name__)
        return 1

if __name__ == '__main__':
    raise SystemExit(main())
