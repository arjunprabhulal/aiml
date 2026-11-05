"""Offline tests: recorded answers and vectors only, no model server and no network. Python 3.11+.

    python3 -m unittest -v test_rag.py
"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import answer_model
import context_probe
import embed_model
import evaluate
import rag
import sources as source_module
from pngio import Canvas, decode_png, encode_png

ROOT = Path(__file__).resolve().parent
MANIFEST = json.loads((ROOT / 'model-manifest.json').read_text())
QUESTIONS = json.loads((ROOT / 'questions.json').read_text())['questions']
SOURCES = source_module.load_sources()
BY_ID = {s['id']: s for s in SOURCES}
NUM_CTX = MANIFEST['generation_options']['num_ctx']


def load(name):
    return json.loads((ROOT / name).read_text())


def no_network(*args, **kwargs):
    raise AssertionError('A test tried to open a network connection.')


def reply(parsed, done='stop', prompt=600, output=80):
    text = parsed if isinstance(parsed, str) else json.dumps(parsed)
    return {'text': text, 'done_reason': done, 'prompt_tokens': prompt, 'output_tokens': output, 'total_ms': 1}


def labels_for(mode, *ids):
    _, _, labels = rag.assemble('q', [(BY_ID[i], 1.0) for i in ids], mode)
    return labels


def claim(source, quote, text='a claim'):
    return {'text': text, 'source': source, 'quote': quote}


class RecordedRun(unittest.TestCase):
    def test_recorded_run_reproduces(self):
        with mock.patch('answer_model.urlopen', no_network), mock.patch('embed_model.urlopen', no_network):
            embedder, model = rag.models('replay')
            result = evaluate.evaluate(QUESTIONS, embedder, model, SOURCES)
            probe = context_probe.probe('replay')
        self.assertEqual(result, load('evaluation.json'))
        self.assertEqual(probe, load('context-probe.json'))

    def test_every_source_resolves_to_its_pixels(self):
        for source in SOURCES:
            self.assertTrue(source_module.resolve(source))


class Citations(unittest.TestCase):
    def test_unknown_label_is_flagged(self):
        labels = labels_for('images', 'runbook-c04')
        status, _, flags = rag.check(reply({'answer': 'x', 'not_in_sources': False,
                                            'claims': [claim('S9', 'returns 0.32.14')]}), labels, NUM_CTX)
        self.assertEqual((status, flags), ('flagged', ['claim_1_cites_unknown_source']))

    def test_quote_not_in_source_is_flagged(self):
        labels = labels_for('images', 'runbook-c04')
        good = reply({'answer': 'x', 'not_in_sources': False, 'claims': [claim('S1', 'returns 0.32.14')]})
        bad = reply({'answer': 'x', 'not_in_sources': False, 'claims': [claim('[S1]', 'returns 0.33.0')]})
        self.assertEqual(rag.check(good, labels, NUM_CTX)[0], 'verified')
        self.assertEqual(rag.check(bad, labels, NUM_CTX)[2], ['claim_1_quote_not_in_source'])

    def test_quote_is_checked_against_what_the_model_was_shown(self):
        quote = 'The bar for medium has a height of 380 ms.'
        self.assertIn(quote, BY_ID['latency-p95']['description'])
        parsed = {'answer': 'x', 'not_in_sources': False, 'claims': [claim('S1', quote)]}
        self.assertEqual(rag.check(reply(parsed), labels_for('text', 'latency-p95'), NUM_CTX)[0], 'verified')
        self.assertEqual(rag.check(reply(parsed), labels_for('images', 'latency-p95'), NUM_CTX)[2],
                         ['claim_1_quote_not_in_source'])

    def test_changed_page_or_image_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            for folder in ('pages', 'images'):
                shutil.copytree(ROOT / folder, Path(tmp) / folder)
            for name in ('pages/runbook-p2.png', 'images/latency-p95.png'):
                canvas = decode_png((Path(tmp) / name).read_bytes())
                canvas.fill(0, 0, 3, 3)
                (Path(tmp) / name).write_bytes(encode_png(canvas))
            labels = labels_for('images', 'runbook-c04', 'latency-p95')
            parsed = {'answer': 'x', 'not_in_sources': False,
                      'claims': [claim('S1', 'returns 0.32.14'), claim('S2', '1290')]}
            status, _, flags = rag.check(reply(parsed), labels, NUM_CTX, root=tmp)
        self.assertEqual(status, 'flagged')
        self.assertEqual(flags, ['claim_1_source_pixels_changed', 'claim_2_source_pixels_changed'])

    def test_missing_or_contradictory_citations_are_flagged(self):
        labels = labels_for('images', 'runbook-c04')
        no_claims = reply({'answer': 'It returns 0.32.14.', 'not_in_sources': False, 'claims': []})
        both = reply({'answer': 'Not in the sources.', 'not_in_sources': True, 'claims': [claim('S1', 'returns 0.32.14')]})
        self.assertEqual(rag.check(no_claims, labels, NUM_CTX)[2], ['answer_without_citations'])
        self.assertEqual(rag.check(both, labels, NUM_CTX)[2], ['claims_without_an_answer'])


class Incomplete(unittest.TestCase):
    def test_reply_that_is_not_the_requested_json_is_incomplete(self):
        labels = labels_for('images', 'runbook-c04')
        for text in ('The version is 0.32.14.', json.dumps({'answer': 'x', 'claims': []}),
                     json.dumps({'answer': 'x', 'not_in_sources': 'no', 'claims': []}),
                     json.dumps({'answer': 'x', 'not_in_sources': False, 'claims': [{'text': 'x', 'source': 1}]})):
            self.assertEqual(rag.check(reply(text), labels, NUM_CTX), ('incomplete', None, ['not_the_requested_json']))

    def test_output_limit_or_full_context_is_incomplete(self):
        labels = labels_for('images', 'runbook-c04')
        parsed = {'answer': 'x', 'not_in_sources': True, 'claims': []}
        self.assertEqual(rag.check(reply(parsed, done='length'), labels, NUM_CTX)[2], ['output_cut_off'])
        self.assertEqual(rag.check(reply(parsed, prompt=NUM_CTX - 10, output=10), labels, NUM_CTX)[2],
                         ['context_window_full'])
        self.assertEqual(load('context-probe.json')['check_status'], 'incomplete')

    def test_ungradable_reply_is_neither_pass_nor_fail(self):
        result = {'status': 'incomplete', 'reply': None, 'retrieved': []}
        self.assertIsNone(evaluate.grade(QUESTIONS[0], result))


class Assembly(unittest.TestCase):
    def test_images_mode_sends_pixels_and_text_mode_sends_the_description(self):
        ranked = [(BY_ID['runbook-c04'], 1.0), (BY_ID['latency-p95'], 0.9)]
        user, images, _ = rag.assemble('q', ranked, 'images')
        self.assertEqual([i.sha256() for i in images], [BY_ID['latency-p95']['pixel_sha256']])
        self.assertNotIn(BY_ID['latency-p95']['description'], user)
        self.assertIn('[S2] figure latency-p95: image 1 attached.', user)
        user, images, _ = rag.assemble('q', ranked, 'text')
        self.assertEqual(images, [])
        self.assertIn(BY_ID['latency-p95']['description'], user)
        self.assertIn(BY_ID['runbook-c04']['text'], user)

    def test_bad_question_or_mode_is_refused(self):
        with mock.patch('embed_model.urlopen', no_network):
            embedder, _ = rag.models('replay')
            with self.assertRaises(ValueError):
                rag.retrieve(embedder, SOURCES, '   ')
        with self.assertRaises(ValueError):
            rag.assemble('q', [], 'pixels')


class Models(unittest.TestCase):
    def test_missing_recording_fails_without_network(self):
        with mock.patch('answer_model.urlopen', no_network), mock.patch('embed_model.urlopen', no_network):
            embedder, model = rag.models('replay')
            with self.assertRaisesRegex(answer_model.ModelError, 'No recorded answer'):
                model.chat(rag.SYSTEM, 'a question nobody recorded', [Canvas(4, 4)], rag.SCHEMA)
            with self.assertRaisesRegex(embed_model.EmbedError, 'No recorded vector'):
                embedder.query('a question nobody recorded')

    def test_different_model_build_is_refused(self):
        tags = {'models': [{'name': MANIFEST['vision']['ollama_tag'], 'digest': '0' * 64}]}
        with tempfile.TemporaryDirectory() as tmp, mock.patch('answer_model._post', lambda *a, **k: tags):
            with self.assertRaisesRegex(answer_model.ModelError, 'digest differs'):
                answer_model.AnswerModel(MANIFEST['vision'], MANIFEST['generation_options'], Path(tmp) / 'a.json', 'record')

    def test_model_without_vision_is_refused(self):
        def fake(path, payload=None, timeout=600):
            if path == '/api/tags':
                return {'models': [{'name': MANIFEST['vision']['ollama_tag'], 'digest': MANIFEST['vision']['ollama_digest']}]}
            return {'capabilities': ['completion']}
        with tempfile.TemporaryDirectory() as tmp, mock.patch('answer_model._post', fake):
            with self.assertRaisesRegex(answer_model.ModelError, 'vision'):
                answer_model.AnswerModel(MANIFEST['vision'], MANIFEST['generation_options'], Path(tmp) / 'a.json', 'record')


class Grading(unittest.TestCase):
    def test_expected_strings_match_whole_words_only(self):
        self.assertTrue(evaluate.contains('There were 0 read errors.', '0'))
        self.assertFalse(evaluate.contains('Both graders marked 10 cases.', '0'))
        self.assertFalse(evaluate.contains('Version 0.32.14 is required.', '0'))
        self.assertFalse(evaluate.contains('Version four has the highest pass rate.', '4'))

    def test_unanswerable_question_passes_only_without_claims(self):
        question = next(q for q in QUESTIONS if not q['expected'])
        quiet = {'status': 'verified', 'retrieved': [], 'reply': {'answer': 'Not in the sources.', 'not_in_sources': True, 'claims': []}}
        chatty = {'status': 'flagged', 'retrieved': [{'label': 'S1', 'id': 'runbook-c01'}],
                  'reply': {'answer': 'An A100.', 'not_in_sources': False, 'claims': [claim('S1', 'one model')]}}
        hedged = {'status': 'flagged', 'retrieved': [{'label': 'S1', 'id': 'runbook-c01'}],
                  'reply': {'answer': 'Not stated.', 'not_in_sources': True, 'claims': [claim('S1', 'one model')]}}
        self.assertIs(evaluate.grade(question, quiet), True)
        self.assertIs(evaluate.grade(question, chatty), False)
        self.assertIs(evaluate.grade(question, hedged), False)


if __name__ == '__main__':
    unittest.main()
