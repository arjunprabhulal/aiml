import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from rag_dataset import (ROOT,load_sources,load_questions,validate_dataset,validate_targets,
                         text_sha,TargetError,SplitBoundaryError,harness,leakcheck)
from pipeline_ids import chunk_id

class DatasetTests(unittest.TestCase):
    def setUp(self):
        self.cases=load_questions();self.sources,self.passages,self.manifest=load_sources()
        self.locked=harness.read_json(ROOT/"data/held-out.lock.json")
    def validate(self):return validate_dataset(self.cases,self.sources,self.passages,self.locked)
    def target(self,source_id):
        source=next(s for s in self.sources if s["id"]==source_id);passage=next(p for p in self.passages if p.metadata["id"]==source_id)
        return {"source_id":source_id,"chunk_id":chunk_id(passage),"source_version":source["version"],"source_text_sha256":text_sha(source["text"]),"chunk_text_sha256":text_sha(passage.page_content)}
    def test_actual_dataset_has_all_source_bound_targets_and_expected_classes(self):
        result=self.validate();self.assertEqual(result["counts"],{"cases":8,"sources":4,"passages":4,"by_split":{"development":4,"held_out":4},"by_class":{"answerable":3,"unsupported":3,"version_specific":2}})
        self.assertEqual(result["split_findings"],[])
    def test_wrong_declared_version_is_refused(self):
        self.cases["cases"][0]["expected"]["targets"][0]["source_version"]="3.13"
        with self.assertRaisesRegex(TargetError,"version"):self.validate()
    def test_existing_other_version_source_is_not_relevant_to_312_request(self):
        self.cases["cases"][4]["expected"]["targets"]=[self.target("path-read-3-13")]
        with self.assertRaisesRegex(TargetError,"version"):validate_targets(self.cases,self.sources,self.passages)
    def test_stale_source_hash_is_refused(self):
        self.cases["cases"][0]["expected"]["targets"][0]["source_text_sha256"]="0"*64
        with self.assertRaisesRegex(TargetError,"hash"):self.validate()
    def test_stale_chunk_hash_is_refused(self):
        self.cases["cases"][0]["expected"]["targets"][0]["chunk_text_sha256"]="0"*64
        with self.assertRaisesRegex(TargetError,"hash"):self.validate()
    def test_unknown_chunk_is_refused_even_with_a_real_source(self):
        self.cases["cases"][0]["expected"]["targets"][0]["chunk_id"]="unknown"
        with self.assertRaisesRegex(TargetError,"does not exist"):self.validate()
    def test_chunk_from_other_source_cannot_be_attached_to_source_id(self):
        self.cases["cases"][0]["expected"]["targets"][0]["chunk_id"]=self.target("json-text")["chunk_id"]
        with self.assertRaisesRegex(TargetError,"does not exist"):self.validate()
    def test_answerable_case_needs_a_relevant_target(self):
        self.cases["cases"][0]["expected"]["targets"]=[]
        with self.assertRaisesRegex(TargetError,"needs a relevant"):self.validate()
    def test_unsupported_case_cannot_list_a_relevant_target(self):
        self.cases["cases"][3]["expected"]["targets"]=[self.target("json-text")]
        with self.assertRaisesRegex(TargetError,"unsupported"):self.validate()
    def test_question_class_and_answerability_must_agree(self):
        self.cases["cases"][0]["class"]="unsupported"
        with self.assertRaisesRegex(TargetError,"disagree"):self.validate()
    def test_blank_question_and_missing_intent_family_are_refused(self):
        for field in ["question","family"]:
            with self.subTest(field=field):
                self.cases=load_questions()
                if field=="question":self.cases["cases"][0]["input"]=" "
                else:self.cases["cases"][0]["tags"].pop("intent_family")
                with self.assertRaisesRegex(TargetError,"required"):self.validate()
    def test_related_intent_family_stays_in_one_split(self):
        self.cases["cases"][4]["tags"]["intent_family"]=self.cases["cases"][0]["tags"]["intent_family"]
        with self.assertRaisesRegex(SplitBoundaryError,"intent-family"):self.validate()
    def test_lock_for_another_dataset_is_refused(self):
        self.locked["case_set"]="different-question-set"
        with self.assertRaisesRegex(SplitBoundaryError,"different dataset"):self.validate()

    def test_held_out_question_edits_do_not_silently_refresh_the_lock(self):
        original=copy.deepcopy(self.locked);self.cases["cases"][4]["input"]+=" Explain briefly."
        with self.assertRaisesRegex(SplitBoundaryError,"lock"):self.validate()
        self.assertEqual(self.locked,original)
    def test_existing_lock_detects_changed_labels_added_removed_or_moved_cases(self):
        for change in ["label","added","removed","moved"]:
            with self.subTest(change=change):
                cases=copy.deepcopy(self.cases)
                if change=="label":cases["cases"][4]["expected"]["targets"]=[]
                if change=="added":case=copy.deepcopy(cases["cases"][4]);case["id"]="extra-held";cases["cases"].append(case)
                if change=="removed":cases["cases"].pop(4)
                if change=="moved":cases["cases"][4]["split"]="development"
                self.assertTrue(leakcheck.check_lock(self.locked,cases))
    def test_paraphrase_parent_cannot_cross_the_split_boundary(self):
        self.cases["cases"][4]["tags"]["source"]=self.cases["cases"][0]["id"]
        with self.assertRaisesRegex(SplitBoundaryError,"source"):self.validate()
    def test_semantic_relevance_is_not_proved_by_structural_validation(self):
        self.cases["cases"][0]["expected"]["targets"]=[self.target("json-text")]
        result=self.validate()
        self.assertEqual(result["counts"]["cases"],8) # Valid IDs/hashes can still be the wrong human label.
    def test_existing_loader_rejects_duplicate_case_ids(self):
        with tempfile.TemporaryDirectory()as tmp:
            path=Path(tmp)/"cases.json";data={k:v for k,v in self.cases.items()if k!="sha256"};data["cases"][1]["id"]=data["cases"][0]["id"];path.write_text(json.dumps(data))
            with self.assertRaisesRegex(harness.CaseError,"unique"):load_questions(path)
    def test_existing_dataset_hash_changes_on_label_edit_not_json_whitespace(self):
        with tempfile.TemporaryDirectory()as tmp:
            path=Path(tmp)/"cases.json";data={k:v for k,v in self.cases.items()if k!="sha256"};path.write_text(json.dumps(data,indent=5));self.assertEqual(load_questions(path)["sha256"],self.cases["sha256"])
            data["cases"][0]["why"]+=" Reviewed.";path.write_text(json.dumps(data));self.assertNotEqual(load_questions(path)["sha256"],self.cases["sha256"])
    def test_source_changes_require_a_reviewed_snapshot(self):
        with tempfile.TemporaryDirectory()as tmp:
            path=Path(tmp)/"sources.json";sources=copy.deepcopy(self.sources);sources[0]["text"]+=" Changed.";path.write_text(json.dumps(sources))
            with self.assertRaisesRegex(TargetError,"snapshot changed"):load_sources(path)
    def test_blank_source_id_is_refused_before_snapshot_comparison(self):
        with tempfile.TemporaryDirectory()as tmp:
            path=Path(tmp)/"sources.json";sources=copy.deepcopy(self.sources);sources[0]["id"]="";path.write_text(json.dumps(sources))
            with self.assertRaisesRegex(TargetError,"Source IDs"):load_sources(path)
    def test_chunk_ids_change_with_content_and_keep_versioned_source_identity(self):
        p=copy.deepcopy(self.passages[0]);old=chunk_id(p);p.page_content+=" Changed.";self.assertNotEqual(chunk_id(p),old)
        ids=[chunk_id(p)for p in self.passages if p.metadata["id"]in["path-read","path-read-3-13"]];self.assertEqual(len(set(ids)),2)
    def test_313_source_is_explicitly_documented_only(self):
        source=next(s for s in self.manifest["sources"]if s["version"]=="3.13")
        self.assertEqual(source["verification"],"documented_only")

if __name__=="__main__":unittest.main()
