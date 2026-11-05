"""Generate original, fictional events and declared finalized outcome records.

This is a teaching fixture, not measured user behavior. Outcome values are
authored probabilistically from a fixed hash and count. They are not inferred
from the partial feature-event log. No real personal data is used.
"""
from datetime import datetime,timedelta,timezone
import hashlib,json
from pathlib import Path


def unit(key):
    return int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], 'big') / 2**64


def stamp(at):
    return at.isoformat().replace('+00:00','Z')


def fixture():
    observations,events,labels=[],[],[]
    for day in [3,4,5,6,7,8,10,11,13,14]:
        at=datetime(2026,1,day,12,tzinfo=timezone.utc)
        for user in range(24):
            entity=f'user-{user:02d}';key=f'{entity}-day-{day:02d}'
            n=int(unit('count:'+key)*9)
            observations.append(dict(id=key,entity=entity,predict_at=stamp(at)))
            for index in range(n):
                event_at=at-timedelta(hours=20)+timedelta(minutes=index*10)
                events.append(dict(id=f'{key}-event-{index}',entity=entity,event_at=stamp(event_at),arrived_at=stamp(event_at+timedelta(minutes=2))))
            events.append(dict(id=key+'-late',entity=entity,event_at=stamp(at-timedelta(minutes=10)),arrived_at=stamp(at+timedelta(minutes=5))))
            returned=int(unit('outcome:'+key)<(.12+.085*n))
            labels.append(dict(id=key,value=returned,ready_at=stamp(at+timedelta(hours=26))))
    return dict(description=__doc__.strip(),assemble_at='2026-01-16T12:00:00Z',observations=observations,events=events,labels=labels)


if __name__=='__main__':
    Path(__file__).with_name('scenario.json').write_text(json.dumps(fixture(),indent=2)+'\n')
