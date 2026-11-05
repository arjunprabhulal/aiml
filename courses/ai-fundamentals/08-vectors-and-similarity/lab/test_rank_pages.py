"""Offline tests on the recorded vectors and rankings. Run: python -m pytest -q"""
import json

import numpy as np
import pytest

from rank_pages import HERE, PAGES, cosine, rank

PAGE_VECTORS = np.load(HERE / "page-vectors.npy")
RANKINGS = json.loads((HERE / "rankings.json").read_text())["rankings"]


def test_cosine_ignores_length_and_measures_direction():
    matrix = np.array([[1.0, 0.0], [0.0, 2.0], [-3.0, 0.0]])
    assert cosine(np.array([5.0, 0.0]), matrix).tolist() == [1.0, 0.0, -1.0]


def test_each_page_is_most_similar_to_itself():
    names = list(PAGES)
    for i, name in enumerate(names):
        assert rank(PAGE_VECTORS[i], PAGE_VECTORS, names)[0] == (name, 1.0)


def test_the_recorded_rankings_put_the_answering_page_first():
    top = {query: ranking[0][0] for query, ranking in RANKINGS.items()}
    assert top == {"how do I undo a bad deploy": "rollback.md",
                   "where should the CI credential live": "tokens.md",
                   "what replaced release revert": "rollback.md"}


def test_a_query_vector_of_another_size_cannot_be_compared():
    with pytest.raises(ValueError, match="mismatch"):
        rank(np.ones(512), PAGE_VECTORS, list(PAGES))


def test_an_unanswerable_query_still_scores_close_to_a_real_match():
    failures = (HERE / "failures-output.txt").read_text()
    unanswerable = float(failures.split("pin a Python dependency' -> top page config.md at ")[1].split()[0])
    weakest_real_top = min(ranking[0][1] for ranking in RANKINGS.values())
    assert unanswerable > 0 and weakest_real_top - unanswerable < 0.25


def test_fresh_vectors_leave_original_recordings_unchanged(tmp_path, monkeypatch):
    import rank_pages as app
    originals = {"rankings.json": b"original ranking", "page-vectors.npy": b"original vectors"}
    for name, data in originals.items():
        (tmp_path / name).write_bytes(data)
    monkeypatch.setattr(app, "HERE", tmp_path)
    monkeypatch.setattr(app, "PAGES", {"rollback.md": "current docuctl manual"})
    monkeypatch.setattr(app.ollama, "Client", lambda: object())
    monkeypatch.setattr(app, "embed", lambda _client, texts: np.ones((len(texts), 2)))
    app.main()
    assert all((tmp_path / name).read_bytes() == data for name, data in originals.items())
    assert np.load(tmp_path / "runs/local-docuctl/page-vectors.npy").shape == (1, 2)
    assert len(json.loads((tmp_path / "runs/local-docuctl/rankings.json").read_text())["rankings"]) == 3
