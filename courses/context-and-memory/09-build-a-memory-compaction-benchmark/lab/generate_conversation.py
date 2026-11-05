"""Write conversation.json: a fixed 50-turn conversation with labeled memory events.

Fact turns carry a `memory` label: what an application with perfect extraction
would remember, correct or forget at that turn. Other turns are filler of
varying length. Run this file to regenerate the fixture; the test suite checks
that the stored file still matches.
"""
import json
from pathlib import Path

FACTS = {
    3: ('I am vegetarian.', {'op': 'remember', 'attribute': 'diet'}),
    5: ('The budget is 150 euros per night.', {'op': 'remember', 'attribute': 'budget'}),
    8: ('We are going to Porto.', {'op': 'remember', 'attribute': 'city'}),
    12: ('My passport number is P1234567.', {'op': 'remember', 'attribute': 'passport'}),
    15: ('We travel from 3 to 6 November.', {'op': 'remember', 'attribute': 'dates'}),
    18: ('I want a hotel near the river.', {'op': 'remember', 'attribute': 'hotel-area'}),
    22: ('Raise the budget to 180 euros per night.', {'op': 'correct', 'attribute': 'budget'}),
    27: ('Book the morning flight if possible.', {'op': 'remember', 'attribute': 'flight'}),
    31: ('I eat fish now, but still no meat.', {'op': 'correct', 'attribute': 'diet'}),
    35: ('Please forget my passport number.', {'op': 'forget', 'attribute': 'passport'}),
    40: ('Move the trip to 10 to 13 November.', {'op': 'correct', 'attribute': 'dates'}),
    44: ('Bob will join us on the second day.', {'op': 'remember', 'attribute': 'attendee'}),
    47: ('I want a hotel near the river.', {'op': 'remember', 'attribute': 'hotel-area'}),
}
TOPICS = ['the agenda', 'the slides', 'the venue map', 'the team list', 'the travel policy',
          'the expense form', 'the meeting notes', 'the room layout']


def filler(turn: int) -> tuple[str, str]:
    topic = TOPICS[turn % len(TOPICS)]
    # Every fourth filler turn pastes a long document, which pushes older turns out.
    repeat = 14 if turn % 4 == 0 else 2
    body = ' '.join(f'Line {i + 1} of {topic} has routine details for the offsite.' for i in range(repeat))
    return f'Here is {topic}: {body}', f'Thanks, I read {topic}.'


def conversation() -> dict:
    turns = []
    for turn in range(1, 51):
        if turn in FACTS:
            text, label = FACTS[turn]
            turns.append({'turn': turn, 'user': text, 'assistant': 'Noted.', 'memory': label})
        else:
            user, assistant = filler(turn)
            turns.append({'turn': turn, 'user': user, 'assistant': assistant})
    return {
        'instructions': 'Answer from the conversation and the stored memories. Say when a fact is missing.',
        'turns': turns,
        'checkpoints': [
            {'after': 10, 'question': 'Summarize the trip plan so far.',
             'required': ['I am vegetarian.', '150 euros per night', 'going to Porto'], 'stale': [], 'deleted': []},
            {'after': 20, 'question': 'Summarize the trip plan so far.',
             'required': ['I am vegetarian.', '150 euros per night', 'going to Porto', '3 to 6 November',
                          'hotel near the river'], 'stale': [], 'deleted': []},
            {'after': 30, 'question': 'Summarize the trip plan so far.',
             'required': ['180 euros per night', 'going to Porto', '3 to 6 November', 'hotel near the river',
                          'morning flight'], 'stale': ['150 euros per night'], 'deleted': []},
            {'after': 40, 'question': 'Summarize the trip plan so far.',
             'required': ['fish now', '180 euros per night', 'going to Porto', '10 to 13 November',
                          'hotel near the river', 'morning flight'],
             'stale': ['I am vegetarian.', '150 euros per night', '3 to 6 November'], 'deleted': ['P1234567']},
            {'after': 50, 'question': 'Summarize the trip plan so far.',
             'required': ['fish now', '180 euros per night', 'going to Porto', '10 to 13 November',
                          'hotel near the river', 'morning flight', 'Bob will join'],
             'stale': ['I am vegetarian.', '150 euros per night', '3 to 6 November'], 'deleted': ['P1234567']},
        ],
        'budget': {'context_limit': 512, 'max_new_tokens': 128, 'margin': 32},
    }


if __name__ == '__main__':
    Path(__file__).with_name('conversation.json').write_text(json.dumps(conversation(), indent=2) + '\n')
