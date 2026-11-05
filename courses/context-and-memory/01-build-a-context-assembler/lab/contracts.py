"""Validated request contract for the assembler. Standard library only."""
from dataclasses import dataclass
import math

MAX_TEXT = 16_384
MAX_TOTAL_TEXT = 131_072
MAX_ITEMS = 64


class ContractError(ValueError):
    """The request shape is invalid; nothing was counted."""


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict


@dataclass(frozen=True)
class Turn:
    user: str
    assistant: str


@dataclass(frozen=True)
class ToolExchange:
    call_id: str
    name: str
    arguments: dict
    result: str


@dataclass(frozen=True)
class Passage:
    id: str
    source: str
    text: str
    score: float


@dataclass(frozen=True)
class AssemblyRequest:
    instructions: str
    current: str
    tools: tuple[Tool, ...]
    history: tuple[Turn, ...]
    tool_exchanges: tuple[ToolExchange, ...]
    evidence: tuple[Passage, ...]
    context_limit: int
    max_new_tokens: int
    margin: int
    fill_order: tuple[str, ...] = ('history', 'evidence')


def _object(value, fields, where):
    if not isinstance(value, dict):
        raise ContractError(f'{where} must be an object')
    unknown = set(value) - set(fields)
    if unknown:
        raise ContractError(f'{where} has unsupported fields: {sorted(unknown)}')
    missing = [name for name, required in fields.items() if required and name not in value]
    if missing:
        raise ContractError(f'{where} is missing fields: {missing}')
    return value


def _text(value, where, blank_ok=False):
    if not isinstance(value, str):
        raise ContractError(f'{where} must be text')
    if len(value) > MAX_TEXT:
        raise ContractError(f'{where} exceeds {MAX_TEXT} characters')
    if not blank_ok and not value.strip():
        raise ContractError(f'{where} must contain non-whitespace text')
    return value


def _integer(value, where, low, high):
    # bool is a subclass of int; reject it explicitly.
    if type(value) is not int or not low <= value <= high:
        raise ContractError(f'{where} must be an integer from {low} to {high}')
    return value


def _items(value, where):
    if not isinstance(value, list):
        raise ContractError(f'{where} must be a list')
    if len(value) > MAX_ITEMS:
        raise ContractError(f'{where} has more than {MAX_ITEMS} items')
    return value


def parse_request(data) -> AssemblyRequest:
    fields = {'instructions': True, 'current': True, 'tools': False, 'history': False,
              'tool_exchanges': False, 'evidence': False, 'context_limit': True,
              'max_new_tokens': True, 'margin': True, 'fill_order': False}
    data = _object(data, fields, 'request')
    tools = []
    for index, item in enumerate(_items(data.get('tools', []), 'tools')):
        item = _object(item, {'name': True, 'description': True, 'parameters': True}, f'tools[{index}]')
        if not isinstance(item['parameters'], dict):
            raise ContractError(f'tools[{index}].parameters must be an object')
        tools.append(Tool(_text(item['name'], f'tools[{index}].name'),
                          _text(item['description'], f'tools[{index}].description'),
                          item['parameters']))
    names = [tool.name for tool in tools]
    if len(names) != len(set(names)):
        raise ContractError('tool names must be unique')

    history = []
    for index, item in enumerate(_items(data.get('history', []), 'history')):
        item = _object(item, {'user': True, 'assistant': True}, f'history[{index}]')
        history.append(Turn(_text(item['user'], f'history[{index}].user'),
                            _text(item['assistant'], f'history[{index}].assistant')))

    exchanges = []
    for index, item in enumerate(_items(data.get('tool_exchanges', []), 'tool_exchanges')):
        where = f'tool_exchanges[{index}]'
        item = _object(item, {'call_id': True, 'name': True, 'arguments': True, 'result': True}, where)
        if item['name'] not in names:
            raise ContractError(f'{where} calls undeclared tool {item["name"]!r}')
        if not isinstance(item['arguments'], dict):
            raise ContractError(f'{where}.arguments must be an object')
        schema = next(tool.parameters for tool in tools if tool.name == item['name'])
        missing = set(schema.get('required', [])) - set(item['arguments'])
        unknown = set(item['arguments']) - set(schema.get('properties', {}))
        if missing or unknown:
            raise ContractError(f'{where}.arguments do not match the declared parameters')
        exchanges.append(ToolExchange(_text(item['call_id'], f'{where}.call_id'), item['name'],
                                      item['arguments'], _text(item['result'], f'{where}.result', blank_ok=True)))
    call_ids = [exchange.call_id for exchange in exchanges]
    if len(call_ids) != len(set(call_ids)):
        raise ContractError('tool call IDs must be unique')

    evidence = []
    for index, item in enumerate(_items(data.get('evidence', []), 'evidence')):
        where = f'evidence[{index}]'
        item = _object(item, {'id': True, 'source': True, 'text': True, 'score': True}, where)
        score = item['score']
        if type(score) not in (int, float) or not math.isfinite(score):
            raise ContractError(f'{where}.score must be a finite number')
        evidence.append(Passage(_text(item['id'], f'{where}.id'), _text(item['source'], f'{where}.source'),
                                _text(item['text'], f'{where}.text'), float(score)))
    passage_ids = [passage.id for passage in evidence]
    if len(passage_ids) != len(set(passage_ids)):
        raise ContractError('evidence IDs must be unique')

    fill_order = data.get('fill_order', ['history', 'evidence'])
    if not isinstance(fill_order, list) or sorted(fill_order) != ['evidence', 'history']:
        raise ContractError('fill_order must list "history" and "evidence" once each')

    request = AssemblyRequest(
        instructions=_text(data['instructions'], 'instructions'),
        current=_text(data['current'], 'current'),
        tools=tuple(tools), history=tuple(history), tool_exchanges=tuple(exchanges),
        evidence=tuple(evidence),
        context_limit=_integer(data['context_limit'], 'context_limit', 128, 32_768),
        max_new_tokens=_integer(data['max_new_tokens'], 'max_new_tokens', 1, 8_192),
        margin=_integer(data['margin'], 'margin', 0, 2_048),
        fill_order=tuple(fill_order),
    )
    if request.max_new_tokens + request.margin >= request.context_limit:
        raise ContractError('output reserve and margin leave no input space')
    texts = [request.instructions, request.current]
    texts += [text for turn in history for text in (turn.user, turn.assistant)]
    texts += [exchange.result for exchange in exchanges] + [passage.text for passage in evidence]
    if sum(map(len, texts)) > MAX_TOTAL_TEXT:
        raise ContractError(f'combined text exceeds {MAX_TOTAL_TEXT} characters')
    return request
