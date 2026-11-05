"""Meaning-preserving perturbations of an issue. Each one is deterministic for a given text."""
import random
import re

CODE = re.compile(r"(`[^`]*`)")  # code spans stay exact: a typo in a command changes its meaning


def _prose(text: str, change) -> str:
    return "".join(part if CODE.fullmatch(part) else change(part) for part in CODE.split(text))


def typos(text: str, rate: float = 0.15) -> str:
    """Swap two different inner letters in about one word in seven, and in at least one word, outside code spans."""
    rng = random.Random(text)
    words = [m for part in CODE.split(text) if not CODE.fullmatch(part) for m in re.findall(r"[A-Za-z]{4,}", part)]
    picked = set(rng.sample(range(len(words)), max(1, round(rate * len(words))))) if words else set()
    counter = iter(range(len(words)))

    def swap(word: str) -> str:
        if next(counter) not in picked:
            return word
        spots = [i for i in range(1, len(word) - 2) if word[i] != word[i + 1]]
        if not spots:
            return word
        i = rng.choice(spots)
        return word[:i] + word[i + 1] + word[i] + word[i + 2:]

    return _prose(text, lambda prose: re.sub(r"[A-Za-z]{4,}", lambda m: swap(m.group()), prose))


def lowercase(text: str) -> str:
    return _prose(text, str.lower)


def shouting(text: str) -> str:
    return _prose(text, str.upper)


def pleasantries(text: str) -> str:
    return f"Hi team, hope you are well!\n\n{text}\n\nThanks a lot for maintaining tracker :)"


def log_paste(text: str) -> str:
    """Append the kind of debug log reporters paste below an issue."""
    lines = [f"2026-10-19 09:14:{s:02d} DEBUG tracker.http GET /api/tasks?page={s} 200 OK" for s in range(30)]
    return f"{text}\n\n```\n" + "\n".join(lines) + "\n```"


PERTURBATIONS = {f.__name__: f for f in (typos, lowercase, shouting, pleasantries, log_paste)}


if __name__ == "__main__":
    import sys
    for name, change in PERTURBATIONS.items():
        lines = change(sys.argv[1]).splitlines()
        more = f"\n... {len(lines) - 6} more lines" if len(lines) > 6 else ""
        print(f"--- {name}\n" + "\n".join(lines[:6]) + more)
