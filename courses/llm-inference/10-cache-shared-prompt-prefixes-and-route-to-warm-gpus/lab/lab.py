from __future__ import annotations

from dataclasses import dataclass, field
import copy
import json
from typing import Literal


@dataclass
class RadixNode:
    tokens: tuple[int, ...] = ()
    parent: RadixNode | None = None
    children: dict[int, RadixNode] = field(default_factory=dict)
    last_access_step: int = 0
    pin_count: int = 0

    @property
    def is_leaf(self) -> bool:
        return len(self.children) == 0


class RadixKvTree:
    """Compressed radix tree for shared KV-cache prefix blocks with LRU leaf eviction."""

    def __init__(self, max_cached_tokens: int = 16384) -> None:
        if max_cached_tokens <= 0:
            raise ValueError("max_cached_tokens must be positive")
        self.max_cached_tokens = max_cached_tokens
        self.root = RadixNode()
        self.step_clock = 0
        self.cached_tokens = 0
        self.total_evicted_tokens = 0
        self.pinned_sequences = {}

    def _touch(self, node: RadixNode) -> None:
        self.step_clock += 1
        curr: RadixNode | None = node
        while curr is not None and curr is not self.root:
            curr.last_access_step = self.step_clock
            curr = curr.parent

    def match_prefix(self, tokens: tuple[int, ...]) -> tuple[int, RadixNode]:
        """Return (matched_token_count, deepest_matched_node) without mutating tree structure."""
        curr = self.root
        matched = 0
        idx = 0
        n = len(tokens)

        while idx < n:
            first_tok = tokens[idx]
            child = curr.children.get(first_tok)
            if child is None:
                break
            edge = child.tokens
            common = 0
            max_common = min(len(edge), n - idx)
            while common < max_common and edge[common] == tokens[idx + common]:
                common += 1
            if common < len(edge):
                matched += common
                curr = child
                break
            matched += common
            idx += common
            curr = child

        if curr is not self.root:
            self._touch(curr)
        return matched, curr

    def _collect_evictable_leaves(self) -> list[RadixNode]:
        leaves: list[RadixNode] = []
        stack = list(self.root.children.values())
        while stack:
            node = stack.pop()
            if node.is_leaf:
                if node.pin_count == 0:
                    leaves.append(node)
            else:
                stack.extend(node.children.values())
        leaves.sort(key=lambda nd: nd.last_access_step)
        return leaves

    def evict_lru(self, needed_tokens: int) -> int:
        """Evict unpinned leaf nodes in LRU order until needed_tokens are freed."""
        freed = 0
        while freed < needed_tokens:
            leaves = self._collect_evictable_leaves()
            if not leaves:
                raise RuntimeError(
                    f"Cannot evict {needed_tokens} tokens: all remaining cached nodes are pinned"
                )
            victim = leaves[0]
            parent = victim.parent
            assert parent is not None
            del parent.children[victim.tokens[0]]
            victim_len = len(victim.tokens)
            self.cached_tokens -= victim_len
            self.total_evicted_tokens += victim_len
            freed += victim_len
        return freed

    def insert(self, tokens: tuple[int, ...], pin: bool = False) -> dict[str, int]:
        if len(tokens) > self.max_cached_tokens:
            raise ValueError("Request length exceeds replica KV cache capacity")
        snapshot = (
            copy.deepcopy(self.root),
            self.cached_tokens,
            self.total_evicted_tokens,
            self.step_clock,
        )
        try:
            result = self._insert(tokens, pin)
            if pin:
                self.pinned_sequences[tokens] = self.pinned_sequences.get(tokens, 0) + 1
            return result
        except Exception:
            (
                self.root,
                self.cached_tokens,
                self.total_evicted_tokens,
                self.step_clock,
            ) = snapshot
            raise

    def release_pin(self, tokens: tuple[int, ...]) -> None:
        if self.pinned_sequences.get(tokens, 0) < 1:
            raise ValueError("No active pin for this sequence")
        matched, node = self.match_prefix(tokens)
        if matched != len(tokens):
            raise RuntimeError("Pinned sequence is missing")
        while node is not self.root:
            node.pin_count -= 1
            node = node.parent
        self.pinned_sequences[tokens] -= 1
        if self.pinned_sequences[tokens] == 0:
            del self.pinned_sequences[tokens]

    def _insert(self, tokens: tuple[int, ...], pin: bool = False) -> dict[str, int]:
        """Insert a token sequence into the radix tree, splitting edges on partial match."""
        curr = self.root
        idx = 0
        n = len(tokens)
        matched_tokens = 0

        while idx < n:
            first_tok = tokens[idx]
            child = curr.children.get(first_tok)
            if child is None:
                break
            edge = child.tokens
            common = 0
            max_common = min(len(edge), n - idx)
            while common < max_common and edge[common] == tokens[idx + common]:
                common += 1
            matched_tokens += common
            idx += common

            if common == len(edge):
                curr = child
            else:
                # Split child edge into shared prefix node and existing suffix child
                split_node = RadixNode(
                    tokens=edge[:common],
                    parent=curr,
                    last_access_step=child.last_access_step,
                    pin_count=child.pin_count,
                )
                curr.children[first_tok] = split_node
                child.tokens = edge[common:]
                child.parent = split_node
                split_node.children[child.tokens[0]] = child
                curr = split_node
                break

        new_tokens = n - idx
        if new_tokens > 0:
            overflow = (self.cached_tokens + new_tokens) - self.max_cached_tokens
            if overflow > 0:
                # The matched path is a dependency of this insertion, even when otherwise unpinned.
                protected = []
                node = curr
                while node is not self.root:
                    node.pin_count += 1
                    protected.append(node)
                    node = node.parent
                try:
                    self.evict_lru(overflow)
                finally:
                    for node in protected:
                        node.pin_count -= 1
            new_leaf = RadixNode(
                tokens=tokens[idx:],
                parent=curr,
                last_access_step=self.step_clock + 1,
            )
            curr.children[new_leaf.tokens[0]] = new_leaf
            self.cached_tokens += new_tokens
            curr = new_leaf

        if pin:
            node_ptr: RadixNode | None = curr
            while node_ptr is not None and node_ptr is not self.root:
                node_ptr.pin_count += 1
                node_ptr = node_ptr.parent

        self._touch(curr)
        return {
            "matched_tokens": matched_tokens,
            "new_tokens": new_tokens,
            "cached_tokens": self.cached_tokens,
        }


