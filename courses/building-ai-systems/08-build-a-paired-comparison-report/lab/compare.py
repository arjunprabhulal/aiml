"""Paired comparison of two run records: the difference, its uncertainty and its slices.

Both runs must be comparable under harness.compare(): same case set, task,
graders, splits and trials. Every case then has a share of passing trials in
each run, and the comparison is about the per-case differences:
- the mean difference, with a 95% bootstrap interval that resamples cases, because
  the trials of one case are not independent of each other;
- the interval again with whole source groups resampled, because a generated
  variant repeats its source case's meaning and is not an independent case.
  With few groups it is computed exactly, over every possible draw, together
  with the share of draws that show no gain, so it does not depend on a seed;
- the interval computed as if every trial were independent, for contrast;
- the cases that got better, worse or stayed the same, and the trial pairs
  (same case, same trial number, so the same seed) by outcome;
- the same difference and interval for every value of every case tag (a slice),
  with the number of cases behind it.
Python standard library only.
Run: python3 compare.py runs/qwen-v1.json runs/qwen-v2.json --cases cases-robustness.json --out runs/comparison.json
"""
import argparse
import math
import random
from fractions import Fraction

import harness

COMPARISON_VERSION = "1"
RESAMPLES = 2000
SEED = 20261020  # Bootstrap seed: the interval is reproducible byte for byte.
FEW_CASES = 10   # Mark sparse slices; interval width also depends on score variation.


def mean(values):
    return math.fsum(values) / len(values)


def interval(values, rng, resamples=RESAMPLES):
    """95% percentile bootstrap interval for the mean of values, resampling them with replacement."""
    means = sorted(mean([values[rng.randrange(len(values))] for _ in values]) for _ in range(resamples))
    return [round(means[math.floor(0.025 * resamples)], 4), round(means[math.ceil(0.975 * resamples) - 1], 4)]


def grouped_interval(groups, rng, resamples=RESAMPLES):
    """95% bootstrap interval for the mean over cases, resampling whole groups of cases."""
    groups = list(groups.values())
    means = []
    for _ in range(resamples):
        drawn = [value for _ in groups for value in groups[rng.randrange(len(groups))]]
        means.append(mean(drawn))
    means.sort()
    return [round(means[math.floor(0.025 * resamples)], 4), round(means[math.ceil(0.975 * resamples) - 1], 4)]


EXACT_LIMIT = 200_000  # Enumerate every draw of groups when there are at most this many.


def compositions(total, parts):
    """Every way to write total as an ordered sum of parts nonnegative counts."""
    if parts == 1:
        yield (total,)
        return
    for first in range(total + 1):
        for rest in compositions(total - first, parts - 1):
            yield (first, *rest)


def exact_grouped(groups):
    """The bootstrap over whole groups, computed exactly instead of sampled.

    Drawing G groups with replacement from G gives every count vector c with
    probability G! / (c1! ... cG!) / G^G. Each draw's mean is the mean over all
    cases in the drawn groups. Returns the 2.5% and 97.5% points of that
    distribution, defined as in interval(), and the probability that the mean
    is at or below zero: the share of draws that show no gain.
    """
    sums = [math.fsum(values) for values in groups.values()]
    sizes = [len(values) for values in groups.values()]
    count = len(sums)
    if math.comb(2 * count - 1, count - 1) > EXACT_LIMIT:
        return None
    distribution = {}
    for counts in compositions(count, count):
        weight = Fraction(math.factorial(count), count ** count)
        for c in counts:
            weight /= math.factorial(c)
        value = round(math.fsum(c * s for c, s in zip(counts, sums)) / sum(c * n for c, n in zip(counts, sizes)), 10)
        distribution[value] = distribution.get(value, 0) + weight
    cumulative, low, high = Fraction(0), None, None
    for value, weight in sorted(distribution.items()):
        cumulative += weight
        if low is None and cumulative >= Fraction(25, 1000):
            low = value
        if high is None and cumulative >= Fraction(975, 1000):
            high = value
    no_gain = sum(w for v, w in distribution.items() if v <= 0)
    return {"interval_95": [round(low, 4), round(high, 4)], "share_at_or_below_zero": round(float(no_gain), 4),
            "draws": math.comb(2 * count - 1, count - 1)}


def shares(record):
    """Per case: the share of its trials that passed."""
    trials = record["manifest"]["trials"]
    return {case: counts["pass"] / trials
            for split in record["summary"].values() for case, counts in split["per_case"].items()}


