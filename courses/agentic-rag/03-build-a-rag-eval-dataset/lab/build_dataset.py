"""Execute dataset validation and controlled invalid-label cases; no model calls."""
from pathlib import Path
from collections import Counter
import copy,json,platform,hashlib
from importlib.metadata import version
from rag_dataset import ROOT,load_questions,load_sources,validate_dataset,validate_targets,harness

def main():
    cases=load_questions();sources,passages,manifest=load_sources();locked=harness.read_json(ROOT/"data/held-out.lock.json")
    valid=validate_dataset(cases,sources,passages,locked);failures=[]
    def attempt(name,change):
        candidate=copy.deepcopy(cases);change(candidate)
        try:validate_dataset(candidate,sources,passages,locked)
        except ValueError as error:failures.append({"case":name,"error_type":type(error).__name__,"message":str(error)})
        else:raise AssertionError("Controlled invalid case was accepted: "+name)
    attempt("Wrong documentation version",lambda x:x["cases"][0]["expected"]["targets"][0].update(source_version="3.13"))
    attempt("Stale target hash",lambda x:x["cases"][0]["expected"]["targets"][0].update(source_text_sha256="0"*64))
    attempt("Answerable question without a passage",lambda x:x["cases"][0]["expected"].update(targets=[]))
    attempt("Edited held-out question",lambda x:x["cases"][4].update(input=x["cases"][4]["input"]+" Explain briefly."))
    other_lock=copy.deepcopy(locked);other_lock["case_set"]="another-dataset"
    try:validate_dataset(cases,sources,passages,other_lock)
    except ValueError as error:failures.append({"case":"Lock from another dataset","error_type":type(error).__name__,"message":str(error)})
    else:raise AssertionError("A lock for another dataset was accepted.")
    rows=[{"id":c["id"],"split":c["split"],"class":c["class"],"question":c["input"],"python_version":c["tags"]["python_version"],
           "status":c["expected"]["status"],"targets":c["expected"]["targets"],"reason":c["why"]}for c in cases["cases"]]
    report={"mode":"actual local dataset validation; no retrieval, generation or quality benchmark",**valid,
            "corpus":manifest,"questions":rows,"controlled_failures":failures,
            "held_out_scope":"Public teaching fixtures authored/frozen before future tuning; not an unseen external benchmark.",
            "environment":{"python":platform.python_version(),"packages":{p:version(p)for p in ["langchain-core","langchain-text-splitters","numpy"]}},
            "implementation_sha256":{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest()for name in ["rag_dataset.py","eval_task.py","pipeline_ids.py","build_dataset.py","vendor/evals/harness.py","vendor/evals/leakcheck.py"]}}
    run=ROOT/"runs/2026-10-22-dataset";run.mkdir(parents=True,exist_ok=True);(run/"validation.json").write_text(json.dumps(report,indent=2)+"\n")
    text="\n".join([report["mode"],"Questions: "+str(valid["counts"]["cases"]),"Sources: "+str(valid["counts"]["sources"]),"Splits: "+json.dumps(valid["counts"]["by_split"]),
         *[f"{f['case']}: {f['error_type']}"for f in failures],"Python 3.13 facts documented only; no 3.13 execution. Semantic relevance is a reviewed label, not a validated model answer."])+"\n"
    (run/"output.txt").write_text(text);print(text,end="")

if __name__=="__main__":main()
