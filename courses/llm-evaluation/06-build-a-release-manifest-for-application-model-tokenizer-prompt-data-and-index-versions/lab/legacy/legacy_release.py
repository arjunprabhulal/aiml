"""Build, verify and compare release manifests. Standard library only.

    python3 release.py build releases/r1.json --out manifests/r1.json
    python3 release.py verify manifests/r1.json --installed environments/installed.json
    python3 release.py diff manifests/r1.json manifests/r2.json

A release spec, written by hand, names the files and model pins of one release. build()
reads them and writes a manifest: the SHA-256 of every file, the model digests, what the
index was built from, and which evaluation run belongs to the release. verify() checks a
manifest against the files on disk, against the models a server has installed, and
against the rules that tie the components together. diff() lists the components that
changed between two manifests and the work each change makes necessary.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

COMPONENTS = ("application", "generator", "embedder", "tokenizer", "prompt", "data", "index", "config", "evaluation")
# Changing the key makes each listed piece of work necessary before the release can ship.
WORK = {
    "data": ["rebuild the index: embed the changed corpus", "rerun the evaluation"],
    "embedder": ["rebuild the index: embed the whole corpus", "embed the evaluation questions again",
                 "rerun the evaluation"],
    "index": ["rerun the evaluation"],
    "generator": ["pin the tokenizer of the new generator", "rerun the evaluation"],
    "tokenizer": ["rerun the evaluation"],
    "prompt": ["rerun the evaluation"],
    "application": ["rerun the evaluation"],
    "config": ["rerun the evaluation"],
}


class ReleaseError(ValueError):
    """A spec or manifest is malformed, or names a file that does not exist."""


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def file_hash(root, path):
    try:
        return sha256_bytes((Path(root) / path).read_bytes())
    except OSError as error:
        raise ReleaseError(f"cannot read {path}: {error.strerror}") from None


def read_json(root, path):
    try:
        return json.loads((Path(root) / path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReleaseError(f"cannot read {path}: {error}") from None


def files(root, paths):
    return {path: file_hash(root, path) for path in sorted(paths)}


def build(spec, root):
    """Hash every file a release spec names and record what the index and evaluation were built from."""
    if set(spec) != {"release", *COMPONENTS}:
        raise ReleaseError(f"a release spec has exactly release and {list(COMPONENTS)}")
    embedder = read_json(root, spec["embedder"])
    tokenizer = read_json(root, spec["tokenizer"])
    index_record = read_json(root, spec["index"]["record"])
    queries = read_json(root, spec["evaluation"]["query_vectors"]["record"])
    cases = read_json(root, spec["evaluation"]["cases"])
    components = {
        "application": {"files": files(root, spec["application"])},
        "generator": {key: spec["generator"][key] for key in ("publisher_model", "ollama_tag", "ollama_digest")},
        "embedder": {"files": files(root, [spec["embedder"]]),
                     **{key: embedder[key] for key in ("publisher_model", "publisher_revision", "ollama_tag",
                                                        "ollama_digest", "dimensions")}},
        "tokenizer": {"files": files(root, [spec["tokenizer"]]), "publisher_model": tokenizer["model"],
                      "revision": tokenizer["revision"], "tokenizer_files": tokenizer["files"]},
        "prompt": {"path": spec["prompt"], "sha256": file_hash(root, spec["prompt"])},
        "data": {"path": spec["data"], "sha256": file_hash(root, spec["data"])},
        "index": {"files": files(root, [spec["index"]["record"], spec["index"]["vectors"]]),
                  "built_from": {"corpus_sha256": index_record["corpus_sha256"],
                                 "embedder_digest": index_record["model"]["ollama_digest"]}},
        "config": dict(spec["config"]),
    }
    evaluation = {"cases": {"path": spec["evaluation"]["cases"], "sha256": file_hash(root, spec["evaluation"]["cases"]),
                            "case_set_sha256": sha256_bytes(canonical(cases).encode("utf-8"))},
                  "query_vectors": {"files": files(root, [spec["evaluation"]["query_vectors"]["record"],
                                                          spec["evaluation"]["query_vectors"]["vectors"]]),
                                    "embedder_digest": queries["model_digest"]},
                  "run": None}
    if spec["evaluation"]["run"] is not None:
        run = read_json(root, spec["evaluation"]["run"])
        evaluation["run"] = {"path": spec["evaluation"]["run"], "sha256": file_hash(root, spec["evaluation"]["run"]),
                             "system": run["manifest"]["system"], "case_set_sha256": run["manifest"]["case_set"]["sha256"],
                             "summary": {split: {k: v for k, v in s.items() if k in ("cases", "trials", "pass", "fail", "incomplete")}
                                         for split, s in run["summary"].items()}}
    manifest = {"release": spec["release"], "components": components, "evaluation": evaluation}
    return dict(manifest, manifest_sha256=sha256_bytes(canonical(manifest).encode("utf-8")))


def identity(manifest):
    """The harness system identity of a release: the evaluation run must carry exactly this."""
    c = manifest["components"]
    return {"name": "lesson-app", "version": manifest["release"], "mode": "live",
            "model": f"generator {c['generator']['ollama_tag']}@{c['generator']['ollama_digest']}; "
                     f"embedder {c['embedder']['ollama_tag']}@{c['embedder']['ollama_digest']}",
            "prompt": f"sha256:{c['prompt']['sha256']}",
            "tools": f"application {sha256_bytes(canonical(c['application']).encode())}; "
                     f"tokenizer {sha256_bytes(canonical(c['tokenizer']).encode())}; "
                     f"config {sha256_bytes(canonical(c['config']).encode())}",
            "index": f"corpus {c['data']['sha256']}; index {sha256_bytes(canonical(c['index']['files']).encode())}"}


def all_files(manifest):
    c, e = manifest["components"], manifest["evaluation"]
    listed = {**c["application"]["files"], **c["embedder"]["files"], **c["tokenizer"]["files"],
              c["prompt"]["path"]: c["prompt"]["sha256"], c["data"]["path"]: c["data"]["sha256"],
              **c["index"]["files"], e["cases"]["path"]: e["cases"]["sha256"], **e["query_vectors"]["files"]}
    if e["run"] is not None:
        listed[e["run"]["path"]] = e["run"]["sha256"]
    return listed


def verify(manifest, root, installed):
    """Check a manifest against the disk, the installed models and the rules between components.

    Returns one row per rule, so a report shows every problem at once, not only the first.
    """
    c, e = manifest["components"], manifest["evaluation"]
    rows = []

    def rule(name, problems):
        rows.append({"rule": name, "ok": not problems, "problems": problems})

    changed = []
    for path, expected in all_files(manifest).items():
        try:
            if file_hash(root, path) != expected:
                changed.append(f"{path} changed")
        except ReleaseError:
            changed.append(f"{path} is missing")
    rule("files match their hashes", changed)
    rule("served models match their digests",
         [f"{c[m]['ollama_tag']} is {installed.get(c[m]['ollama_tag'], 'not installed')}, "
          f"the release pins {c[m]['ollama_digest']}"
          for m in ("generator", "embedder") if installed.get(c[m]["ollama_tag"]) != c[m]["ollama_digest"]])
    built = c["index"]["built_from"]
    rule("index built from this data and embedder",
         ([f"index was built from corpus {built['corpus_sha256']}, the release data is {c['data']['sha256']}"]
          if built["corpus_sha256"] != c["data"]["sha256"] else []) +
         ([f"index was embedded by {built['embedder_digest']}, the release embedder is {c['embedder']['ollama_digest']}"]
          if built["embedder_digest"] != c["embedder"]["ollama_digest"] else []))
    rule("tokenizer belongs to the generator",
         [] if c["tokenizer"]["publisher_model"] == c["generator"]["publisher_model"] else
         [f"tokenizer is from {c['tokenizer']['publisher_model']}, the generator is {c['generator']['publisher_model']}"])
    rule("evaluation questions embedded by the release embedder",
         [] if e["query_vectors"]["embedder_digest"] == c["embedder"]["ollama_digest"] else
         [f"questions were embedded by {e['query_vectors']['embedder_digest']}"])
    if e["run"] is None:
        run_problems = ["no evaluation run is attached"]
    else:
        expected, recorded = identity(manifest), e["run"]["system"]
        run_problems = [f"evaluation ran with a different {key}" for key in ("model", "prompt", "tools", "index")
                        if recorded.get(key) != expected[key]]
        if e["run"]["case_set_sha256"] != e["cases"]["case_set_sha256"]:
            run_problems.append("evaluation ran on a different case set")
    rule("evaluation ran on this release", run_problems)
    return {"release": manifest["release"], "verified": all(row["ok"] for row in rows), "rules": rows}


def diff(old, new):
    """Components that changed, and the work that each change makes necessary, in order."""
    changed = [name for name in COMPONENTS[:-1] if old["components"][name] != new["components"][name]]
    work = []
    for name in changed:
        work += [item for item in WORK[name] if item not in work]
    # Rerunning the evaluation comes last: it must see the rebuilt index and the new pins.
    if "rerun the evaluation" in work:
        work = [item for item in work if item != "rerun the evaluation"] + ["rerun the evaluation"]
    return {"from": old["release"], "to": new["release"], "changed": changed, "work": work}


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    b = commands.add_parser("build")
    b.add_argument("spec")
    b.add_argument("--out", required=True)
    v = commands.add_parser("verify")
    v.add_argument("manifest")
    v.add_argument("--installed", required=True, help="a JSON file with models: {tag: digest}")
    d = commands.add_parser("diff")
    d.add_argument("old")
    d.add_argument("new")
    args = parser.parse_args(argv)
    root = Path.cwd()
    if args.command == "build":
        write(args.out, build(read_json(root, args.spec), root))
        return 0
    if args.command == "verify":
        report = verify(read_json(root, args.manifest), root, read_json(root, args.installed)["models"])
        for row in report["rules"]:
            print(f"{'ok  ' if row['ok'] else 'FAIL'} {row['rule']}" + "".join(f"\n       {p}" for p in row["problems"]))
        return 0 if report["verified"] else 1
    plan = diff(read_json(root, args.old), read_json(root, args.new))
    print(f"changed: {', '.join(plan['changed']) or 'nothing'}")
    for item in plan["work"]:
        print(f"  - {item}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ReleaseError as error:
        sys.exit(f"error: {error}")
