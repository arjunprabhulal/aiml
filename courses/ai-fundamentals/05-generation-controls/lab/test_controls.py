"""Offline tests with a fake client and the recorded run. Run: python -m pytest -q"""
from pathlib import Path
from types import SimpleNamespace

from controls import TASK, complete, stream

RECORDED = Path(__file__).with_name("run-output.txt").read_text()


def chunk(text, done=False, reason=None):
    return SimpleNamespace(message=SimpleNamespace(content=text), done=done, done_reason=reason)


class FakeClient:
    def __init__(self):
        self.calls = []

    def chat(self, **request):
        self.calls.append(request)
        if request.get("stream"):
            return iter([chunk("Rolls "), chunk("back"), chunk("", True, "stop")])
        return SimpleNamespace(message=SimpleNamespace(content=" msg "), done_reason="length")


def test_options_go_to_the_runtime_unchanged():
    client = FakeClient()
    assert complete(client, TASK, temperature=1.0, seed=3, num_predict=40) == ("msg", "length")
    assert client.calls[0]["options"] == {"temperature": 1.0, "seed": 3, "num_predict": 40}


def test_stream_counts_text_chunks_and_keeps_the_final_done_reason():
    result = stream(FakeClient(), "q")
    assert result["chunks"] == 2 and result["done_reason"] == "stop"
    assert result["first_chunk_s"] <= result["total_s"]


def test_temperature_zero_repeated_the_same_message():
    runs = RECORDED.split("temperature 1.0, seeds 1-3:")[0].splitlines()[1:]
    assert len(runs) == 3 and len(set(runs)) == 1


def test_the_same_seed_reproduced_a_sampled_message():
    sampled = RECORDED.split("seeds 1-3:\n")[1].splitlines()
    assert sampled[0] == sampled[4]


def test_an_output_limit_reports_length_not_stop():
    assert "num_predict=40 -> done_reason='length'" in RECORDED
    assert "'done_reason': 'stop'" in RECORDED and "ReadTimeout" in RECORDED


def test_empty_completed_stream_has_no_first_chunk_time():
    client = FakeClient()
    client.chat = lambda **kwargs: iter([chunk("", True, "stop")])
    result = stream(client, "q")
    assert result["chunks"] == 0 and result["first_chunk_s"] is None
    assert result["done_reason"] == "stop"


def test_stream_without_final_status_is_not_success():
    import pytest
    client = FakeClient()
    client.chat = lambda **kwargs: iter([chunk("partial")])
    with pytest.raises(RuntimeError, match="final status"):
        stream(client, "q")
