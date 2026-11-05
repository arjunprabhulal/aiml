"""Join existing task checks and capacity admission at an application boundary."""
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent / 'vendor'))
from gate import Gate, Refused as CapacityRefused, finish_worker
import harness
from architecture import Request, answer
import task


@dataclass(frozen=True)
class Policy:
    max_source_bytes: int = 1024
    max_output_bytes: int = 512
    max_active: int = 1
    max_waiting: int = 1
    wait_seconds: float = 0.02

    def __post_init__(self):
        for field, maximum in [('max_source_bytes', 1_048_576), ('max_output_bytes', 65_536)]:
            if type(getattr(self, field)) is not int or not 1 <= getattr(self, field) <= maximum:
                raise ValueError('invalid byte budget: ' + field)
        Gate(self.max_active, self.max_waiting, self.wait_seconds)

    def gate(self):
        return Gate(self.max_active, self.max_waiting, self.wait_seconds)


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def invoke(case, pages):
    return answer(Request(**case['input']['request']), pages)


async def handle(case, raw_source, policy, gate, application=invoke):
    if not isinstance(policy, Policy) or not isinstance(gate, Gate) or any(getattr(gate, field) != getattr(policy, field) for field in ('max_active', 'max_waiting', 'wait_seconds')):
        raise ValueError('capacity gate must match the declared policy')
    if not isinstance(raw_source, bytes):
        raise ValueError('source snapshot must be bytes')
    result = {'called': False, 'source_bytes': len(raw_source), 'output_bytes': 0,
              'quality': {'verdict': 'not_run'}, 'resource_status': 'not_admitted',
              'response': None, 'meets_contract': False, 'policy': asdict(policy)}
    if len(raw_source) > policy.max_source_bytes:
        return dict(result, resource_status='source_too_large')
    try:
        pages = json.loads(raw_source)
        if not isinstance(pages, list):
            raise ValueError('expected a source list')
    except (ValueError, UnicodeError):
        return dict(result, resource_status='source_invalid')

    def call_application():
        result['called'] = True
        return application(case, pages)

    try:
        async with gate.lease():
            try:
                output = await finish_worker(call_application)
            except Exception as error:
                quality = harness.judge_error(case, error)
                response = {'refused': str(error)} if quality['verdict'] == 'pass' else {'error': type(error).__name__}
            else:
                quality = ({'verdict': 'incomplete', 'reason': 'no output'} if output is None
                           else harness.grade(case, output, tuple(task.GRADERS) + harness.CORE_GRADERS))
                response = output
            try:
                produced = encode(response)
            except (TypeError, ValueError):
                return dict(result, quality=quality, resource_status='output_not_serializable')
            resource_status = 'within_limits' if len(produced) <= policy.max_output_bytes else 'output_too_large'
            meets = resource_status == 'within_limits' and quality['verdict'] == 'pass'
            return dict(result, output_bytes=len(produced), quality=quality, resource_status=resource_status,
                        response=response if meets else None, meets_contract=meets)
    except CapacityRefused as error:
        return dict(result, resource_status=str(error))
