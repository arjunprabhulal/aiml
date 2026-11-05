"""RAG target annotations for the existing task-independent Evals loader."""
NAME="rag-eval-dataset"
VERSION="1"
OUTPUT_FIELDS={"status":str}
GRADERS=()  # Dataset validation only; no answer grader runs in this lesson.

def validate_expected(value):
    if set(value)!={"status","targets"} or value["status"] not in {"answered","not_in_docs"} or not isinstance(value["targets"],list):
        raise ValueError("Expected status and passage targets are required.")
    for target in value["targets"]:
        fields={"source_id","chunk_id","source_version","source_text_sha256","chunk_text_sha256"}
        if not isinstance(target,dict) or set(target)!=fields or not all(isinstance(v,str)and v for v in target.values()):
            raise ValueError("Each target needs exact source/chunk/version/text hashes.")
