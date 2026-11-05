"""Validate RAG-specific source targets; reuse the existing Evals contracts."""
from pathlib import Path
import hashlib
import sys
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pipeline_ids import chunk_id

ROOT=Path(__file__).parent
sys.path.insert(0,str(ROOT/"vendor/evals"))
import harness
import leakcheck
import eval_task

class TargetError(ValueError):
    pass
class SplitBoundaryError(ValueError):
    pass

def text_sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def load_sources(path=ROOT/"data/sources.json", manifest_path=ROOT/"data/corpus-manifest.json"):
    sources=harness.read_json(path);manifest=harness.read_json(manifest_path)
    if not isinstance(sources,list)or not sources or any(not isinstance(s.get("id"),str)or not s["id"].strip()for s in sources)or len({s["id"]for s in sources})!=len(sources):
        raise TargetError("Source IDs must be nonempty and unique.")
    if hashlib.sha256(harness.canonical(sources).encode()).hexdigest()!=manifest["sources_sha256"]:
        raise TargetError("Source snapshot changed; review the corpus and its targets together.")
    settings=manifest["splitter"]
    passages=RecursiveCharacterTextSplitter(chunk_size=settings["chunk_size"],chunk_overlap=settings["chunk_overlap"]).split_documents([
        Document(page_content=s["text"],metadata={"id":s["id"],"url":s["url"],"version":s["version"]})for s in sources])
    return sources,passages,manifest

def load_questions(path=ROOT/"data/cases.json"):
    return harness.load_cases(path,eval_task)

def validate_targets(cases,sources,passages):
    source_by_id={s["id"]:s for s in sources};chunk_by_id={chunk_id(p):p for p in passages};families={}
    for case in cases["cases"]:
        tags=case.get("tags",{});version=tags.get("python_version");family=tags.get("intent_family")
        if not isinstance(case["input"],str)or not case["input"].strip()or not family or not version:
            raise TargetError(f"{case['id']}: question, version and intent family are required.")
        if case["class"]not in {"answerable","unsupported","version_specific"}:
            raise TargetError(f"{case['id']}: unknown question class.")
        families.setdefault(family,set()).add(case["split"])
        status,targets=case["expected"]["status"],case["expected"]["targets"]
        if status=="answered"and not targets:
            raise TargetError(f"{case['id']}: an answerable question needs a relevant passage target.")
        if status=="not_in_docs"and targets:
            raise TargetError(f"{case['id']}: an unsupported question must not name a relevant target.")
        if (case["class"]=="unsupported")!=(status=="not_in_docs"):
            raise TargetError(f"{case['id']}: class and answerability label disagree.")
        if len({t["chunk_id"]for t in targets})!=len(targets):
            raise TargetError(f"{case['id']}: duplicate passage target.")
        for target in targets:
            source=source_by_id.get(target["source_id"]);passage=chunk_by_id.get(target["chunk_id"])
            if source is None or passage is None or passage.metadata["id"]!=target["source_id"]:
                raise TargetError(f"{case['id']}: source or chunk target does not exist in this snapshot.")
            if target["source_version"]!=version or source["version"]!=version or passage.metadata["version"]!=version:
                raise TargetError(f"{case['id']}: source version does not match the question version.")
            if target["source_text_sha256"]!=text_sha(source["text"])or target["chunk_text_sha256"]!=text_sha(passage.page_content):
                raise TargetError(f"{case['id']}: target text hash is stale.")
    if any(len(splits)>1 for splits in families.values()):
        raise SplitBoundaryError("Related intent-family questions cross the development/held_out boundary.")
    return {"cases":len(cases["cases"]),"sources":len(sources),"passages":len(passages),
            "by_split":{split:sum(c["split"]==split for c in cases["cases"])for split in harness.SPLITS},
            "by_class":{kind:sum(c["class"]==kind for c in cases["cases"])for kind in ["answerable","unsupported","version_specific"]}}

def validate_dataset(cases,sources,passages,locked):
    if not isinstance(locked,dict)or locked.get("case_set")!=cases["name"]:
        raise SplitBoundaryError("Lock belongs to a different dataset.")
    counts=validate_targets(cases,sources,passages)
    findings=leakcheck.check_overlap(cases)+leakcheck.check_sources(cases)+leakcheck.check_lock(locked,cases)
    if findings:
        raise SplitBoundaryError("Split review required: "+harness.canonical(findings))
    return {"dataset_sha256":cases["sha256"],"counts":counts,"split_findings":findings,
            "validation":"question/target relationships and split lock accepted; semantic relevance still needs review"}