@dataclass
class GpuReplica:
    replica_id: int
    tree: RadixKvTree
    queue_wait_ms: float = 0.0
    routed_requests: int = 0
    matched_tokens_total: int = 0
    computed_tokens_total: int = 0


class CacheAwareRouter:
    """Routes incoming prompts across GPU replicas using round-robin, pure affinity, or cache-aware scoring."""

    def __init__(
        self,
        num_replicas: int = 4,
        max_cached_tokens_per_replica: int = 16384,
        prefill_ms_per_token: float = 0.025,
        cached_lookup_ms_per_token: float = 0.0015,
        queue_decay_ms_per_arrival: float = 12.0,
    ) -> None:
        self.replicas = [
            GpuReplica(
                replica_id=i,
                tree=RadixKvTree(max_cached_tokens=max_cached_tokens_per_replica),
            )
            for i in range(num_replicas)
        ]
        self.prefill_ms_per_token = prefill_ms_per_token
        self.cached_lookup_ms_per_token = cached_lookup_ms_per_token
        self.queue_decay_ms_per_arrival = queue_decay_ms_per_arrival
        self._rr_cursor = 0

    def _estimate_prefill_ms(self, total_tokens: int, matched_tokens: int) -> float:
        unmatched = total_tokens - matched_tokens
        return round(
            matched_tokens * self.cached_lookup_ms_per_token
            + unmatched * self.prefill_ms_per_token,
            4,
        )

    def route_request(
        self,
        tokens: tuple[int, ...],
        policy: Literal["round_robin", "pure_affinity", "cache_aware"],
    ) -> dict[str, object]:
        for rep in self.replicas:
            rep.queue_wait_ms = max(
                0.0, round(rep.queue_wait_ms - self.queue_decay_ms_per_arrival, 4)
            )

        if policy == "round_robin":
            chosen = self.replicas[self._rr_cursor % len(self.replicas)]
            self._rr_cursor += 1
        elif policy == "pure_affinity":
            # Pick replica with longest prefix match; ties go to lowest replica_id (ignoring queue load)
            best_rep = self.replicas[0]
            best_match = -1
            for rep in self.replicas:
                matched, _ = rep.tree.match_prefix(tokens)
                if matched > best_match:
                    best_match = matched
                    best_rep = rep
            if best_match == 0:
                # Hash by first token so same prefix always lands on the same replica
                chosen = self.replicas[tokens[0] % len(self.replicas)]
            else:
                chosen = best_rep
        elif policy == "cache_aware":
            # Choose replica that minimizes estimated TTFT = queue_wait_ms + remaining_prefill_ms
            chosen = min(
                self.replicas,
                key=lambda rep: (
                    round(
                        rep.queue_wait_ms
                        + self._estimate_prefill_ms(
                            len(tokens), rep.tree.match_prefix(tokens)[0]
                        ),
                        4,
                    ),
                    rep.replica_id,
                ),
            )
        else:
            raise ValueError(f"Unknown routing policy: {policy}")

        matched, _ = chosen.tree.match_prefix(tokens)
        exec_ms = self._estimate_prefill_ms(len(tokens), matched)
        ttft_ms = round(chosen.queue_wait_ms + exec_ms, 2)

        chosen.tree.insert(tokens)
        chosen.queue_wait_ms = round(chosen.queue_wait_ms + exec_ms, 4)
        chosen.routed_requests += 1
        chosen.matched_tokens_total += matched
        chosen.computed_tokens_total += len(tokens) - matched

        return {
            "replica_id": chosen.replica_id,
            "matched_tokens": matched,
            "computed_tokens": len(tokens) - matched,
            "exec_ms": round(exec_ms, 2),
            "ttft_ms": ttft_ms,
        }


