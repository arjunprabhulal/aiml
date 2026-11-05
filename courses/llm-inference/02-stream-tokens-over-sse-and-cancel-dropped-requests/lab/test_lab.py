"""Unit and failure-boundary tests for SSE token streaming and disconnect cancellation."""

from __future__ import annotations

import json
import unittest

from lab import DecodeSlotPool, format_sse_frame, stream_generation_sse


class SseStreamingCancellationTests(unittest.TestCase):
    def test_cancellation_aborts_decode_and_frees_kv_blocks(self) -> None:
        pool = DecodeSlotPool(total_kv_blocks=512, block_size_tokens=16)
        cancelled = stream_generation_sse(
            pool=pool,
            request_id="req-cancel",
            prompt_tokens=2048,
            target_tokens=256,
            step_ms=16.0,
            disconnect_at_step=32,
            cancel_on_disconnect=True,
        )
        naive = stream_generation_sse(
            pool=pool,
            request_id="req-naive",
            prompt_tokens=2048,
            target_tokens=256,
            step_ms=16.0,
            disconnect_at_step=32,
            cancel_on_disconnect=False,
        )
        self.assertEqual(cancelled.executed_decode_steps, 31)
        self.assertEqual(cancelled.wasted_decode_steps, 0)
        self.assertFalse(cancelled.sent_done_marker)
        self.assertTrue(cancelled.kv_blocks_freed)
        self.assertEqual(pool.in_use_blocks, 0)
        self.assertEqual(naive.executed_decode_steps, 256)
        self.assertEqual(naive.wasted_decode_steps, 225)
        self.assertLess(
            cancelled.kv_block_seconds_consumed, naive.kv_block_seconds_consumed * 0.15
        )

    def test_unhandled_disconnect_leaks_kv_blocks(self) -> None:
        pool = DecodeSlotPool(total_kv_blocks=256, block_size_tokens=16)
        leaked = stream_generation_sse(
            pool=pool,
            request_id="req-leaked",
            prompt_tokens=2048,
            target_tokens=64,
            step_ms=16.0,
            disconnect_at_step=16,
            cancel_on_disconnect=True,
            release_on_exit=False,
        )
        self.assertFalse(leaked.kv_blocks_freed)
        self.assertEqual(pool.in_use_blocks, 129)
        with self.assertRaisesRegex(MemoryError, "Insufficient KV blocks"):
            pool.allocate("req-blocked-by-leak", 160)

    def test_multiline_token_payload_framing(self) -> None:
        frame = format_sse_frame(
            event_index=0,
            payload={"id": "req-1", "step": 1, "token": "def f():\n\n    return 42"},
        )
        self.assertTrue(frame.raw_frame.startswith("data: "))
        self.assertTrue(frame.raw_frame.endswith("\n\n"))
        # Only one SSE event boundary (\n\n at the end) may exist in the serialized JSON frame.
        segments = frame.raw_frame.split("\n\n")
        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[1], "")
        decoded = json.loads(segments[0].removeprefix("data: "))
        self.assertEqual(decoded["token"], "def f():\n\n    return 42")


if __name__ == "__main__":
    unittest.main()
