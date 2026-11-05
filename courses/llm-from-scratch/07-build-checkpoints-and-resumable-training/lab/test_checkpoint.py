"""Tests for checkpoint.py. Run: python3 -m unittest -v test_checkpoint.py

Short training jobs check resuming; the recorded runs are repeated
only by `python3 trace_checkpoints.py --check`.
"""
import copy
import json
import inspect_inputs
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import checkpoint as ck
import train as t
from bpe import Tokenizer

HERE = Path(__file__).parent
TOK = Tokenizer.load(HERE / "tokenizer.json")
TEXT = (HERE / "corpus.txt").read_text()
RECORD = json.loads((HERE / "checkpoint-trace.json").read_text())
SHORT = dict(t.CONFIG, steps=6, eval_every=2)


class Files(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.path = self.dir / "c.json"
        ck.save(self.path, {"step": 4, "config": SHORT, "params": {"w": [0.5, -1.25]}})

    def test_round_trip_keeps_exact_values(self):
        self.assertEqual(ck.load(self.path, SHORT)["params"], {"w": [0.5, -1.25]})

    def test_atomic_write_leaves_no_temporary_file(self):
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["c.json"])

    def test_failed_rename_keeps_the_old_checkpoint(self):
        # Stop save() at the last moment: the new file is written but never renamed into place.
        with mock.patch.object(ck.os, "replace", side_effect=OSError("stopped before the rename")):
            with self.assertRaises(OSError):
                ck.save(self.path, {"step": 6, "config": SHORT, "params": {"w": [9.0, 9.0]}})
        old = ck.load(self.path, SHORT)
        self.assertEqual((old["step"], old["params"]), (4, {"w": [0.5, -1.25]}))

    def test_changed_value_is_rejected(self):
        self.path.write_text(self.path.read_text().replace("-1.25", "-1.5"))
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            ck.load(self.path, SHORT)

    def test_truncated_file_is_rejected(self):
        text = self.path.read_text()
        self.path.write_text(text[: len(text) // 2])
        with self.assertRaisesRegex(ValueError, "not valid JSON"):
            ck.load(self.path, SHORT)

    def test_different_config_is_rejected(self):
        with self.assertRaisesRegex(ValueError, r"different config: \['learning_rate'\]"):
            ck.load(self.path, dict(SHORT, learning_rate=0.02))

    def test_json_that_is_not_an_object_is_rejected(self):
        self.path.write_text("null")
        with self.assertRaisesRegex(ValueError, "does not hold a JSON object"):
            ck.load(self.path, SHORT)

    def test_other_format_version_is_rejected(self):
        data = json.loads(self.path.read_text())
        data["format_version"] = 2
        self.path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "format 2"):
            ck.load(self.path, SHORT)


class Resume(unittest.TestCase):
    def runs(self, **flags):
        work = Path(tempfile.mkdtemp())
        full = ck.run(TOK, TEXT, SHORT, work / "full")[0]
        ck.run(TOK, TEXT, SHORT, work / "cut", stop_after=2)
        resumed = ck.run(TOK, TEXT, SHORT, work / "cut", resume=True, **flags)[0]
        return json.dumps(full, sort_keys=True), json.dumps(resumed, sort_keys=True)  # every value

    def test_resume_refuses_changed_corpus(self):
        cfg=dict(SHORT,d=2,hidden=4,batch=1,steps=2,eval_every=1)
        with tempfile.TemporaryDirectory() as work:
            ck.run(TOK,TEXT,cfg,work,stop_after=1)
            with self.assertRaisesRegex(ValueError,"training inputs differ"):
                ck.run(TOK,TEXT.replace("red","blue"),cfg,work,resume=True)

    def test_resume_refuses_changed_tokenizer_with_same_vocab_size(self):
        cfg=dict(SHORT,d=2,hidden=4,batch=1,steps=2,eval_every=1)
        changed=Tokenizer(list(reversed(TOK.alphabet)),TOK.merges)
        self.assertEqual(len(changed.vocab),len(TOK.vocab))
        with tempfile.TemporaryDirectory() as work:
            ck.run(TOK,TEXT,cfg,work,stop_after=1)
            with self.assertRaisesRegex(ValueError,"training inputs differ"):
                ck.run(changed,TEXT,cfg,work,resume=True)

    def test_resume_matches_an_uninterrupted_run(self):
        full, resumed = self.runs()
        self.assertEqual(full, resumed)

    def test_resume_across_an_epoch_boundary_restores_the_shuffle(self):
        # With 56 stories per batch an epoch lasts 5 steps, so step 6 needs a fresh shuffle.
        cfg = dict(t.CONFIG, steps=6, eval_every=3, batch=56)
        work = Path(tempfile.mkdtemp())
        full = ck.run(TOK, TEXT, cfg, work / "full")[0]
        ck.run(TOK, TEXT, cfg, work / "cut", stop_after=3)
        resumed = ck.run(TOK, TEXT, cfg, work / "cut", resume=True)[0]
        self.assertEqual(json.dumps(full, sort_keys=True), json.dumps(resumed, sort_keys=True))

    def test_best_checkpoint_keeps_the_lowest_development_loss(self):
        # A deliberately high learning rate makes the development loss go up and down.
        cfg = dict(t.CONFIG, steps=6, eval_every=1, learning_rate=1.0)
        work = Path(tempfile.mkdtemp())
        _, _, dev, best = ck.run(TOK, TEXT, cfg, work)
        lowest = min(dev, key=lambda r: r["dev_loss"])
        self.assertNotEqual(lowest["step"], dev[-1]["step"])
        saved = ck.load(work / "best.json", cfg)
        self.assertEqual((saved["step"], saved["dev_loss"]), (lowest["step"], lowest["dev_loss"]))
        self.assertEqual(best, {"step": lowest["step"], "dev_loss": lowest["dev_loss"]})

    def test_resume_without_optimizer_state_differs(self):
        full, resumed = self.runs(restore_optimizer=False)
        self.assertNotEqual(full, resumed)

    def test_resume_without_shuffle_state_differs(self):
        full, resumed = self.runs(restore_shuffle=False)
        self.assertNotEqual(full, resumed)


class Recorded(unittest.TestCase):
    def test_input_identity_refusals_match_the_record(self):
        rows=inspect_inputs.inspect()
        self.assertEqual(rows,json.loads((HERE/'input-checks.json').read_text()))
        self.assertTrue(rows[0]['accepted'])
        self.assertTrue(all(not row['accepted'] for row in rows[1:]))

    def test_recorded_resume_matches_and_bugs_do_not(self):
        runs, full = RECORD["resume_runs"], RECORD["uninterrupted"]["final"]["params_sha256"]
        self.assertEqual(runs["resumed"]["params_sha256"], full)
        self.assertNotEqual(runs["resumed_without_optimizer_state"]["params_sha256"], full)
        self.assertNotEqual(runs["resumed_without_shuffle_state"]["params_sha256"], full)

    def test_best_checkpoint_is_the_lowest_development_loss(self):
        best = RECORD["best_checkpoint"]
        lowest = min(RECORD["uninterrupted"]["dev_loss"], key=lambda r: r["dev_loss"])
        self.assertEqual((best["step"], best["dev_loss"]), (lowest["step"], lowest["dev_loss"]))

    def test_params_hash_detects_one_changed_value(self):
        p = {"w": [0.5, -1.25]}
        q = {"w": [0.5, -1.2500000000000002]}
        self.assertNotEqual(ck.params_sha256(p), ck.params_sha256(q))

    def test_saved_best_checkpoint_reproduces_its_scores(self):
        data = ck.load(HERE / "best.json", t.CONFIG)
        _, _, test = t.split_stories(TEXT)
        te = t.encode_all(TOK, test, t.CONFIG["max_len"])
        self.assertEqual(ck.params_sha256(data["params"]), RECORD["best_checkpoint"]["params_sha256"])
        self.assertEqual(round(t.mean_loss(data["params"], te), 4), RECORD["best_checkpoint"]["test_loss"])
        self.assertEqual(t.color_recall(data["params"], TOK, test), RECORD["best_checkpoint"]["color_recall"])


if __name__ == "__main__":
    unittest.main()
