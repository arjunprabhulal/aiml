"""Write cases.json: three users' memory events with focused questions, and a long replay.

Each conversation lists memory events by turn (what perfect extraction would
store, correct or forget) and questions asked after the last turn. Each
question names the facts it needs and the replaced or forgotten facts it must
not use. The long replay is 200 turns of one user's events, for storage growth.
Run this file to regenerate the fixture; the tests check that it still matches.
"""
import json
from pathlib import Path


def event(turn, text, op, attribute):
    return {'turn': turn, 'text': text, 'op': op, 'attribute': attribute}


CONVERSATIONS = [
    {
        'user': 'alice',
        'events': [
            event(3, 'I am vegetarian.', 'remember', 'diet'),
            event(5, 'The budget is 150 euros per night.', 'remember', 'budget'),
            event(8, 'We are going to Porto.', 'remember', 'city'),
            event(12, 'My passport number is P1234567.', 'remember', 'passport'),
            event(15, 'We travel from 3 to 6 November.', 'remember', 'dates'),
            event(18, 'I want a hotel near the river.', 'remember', 'hotel-area'),
            event(22, 'Raise the budget to 180 euros per night.', 'correct', 'budget'),
            event(31, 'I eat fish now, but still no meat.', 'correct', 'diet'),
            event(35, 'Please forget my passport number.', 'forget', 'passport'),
            event(40, 'Move the trip to 10 to 13 November.', 'correct', 'dates'),
            event(44, 'Bob will join us on the second day.', 'remember', 'attendee'),
        ],
        'questions': [
            {'question': 'What should I eat for dinner?', 'required': ['fish now'],
             'stale': ['I am vegetarian.'], 'forgotten': []},
            {'question': 'What is the budget per night for the hotel?', 'required': ['180 euros per night'],
             'stale': ['150 euros per night'], 'forgotten': []},
            {'question': 'When do we travel to Porto?', 'required': ['10 to 13 November', 'going to Porto'],
             'stale': ['3 to 6 November'], 'forgotten': []},
            {'question': 'Can you fill in my passport number on the form?', 'required': [],
             'stale': [], 'forgotten': ['P1234567']},
        ],
    },
    {
        'user': 'bob',
        'events': [
            event(2, 'My laptop runs Linux.', 'remember', 'laptop-os'),
            event(4, 'I need a standing desk.', 'remember', 'desk'),
            event(7, 'My home address is 12 Rua Nova.', 'remember', 'address'),
            event(11, 'I switched to macOS last week.', 'correct', 'laptop-os'),
            event(14, 'I start work at 8 in the morning.', 'remember', 'schedule'),
            event(19, 'Please delete my home address.', 'forget', 'address'),
            event(23, 'My manager is Priya.', 'remember', 'manager'),
        ],
        'questions': [
            {'question': 'Which operating system should the laptop setup guide cover?', 'required': ['macOS'],
             'stale': ['runs Linux'], 'forgotten': []},
            {'question': 'Who approves my desk order?', 'required': ['manager is Priya', 'standing desk'],
             'stale': [], 'forgotten': []},
            {'question': 'Where should the welcome package be sent?', 'required': [],
             'stale': [], 'forgotten': ['12 Rua Nova']},
        ],
    },
    {
        'user': 'chen',
        'events': [
            event(1, 'I prefer answers in short bullet points.', 'remember', 'answer-style'),
            event(6, 'My team uses PostgreSQL for the billing service.', 'remember', 'database'),
            event(9, 'The on-call rotation changes every Monday.', 'remember', 'rotation'),
            event(13, 'We moved billing to MySQL, not PostgreSQL.', 'correct', 'database'),
            event(17, 'I am allergic to peanuts.', 'remember', 'allergy'),
        ],
        'questions': [
            {'question': 'Which database does the billing service use?', 'required': ['moved billing to MySQL'],
             'stale': ['uses PostgreSQL for the billing'], 'forgotten': []},
            {'question': 'Order snacks for the team meeting.', 'required': ['allergic to peanuts'],
             'stale': [], 'forgotten': []},
            {'question': 'When does on-call change?', 'required': ['changes every Monday'],
             'stale': [], 'forgotten': []},
        ],
    },
]


def long_replay():
    """200 turns for one user: a new fact every 5 turns, a correction every 20, a forget request every 50."""
    events = []
    for turn in range(1, 201):
        if turn % 50 == 0:
            events.append(event(turn, f'Please forget note {turn // 5 - 9}.', 'forget', f'note-{turn // 5 - 9}'))
        elif turn % 20 == 0:
            events.append(event(turn, f'Change the budget to {100 + turn} euros.', 'correct', 'budget'))
        elif turn % 5 == 0:
            events.append(event(turn, f'Note {turn // 5}: a detail the user mentioned at turn {turn}.', 'remember',
                                f'note-{turn // 5}'))
        elif turn == 1:
            events.append(event(1, 'The budget is 100 euros.', 'remember', 'budget'))
    return {'user': 'dana', 'events': events, 'sample_every': 20}


def cases():
    return {'conversations': CONVERSATIONS, 'long_replay': long_replay(), 'facts_quota': 120}


if __name__ == '__main__':
    Path(__file__).with_name('cases.json').write_text(json.dumps(cases(), indent=2) + '\n')
