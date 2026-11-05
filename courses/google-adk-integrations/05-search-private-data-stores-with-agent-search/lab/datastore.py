"""Create, check or delete the lesson's Agent Search data store: four private engineering documents.

python datastore.py create   # creates the data store and adds private/*.txt with a team field
python datastore.py status   # lists each document and whether it is indexed
python datastore.py delete   # deletes the data store, waits, and confirms it is gone
"""
import json
import os
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

from google.api_core import exceptions  # noqa: E402
from google.cloud import discoveryengine_v1 as de  # noqa: E402

HERE = Path(__file__).resolve().parent
PROJECT = os.environ["GOOGLE_CLOUD_PROJECT"]
STORE_ID = os.environ.get("DOCS_SEARCH_STORE", "aiml-lesson-agent-search")  # data stores take no labels; the ID carries the lesson tag
COLLECTION = f"projects/{PROJECT}/locations/global/collections/default_collection"
STORE = f"{COLLECTION}/dataStores/{STORE_ID}"
BRANCH = f"{STORE}/branches/default_branch"
# User ADC has no quota project; Discovery Engine requires one, so name it on each client.
OPTIONS = {"quota_project_id": PROJECT}


def create() -> None:
    stores = de.DataStoreServiceClient(client_options=OPTIONS)
    operation = stores.create_data_store(
        parent=COLLECTION, data_store_id=STORE_ID,
        data_store=de.DataStore(
            display_name="aiml lesson: search-private-data-stores-with-agent-search",
            industry_vertical=de.IndustryVertical.GENERIC,
            solution_types=[de.SolutionType.SOLUTION_TYPE_SEARCH],
            content_config=de.DataStore.ContentConfig.CONTENT_REQUIRED))
    operation.result(timeout=600)
    documents = de.DocumentServiceClient(client_options=OPTIONS)
    for path in sorted((HERE / "private").glob("*.txt")):
        text = path.read_text(encoding="utf-8")
        team = next(line.split(":", 1)[1].strip() for line in text.splitlines() if line.startswith("Team:"))
        documents.create_document(parent=BRANCH, document_id=path.stem, document=de.Document(
            json_data=json.dumps({"title": text.splitlines()[0], "team": team}),
            content=de.Document.Content(raw_bytes=text.encode(), mime_type="text/plain")))


def status() -> list[tuple[str, str]]:
    documents = de.DocumentServiceClient(client_options=OPTIONS)
    return [(d.id, "indexed" if d.index_time else "not indexed yet")
            for d in documents.list_documents(parent=BRANCH)]


def delete() -> None:
    stores = de.DataStoreServiceClient(client_options=OPTIONS)
    try:
        stores.delete_data_store(name=STORE).result(timeout=600)
    except exceptions.GoogleAPICallError as error:
        # google-cloud-discoveryengine 0.13.12 raised "Long-running operation had neither response
        # nor error set" for a delete that succeeded, so check the store itself before trusting it.
        print(f"delete operation: {error}")
    try:
        stores.get_data_store(name=STORE)
    except exceptions.NotFound:
        return
    raise SystemExit(f"{STORE_ID} still exists")


if __name__ == "__main__":
    command = sys.argv[1] if sys.argv[1:] else "status"
    if command == "create":
        create()
        print(f"created {STORE_ID}")
    elif command == "status":
        print(status())
    elif command == "delete":
        delete()
        print(f"deleted {STORE_ID}")
