"""Unchanged computation bodies extracted from the existing feature-store lab."""
import json
from dataclasses import dataclass

DAY = 1440


@dataclass(frozen=True)
class Feature:
    name: str
    version: int
    entity: str            # 'user' or 'item'
    window_days: int
    aggregation: str       # 'count' or 'distinct_days'

    def spec(self):
        return json.dumps([self.entity, self.window_days, self.aggregation])


def visible(events, as_of, mode='as_known'):
    """Events a computation at this cutoff may use: those that happened before it. 'as_known' also
    requires that the event had reached the log before it; 'corrected' uses every event that happened
    before the cutoff, as a later backfill sees it."""
    if mode not in ('as_known', 'corrected'):
        raise ValueError(f'unknown mode: {mode}')
    return [e for e in events if e['event_minute'] < as_of and (mode == 'corrected' or e['ingested_minute'] < as_of)]


def compute(feature, events, as_of, mode='as_known'):
    """Values for every entity seen before the cutoff. The window is [as_of - window, as_of):
    an event exactly a window earlier counts, one exactly at the cutoff does not, because the
    cutoff minute is the first minute of the next day."""
    seen = visible(events, as_of, mode)
    start = as_of - feature.window_days * DAY
    values = {e[feature.entity]: set() if feature.aggregation == 'distinct_days' else 0 for e in seen}
    for e in seen:
        if e['event_minute'] >= start:
            key = e[feature.entity]
            if feature.aggregation == 'count':
                values[key] += 1
            else:
                values[key].add(e['event_minute'] // DAY)
    return {k: len(v) if isinstance(v, set) else v for k, v in sorted(values.items())}
