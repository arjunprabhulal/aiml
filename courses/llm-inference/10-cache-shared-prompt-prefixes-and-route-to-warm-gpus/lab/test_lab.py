from __future__ import annotations

import unittest

from lab import (
    CacheAwareRouter,
    RadixKvTree,
    simulate_routing_comparison,
)


class TestPrefixCacheAndRouterLab(unittest.TestCase):
    def test_evicting_pinned_prefix_node_raises_or_skips(self) -> None:
        tree = RadixKvTree(max_cached_tokens=8)
        tree.insert((1, 2, 3, 4, 5, 6), pin=True)
        with self.assertRaises(RuntimeError):
            tree.insert((10, 11, 12, 13))

    def test_blind_prefix_affinity_overloads_single_replica(self) -> None:
        report = simulate_routing_comparison()
        pure = report["policies"]["pure_affinity"]
        aware = report["policies"]["cache_aware"]
        self.assertGreater(pure["max_ttft_ms"], aware["max_ttft_ms"] * 2.0)
        self.assertGreaterEqual(pure["max_replica_requests"], 24)

    def test_radix_tree_splits_shared_edge_on_divergent_branch(self) -> None:
        tree = RadixKvTree(max_cached_tokens=32)
        tree.insert((1, 2, 3, 4, 5, 6))
        second = tree.insert((1, 2, 3, 4, 9, 10))
        self.assertEqual(second["matched_tokens"], 4)
        self.assertEqual(second["new_tokens"], 2)
        self.assertEqual(tree.cached_tokens, 8)

    def test_lru_evicts_oldest_unpinned_leaf_first(self) -> None:
        tree = RadixKvTree(max_cached_tokens=10)
        tree.insert((1, 2, 3, 4))
        tree.insert((5, 6, 7, 8))
        # Touch (1, 2, 3, 4) so (5, 6, 7, 8) becomes the oldest leaf
        matched, _ = tree.match_prefix((1, 2, 3, 4))
        self.assertEqual(matched, 4)
        tree.insert((9, 10, 11, 12))
        self.assertEqual(tree.match_prefix((1, 2, 3, 4))[0], 4)
        self.assertEqual(tree.match_prefix((5, 6, 7, 8))[0], 0)

    def test_cache_aware_router_beats_round_robin_and_pure_affinity(self) -> None:
        report = simulate_routing_comparison()
        rr = report["policies"]["round_robin"]
        pure = report["policies"]["pure_affinity"]
        aware = report["policies"]["cache_aware"]
        self.assertLess(aware["mean_ttft_ms"], rr["mean_ttft_ms"])
        self.assertLess(aware["mean_ttft_ms"], pure["mean_ttft_ms"])


class PrefixInsertionRegressions(unittest.TestCase):
    def test_extending_prefix_does_not_evict_its_ancestor(self):
        tree = RadixKvTree(10)
        tree.insert((1, 2, 3, 4, 5, 6))
        tree.insert((20, 21, 22, 23))
        tree.insert((1, 2, 3, 4, 5, 6, 7, 8))
        self.assertEqual(tree.match_prefix((1, 2, 3, 4, 5, 6, 7, 8))[0], 8)
        self.assertLessEqual(tree.cached_tokens, 10)

    def test_partial_edge_is_a_prefix_match(self):
        tree = RadixKvTree(10)
        tree.insert((1, 2, 3, 4))
        self.assertEqual(tree.match_prefix((1, 2, 3))[0], 3)

    def test_failed_insert_leaves_existing_branches_intact(self):
        tree = RadixKvTree(10)
        tree.insert((1, 2, 3, 4, 5, 6), pin=True)
        tree.insert((20, 21, 22, 23), pin=True)
        with self.assertRaises(RuntimeError):
            tree.insert((1, 2, 3, 4, 9, 10, 11, 12))
        self.assertEqual(tree.match_prefix((1, 2, 3, 4, 5, 6))[0], 6)
        self.assertEqual(tree.match_prefix((20, 21, 22, 23))[0], 4)
        self.assertEqual(tree.cached_tokens, 10)

    def test_oversized_shared_sequence_is_rejected_before_mutation(self):
        tree = RadixKvTree(6)
        tree.insert((1, 2, 3, 4))
        with self.assertRaises(ValueError):
            tree.insert((1, 2, 3, 4, 5, 6, 7))
        self.assertEqual(tree.match_prefix((1, 2, 3, 4))[0], 4)


class PinLifetimeTests(unittest.TestCase):
    def test_released_pin_can_be_evicted(self):
        tree = RadixKvTree(6)
        tree.insert((1, 2, 3, 4), pin=True)
        tree.release_pin((1, 2, 3, 4))
        tree.insert((5, 6, 7, 8))
        self.assertEqual(tree.match_prefix((1, 2, 3, 4))[0], 0)

    def test_unowned_pin_cannot_be_released(self):
        tree = RadixKvTree(6)
        tree.insert((1, 2, 3))
        with self.assertRaises(ValueError):
            tree.release_pin((1, 2, 3))


if __name__ == "__main__":
    unittest.main()


class GuardBoundaryTests(unittest.TestCase):
    def test_rejects_invalid_boundary_inputs_with_specific_reason(self):
        import lab
        cases = [('RadixKvTree(0)', 'max_cached_tokens'), ('a=RadixKvTree(4)\na.insert((1,),pin=True)\na.root.children.clear()\na.release_pin((1,))', 'Pinned sequence'), ('CacheAwareRouter().route_request((1,),"bad")', 'Unknown routing')]
        for code, reason in cases:
            with self.subTest(code=code):
                with self.assertRaisesRegex((ValueError, MemoryError, KeyError, RuntimeError), reason):
                    exec(code, vars(lab).copy())
