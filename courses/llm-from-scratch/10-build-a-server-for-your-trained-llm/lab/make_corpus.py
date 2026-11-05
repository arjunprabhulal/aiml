"""Write corpus.txt: short synthetic stories used by every build in this series.

Each story names a child, an object and its color, moves the object to a place
and hands it to a second child. The last sentence repeats the object and color,
so predicting it needs information from earlier in the story. The text is
generated from a fixed seed, so anyone can rebuild the identical file.

Run: python3 make_corpus.py          (rewrites corpus.txt)
     python3 make_corpus.py --check  (exit 1 if corpus.txt differs)
Python 3.10+, standard library only. No download.
"""
import random
import sys
from pathlib import Path

SEED = 2026
STORIES = 400
NAMES = ["mia", "leo", "ava", "sam", "zoe", "ben"]
OBJECTS = ["ball", "kite", "book", "cup", "hat", "box"]
COLORS = ["red", "blue", "green", "yellow"]
PLACES = ["park", "garden", "kitchen", "school"]


def story(rng):
    giver, taker = rng.sample(NAMES, 2)
    thing, color, place = rng.choice(OBJECTS), rng.choice(COLORS), rng.choice(PLACES)
    return (f"{giver} has a {color} {thing}. {giver} goes to the {place}. "
            f"at the {place}, {giver} gives the {thing} to {taker}. "
            f"now {taker} has the {color} {thing}.")


def corpus(seed=SEED, stories=STORIES):
    rng = random.Random(seed)
    return "\n".join(story(rng) for _ in range(stories)) + "\n"


if __name__ == "__main__":
    path = Path(__file__).with_name("corpus.txt")
    text = corpus()
    if "--check" in sys.argv:
        sys.exit(0 if path.read_text() == text else "corpus.txt is out of date")
    path.write_text(text)
    print(f"wrote {len(text)} characters, {STORIES} stories")
