"""Offline consistency checks for the actual saved one-request crash/resume run."""
from pathlib import Path
import hashlib
import json
import struct

HERE = Path(__file__).resolve().parent
RUN = HERE / "runs/20261023T132807Z-native-crash-resume"
M = json.loads((RUN / "manifest.json").read_text())
P = json.loads((RUN / "provider-projection.json").read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_original_runtime_media_and_artifacts_are_bound():
    for name, expected in M["source_sha256"].items():
        if name != "README.md":
            assert digest(HERE / name) == expected, name
    for name, expected in M["files_sha256"].items():
        assert digest(RUN / name) == expected, name
    assert len(M["images"]) == 9
    for image in M["images"]:
        raw = (RUN / image["path"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == image["sha256"]
        assert raw[:8] == b"\x89PNG\r\n\x1a\n"
        assert struct.unpack(">II", raw[16:24]) in ((2880, 2200), (780, 2200), (640, 2200))


def test_saved_checkpoint_notes_match_the_provider_and_written_artifacts():
    before = json.loads((RUN / "after-start.state.json").read_text())
    after = json.loads((RUN / "after-resume.state.json").read_text())
    assert before["next"] == ["write_file"]
    assert after["next"] == []
    assert before["values"]["notes"] == after["values"]["notes"]
    response = P["response"]["candidates"][0]
    answer = "".join(x.get("text", "") for x in response["content"]["parts"] if not x.get("thought"))
    assert before["values"]["notes"] == answer
    assert (RUN / "release-2.5.0.md").read_text() == "# Release 2.5.0\n\n" + answer + "\n"
    assert (RUN / "announcements.log").read_text() == "Released 2.5.0: out/2.5.0.md\n"
    assert M["observed_unsupported_phrase"] in answer
    assert "not comprehensive factual" in M["scope_limit"]


def test_actual_request_uses_only_selected_fixture_prs_and_one_attempt():
    prs = json.loads((HERE / "prs.json").read_text())
    actual = P["request"]["contents"][0]["parts"][0]["text"]
    expected = "Write release notes for version 2.5.0: one Markdown bullet per merged pull request, user-facing wording, keep the #number.\n" + "\n".join(
        f"#{p['number']} {p['title']}" for p in prs if "dependencies" not in p["labels"])
    assert actual == expected
    assert P["request"]["generationConfig"] == {"candidateCount": 1, "maxOutputTokens": 1024}
    assert "tools" not in P["request"]
    assert M["provider_HTTP_attempts"] == 1
    assert M["resume_HTTP_dispatches"] == 0
    assert M["HTTP_status"] == 200 and M["finish_reason"] == "STOP"
    assert M["start_exit"] == 1 and M["resume_exit"] == 0
    assert M["reported_usage"] == P["response"].get("usageMetadata")
    assert M["invoice_verified"] is False


def test_projection_and_completed_transcript_media_scope_are_explicit():
    assert "only opaque thoughtSignature" in P["projection"]["mode"]
    def walk(v):
        if isinstance(v, dict):
            assert "thoughtSignature" not in v and "thought_signature" not in v
            for x in v.values(): walk(x)
        elif isinstance(v, list):
            for x in v: walk(x)
    walk(P["request"]); walk(P["response"])
    assert "ONE original PTY transcript" in M["capture_policy"]
    assert "not temporal stages" in M["capture_policy"]
    text = (RUN / "terminal-output.txt").read_bytes()
    assert b"CHECKPOINT CAPTURE FINISHED" in text
    assert b"FAKEPROBE" not in text and b"thoughtSignature" not in text
