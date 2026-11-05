"""Unit and failure-boundary tests for contiguous vs PagedAttention KV allocators."""

from __future__ import annotations

import unittest

from lab import ContiguousKvAllocator, PagedKvAllocator, compare_contiguous_vs_paged


class PagedKvCachingTest(unittest.TestCase):
    def test_paged_allocator_eliminates_reserved_slack_and_admits_4x_more_requests(
        self,
    ) -> None:
        report = compare_contiguous_vs_paged()
        self.assertEqual(report["contiguous"]["admitted_requests"], 8)
        self.assertEqual(report["paged"]["admitted_requests"], 32)
        self.assertGreater(report["contiguous"]["waste_ratio"], 0.80)
        self.assertLess(report["paged"]["waste_ratio"], 0.10)

    def test_contiguous_allocator_ooms_on_reserved_slack(self) -> None:
        """Contiguous allocation rejects a 9th 64-token request even though 87.5% of the pool is unused."""
        allocator = ContiguousKvAllocator(total_token_capacity=4096, max_seq_len=512)
        for i in range(8):
            allocator.allocate_sequence(f"req-{i}", initial_tokens=64)
        metrics = allocator.metrics()
        self.assertEqual(metrics["used_tokens"], 512)
        self.assertEqual(metrics["wasted_tokens"], 3584)
        with self.assertRaises(MemoryError):
            allocator.allocate_sequence("req-8", initial_tokens=64)

    def test_mutating_shared_block_without_cow_corrupts_sibling(self) -> None:
        """Appending to a shared tail block with enforce_cow=False overwrites/pollutes the sibling sequence."""
        safe = PagedKvAllocator(total_token_capacity=256, block_size=16)
        safe.allocate_sequence(
            "parent", list(range(20))
        )  # 1 full block + 4 tokens in tail block
        safe.fork_sequence("parent", "child")
        safe.append_token("child", 999, enforce_cow=True)
        self.assertEqual(safe.read_sequence_tokens("parent"), list(range(20)))
        self.assertEqual(safe.read_sequence_tokens("child"), list(range(20)) + [999])

        unsafe = PagedKvAllocator(total_token_capacity=256, block_size=16)
        unsafe.allocate_sequence("parent", list(range(20)))
        unsafe.fork_sequence("parent", "child")
        unsafe.append_token("child", 999, enforce_cow=False)
        # Without copy-on-write, parent's tail block now unexpectedly contains child's token 999!
        self.assertIn(999, unsafe.read_sequence_tokens("parent"))

    def test_freeing_forked_sequence_preserves_shared_prefix_until_last_reference(
        self,
    ) -> None:
        allocator = PagedKvAllocator(total_token_capacity=128, block_size=16)
        allocator.allocate_sequence("seq-a", list(range(32)))
        allocator.fork_sequence("seq-a", "seq-b")
        self.assertEqual(allocator.metrics()["allocated_blocks"], 2)
        allocator.free_sequence("seq-a")
        # Both blocks remain allocated because seq-b still holds ref_count=1
        self.assertEqual(allocator.metrics()["allocated_blocks"], 2)
        self.assertEqual(allocator.read_sequence_tokens("seq-b"), list(range(32)))
        allocator.free_sequence("seq-b")
        self.assertEqual(allocator.metrics()["allocated_blocks"], 0)


if __name__ == "__main__":
    unittest.main()


class GuardBoundaryTests(unittest.TestCase):
    def test_rejects_invalid_boundary_inputs_with_specific_reason(self):
        import lab
        cases = [('ContiguousKvAllocator(0,1)', 'Capacity and'), ('a=ContiguousKvAllocator(4,4)\na.allocate_sequence("x",1)\na.allocate_sequence("x",1)', 'Duplicate sequence'), ('ContiguousKvAllocator(4,4).allocate_sequence("x",0)', 'initial_tokens'), ('a=ContiguousKvAllocator(4,4)\na.allocate_sequence("x",4)\na.append_tokens("x")', 'exceeded max'), ('PagedKvAllocator(0,1)', 'total_token_capacity and'), ('PagedKvAllocator(5,2)', 'multiple of'), ('a=PagedKvAllocator(2,2)\na._acquire_block()\na._acquire_block()', 'out of physical'), ('PagedKvAllocator(2,2)._release_block(0)', 'already has ref_count'), ('a=PagedKvAllocator(4,2)\na.allocate_sequence("x",[1])\na.allocate_sequence("x",[1])', 'Duplicate sequence'), ('PagedKvAllocator(4,2).allocate_sequence("x",[])', 'non-empty'), ('PagedKvAllocator(2,2).allocate_sequence("x",[1,2,3])', 'Need 2 blocks'), ('PagedKvAllocator(2,2).fork_sequence("missing","x")', 'Unknown parent'), ('a=PagedKvAllocator(4,2)\na.allocate_sequence("x",[1])\na.fork_sequence("x","x")', 'Duplicate child')]
        for code, reason in cases:
            with self.subTest(code=code):
                with self.assertRaisesRegex((ValueError, MemoryError, KeyError, RuntimeError), reason):
                    exec(code, vars(lab).copy())
