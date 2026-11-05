"""Reconstruct features at prediction time; admit only ready outcome labels."""
from collections import Counter
from datetime import datetime, timedelta

FEATURE_WINDOW = timedelta(days=1)
OUTCOME_WINDOW = timedelta(days=1)


def instant(value):
    try:
        at = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (AttributeError, TypeError, ValueError) as error:
        raise ValueError('time must be an ISO UTC timestamp') from error
    if at.tzinfo is None or at.utcoffset().total_seconds() != 0:
        raise ValueError('time must have a UTC offset')
    return at


def check_id(value):
    if not isinstance(value, str) or not value or len(value) > 100:
        raise ValueError('IDs must be bounded nonempty strings')


def validate(observations, events, labels):
    seen = set()
    known = {}
    for observation in observations:
        if not isinstance(observation, dict) or set(observation) != {'id', 'entity', 'predict_at'}:
            raise ValueError('observation needs id, entity and predict_at')
        check_id(observation['id']); check_id(observation['entity'])
        if observation['id'] in seen:
            raise ValueError('duplicate observation ID')
        seen.add(observation['id'])
        known[observation['id']] = instant(observation['predict_at'])
    seen = set()
    for event in events:
        if not isinstance(event, dict) or set(event) != {'id', 'entity', 'event_at', 'arrived_at'}:
            raise ValueError('event needs identity and both event/arrival times')
        check_id(event['id']); check_id(event['entity'])
        if event['id'] in seen:
            raise ValueError('duplicate event ID')
        seen.add(event['id'])
        if instant(event['arrived_at']) < instant(event['event_at']):
            raise ValueError('an event cannot arrive before it happens')
    seen = set()
    for label in labels:
        if not isinstance(label, dict) or set(label) != {'id', 'value', 'ready_at'}:
            raise ValueError('label needs observation ID, value and ready_at')
        check_id(label['id'])
        if label['id'] in seen or label['id'] not in known:
            raise ValueError('duplicate or unknown label observation ID')
        seen.add(label['id'])
        if type(label['value']) is not int or label['value'] not in (0, 1):
            raise ValueError('label value must be integer 0 or 1')
        if instant(label['ready_at']) < known[label['id']] + OUTCOME_WINDOW:
            raise ValueError('this cohort requires a finalized full outcome window')


def feature_events(observation, events, require_arrival=True):
    """The event-only variant is a retrospective diagnostic, not a training input."""
    at = instant(observation['predict_at'])
    return sorted(event['id'] for event in events
                  if event['entity'] == observation['entity']
                  and at - FEATURE_WINDOW <= instant(event['event_at']) < at
                  and (not require_arrival or instant(event['arrived_at']) < at))


def assemble(observations, events, labels, as_of):
    validate(observations, events, labels)
    assembled_at = instant(as_of)
    by_id = {label['id']: label for label in labels}
    rows, excluded = [], []
    for observation in sorted(observations, key=lambda row: row['id']):
        label = by_id.get(observation['id'])
        if instant(observation['predict_at']) > assembled_at:
            reason = 'prediction_in_future'
        elif label is None:
            reason = 'label_missing'
        elif instant(label['ready_at']) > assembled_at:
            reason = 'label_pending'
        else:
            ids = feature_events(observation, events)
            rows.append(dict(observation, feature_count=len(ids), feature_event_ids=ids,
                             label=label['value'], label_ready_at=label['ready_at']))
            continue
        excluded.append({'id': observation['id'], 'reason': reason})
    return {'as_of': as_of, 'rows': rows, 'excluded': excluded,
            'exclusion_counts': dict(sorted(Counter(row['reason'] for row in excluded).items()))}