def build_burst_workload() -> list[tuple[int, ...]]:
    """Four 4,096-token tenant system prompts plus a 16-request traffic spike on tenant 0."""
    tenant_prefixes = [
        tuple(range(10_000 * (t + 1), 10_000 * (t + 1) + 4096)) for t in range(4)
    ]
    requests: list[tuple[int, ...]] = []
    # Phase 1: interleaved multi-tenant traffic across all 4 tenants (16 requests)
    for step in range(16):
        t_idx = (step * 3 + 1) % 4
        user_suffix = tuple(range(100_000 + step * 256, 100_000 + (step + 1) * 256))
        requests.append(tenant_prefixes[t_idx] + user_suffix)
    # Phase 2: burst of 16 requests on tenant 0
    for burst in range(16):
        user_suffix = tuple(range(200_000 + burst * 256, 200_000 + (burst + 1) * 256))
        requests.append(tenant_prefixes[0] + user_suffix)
    return requests


def simulate_routing_comparison() -> dict[str, object]:
    workload = build_burst_workload()
    policies: list[Literal["round_robin", "pure_affinity", "cache_aware"]] = [
        "round_robin",
        "pure_affinity",
        "cache_aware",
    ]
    results: dict[str, dict[str, object]] = {}

    for policy in policies:
        router = CacheAwareRouter(
            num_replicas=4,
            max_cached_tokens_per_replica=9216,
            prefill_ms_per_token=0.025,
            cached_lookup_ms_per_token=0.0015,
            queue_decay_ms_per_arrival=14.0,
        )
        ttfts: list[float] = []
        for req_tokens in workload:
            out = router.route_request(req_tokens, policy=policy)
            ttfts.append(float(out["ttft_ms"]))

        total_matched = sum(r.matched_tokens_total for r in router.replicas)
        total_computed = sum(r.computed_tokens_total for r in router.replicas)
        total_tokens = total_matched + total_computed
        results[policy] = {
            "policy": policy,
            "total_requests": len(workload),
            "cache_hit_ratio": round(total_matched / total_tokens, 4),
            "mean_ttft_ms": round(sum(ttfts) / len(ttfts), 2),
            "max_ttft_ms": round(max(ttfts), 2),
            "max_replica_requests": max(r.routed_requests for r in router.replicas),
            "min_replica_requests": min(r.routed_requests for r in router.replicas),
            "total_evicted_tokens": sum(
                r.tree.total_evicted_tokens for r in router.replicas
            ),
            "replica_loads": [
                {
                    "replica_id": r.replica_id,
                    "routed_requests": r.routed_requests,
                    "cached_tokens": r.tree.cached_tokens,
                    "evicted_tokens": r.tree.total_evicted_tokens,
                }
                for r in router.replicas
            ],
        }

    # Also record a small radix tree trace showing shared prefix + branching + LRU eviction
    demo_tree = RadixKvTree(max_cached_tokens=16)
    sys_prompt = (10, 11, 12, 13)
    turn_a = sys_prompt + (20, 21, 22, 23)
    turn_b = sys_prompt + (20, 21, 30, 31)
    first_insert = demo_tree.insert(turn_a, pin=False)
    second_insert = demo_tree.insert(turn_b, pin=False)

    return {
        "workload_requests": len(workload),
        "hot_prefix_tokens": 4096,
        "user_turn_tokens": 256,
        "radix_split_demo": {
            "first_insert": first_insert,
            "second_insert": second_insert,
        },
        "policies": results,
    }


def main() -> None:
    report = simulate_routing_comparison()
    print(
        json.dumps(
            {
                "execution_mode": "CPU algorithm with controlled inputs; any latency/capacity coefficients are assumptions",
                **report,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