def summarize(case_ids, before, after, rng):
    differences = [after[case] - before[case] for case in case_ids]
    return {"cases": len(case_ids),
            "baseline": round(mean([before[c] for c in case_ids]), 4),
            "candidate": round(mean([after[c] for c in case_ids]), 4),
            "difference": round(mean(differences), 4),
            "interval_95": interval(differences, rng),
            "better": sum(d > 0 for d in differences), "worse": sum(d < 0 for d in differences),
            "same": sum(d == 0 for d in differences)}


def trial_pairs(baseline, candidate):
    """Outcome pairs for the same case and trial number: both pass, only one, or neither."""
    after = {(row["case_id"], row["trial"]): row["verdict"] == "pass" for row in candidate["results"]}
    pairs = {"both_pass": 0, "only_baseline": 0, "only_candidate": 0, "neither": 0}
    for row in baseline["results"]:
        b, c = row["verdict"] == "pass", after[(row["case_id"], row["trial"])]
        pairs["both_pass" if b and c else "only_baseline" if b else "only_candidate" if c else "neither"] += 1
    return pairs


def compare(baseline, candidate, case_set):
    comparison = harness.compare(baseline, candidate)  # Raises RunError unless the runs are comparable.
    if comparison["case_set"]["sha256"] != case_set["sha256"]:
        raise harness.RunError("the run records were made with another version of the case file")
    before, after = shares(baseline), shares(candidate)
    case_ids = list(before)
    rng = random.Random(SEED)
    overall = summarize(case_ids, before, after, rng)
    # The same difference, with every trial treated as an independent observation.
    passed = {(row["case_id"], row["trial"]): row["verdict"] == "pass" for row in candidate["results"]}
    trial_differences = [passed[(row["case_id"], row["trial"])] - (row["verdict"] == "pass")
                         for row in baseline["results"]]
    overall["trial_level_interval_95"] = interval(trial_differences, rng)
    tags = {case["id"]: case.get("tags", {}) for case in case_set["cases"]}
    by_source = {}
    for case in case_ids:  # A case without a source tag is its own group.
        by_source.setdefault(tags[case].get("source", case), []).append(after[case] - before[case])
    overall["source_groups"] = len(by_source)
    exact = exact_grouped(by_source)
    if exact is not None:
        overall["source_cluster_method"] = f"exact over {exact['draws']} draws"
        overall["source_cluster_interval_95"] = exact["interval_95"]
        overall["source_no_gain_share"] = exact["share_at_or_below_zero"]
    else:
        overall["source_cluster_method"] = f"bootstrap, {RESAMPLES} resamples"
        overall["source_cluster_interval_95"] = grouped_interval(by_source, rng)
        overall["source_no_gain_share"] = None
    slices = {}
    for name in sorted({tag for case in case_ids for tag in tags[case]} - {"source"}):
        for value in sorted({tags[case].get(name) for case in case_ids if name in tags[case]}):
            members = [case for case in case_ids if tags[case].get(name) == value]
            entry = summarize(members, before, after, rng)
            entry["few_cases"] = len(members) < FEW_CASES
            slices.setdefault(name, {})[value] = entry
    return {"comparison_version": COMPARISON_VERSION, "resamples": RESAMPLES, "seed": SEED,
            "case_set": comparison["case_set"], "trials": baseline["manifest"]["trials"],
            "baseline": baseline["manifest"]["system"], "candidate": candidate["manifest"]["system"],
            "overall": overall, "trial_pairs": trial_pairs(baseline, candidate), "slices": slices,
            "cases": [{"case_id": case, "baseline": round(before[case], 4), "candidate": round(after[case], 4)}
                      for case in case_ids if before[case] != after[case]]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("baseline")
    parser.add_argument("candidate")
    parser.add_argument("--task", default="triage_task")
    parser.add_argument("--cases", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    case_set = harness.load_cases(args.cases, harness.load_task(args.task))
    result = compare(harness.read_json(args.baseline), harness.read_json(args.candidate), case_set)
    harness.write(args.out, result)
    o = result["overall"]
    print(f"difference {o['difference']:+} (95% interval {o['interval_95'][0]:+} to {o['interval_95'][1]:+}) over "
          f"{o['cases']} cases; better {o['better']}, worse {o['worse']}, same {o['same']}")


if __name__ == "__main__":
    try:
        main()
    except (harness.CaseError, harness.RunError) as error:
        raise SystemExit(f"error: {error}")
