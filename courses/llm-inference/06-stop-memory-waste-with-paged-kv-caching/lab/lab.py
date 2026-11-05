"""Contiguous KV cache allocator vs PagedAttention block tables with copy-on-write."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import math


@dataclass
class ContiguousSlot:
    seq_id: str
    reserved_tokens: int
    used_tokens: int


class ContiguousKvAllocator:
    """Reserves a contiguous chunk of max_seq_len tokens per active request."""

    def __init__(self, total_token_capacity: int, max_seq_len: int) -> None:
        if total_token_capacity <= 0 or max_seq_len <= 0:
            raise ValueError("Capacity and max_seq_len must be positive integers")
        self.total_token_capacity = total_token_capacity
        self.max_seq_len = max_seq_len
        self.max_concurrent_sequences = total_token_capacity // max_seq_len
        self.active: dict[str, ContiguousSlot] = {}

    def allocate_sequence(self, seq_id: str, initial_tokens: int) -> None:
        if seq_id in self.active:
            raise ValueError(f"Duplicate sequence ID: {seq_id}")
        if initial_tokens <= 0 or initial_tokens > self.max_seq_len:
            raise ValueError(
                f"initial_tokens={initial_tokens} outside 1..{self.max_seq_len}"
            )
        if len(self.active) >= self.max_concurrent_sequences:
            raise MemoryError(
                f"Contiguous KV allocator out of slots: {len(self.active)}/{self.max_concurrent_sequences} in use"
            )
        self.active[seq_id] = ContiguousSlot(
            seq_id=seq_id,
            reserved_tokens=self.max_seq_len,
            used_tokens=initial_tokens,
        )

    def append_tokens(self, seq_id: str, count: int = 1) -> None:
        slot = self.active[seq_id]
        if slot.used_tokens + count > slot.reserved_tokens:
            raise MemoryError(
                f"Sequence {seq_id} exceeded max_seq_len={self.max_seq_len}"
            )
        slot.used_tokens += count

    def free_sequence(self, seq_id: str) -> None:
        self.active.pop(seq_id, None)

    def metrics(self) -> dict[str, object]:
        reserved = sum(s.reserved_tokens for s in self.active.values())
        used = sum(s.used_tokens for s in self.active.values())
        wasted = reserved - used
        waste_ratio = (wasted / reserved) if reserved else 0.0
        return {
            "active_sequences": len(self.active),
            "reserved_tokens": reserved,
            "used_tokens": used,
            "wasted_tokens": wasted,
            "waste_ratio": round(waste_ratio, 4),
            "utilization_of_total_pool": round(used / self.total_token_capacity, 4),
        }


@dataclass
class PhysicalKvBlock:
    block_id: int
    block_size: int
    ref_count: int = 0
    tokens: list[int] = field(default_factory=list)


@dataclass
class BlockTable:
    seq_id: str
    block_size: int
    logical_blocks: list[int] = field(default_factory=list)
    num_tokens: int = 0


class PagedKvAllocator:
    """Manages fixed-size physical KV blocks with reference counting and copy-on-write."""

    def __init__(self, total_token_capacity: int, block_size: int = 16) -> None:
        if total_token_capacity <= 0 or block_size <= 0:
            raise ValueError("total_token_capacity and block_size must be positive")
        if total_token_capacity % block_size != 0:
            raise ValueError("total_token_capacity must be a multiple of block_size")
        self.total_token_capacity = total_token_capacity
        self.block_size = block_size
        self.num_blocks = total_token_capacity // block_size
        self.blocks: dict[int, PhysicalKvBlock] = {
            i: PhysicalKvBlock(block_id=i, block_size=block_size)
            for i in range(self.num_blocks)
        }
        self.free_block_ids: list[int] = list(range(self.num_blocks))
        self.tables: dict[str, BlockTable] = {}
        self.cow_copies_performed: int = 0

    def _acquire_block(self) -> PhysicalKvBlock:
        if not self.free_block_ids:
            raise MemoryError("PagedKvAllocator out of physical KV blocks")
        block_id = self.free_block_ids.pop(0)
        block = self.blocks[block_id]
        block.ref_count = 1
        block.tokens = []
        return block

    def _release_block(self, block_id: int) -> None:
        block = self.blocks[block_id]
        if block.ref_count <= 0:
            raise RuntimeError(f"Block {block_id} already has ref_count=0")
        block.ref_count -= 1
        if block.ref_count == 0:
            block.tokens = []
            self.free_block_ids.append(block_id)

    def allocate_sequence(self, seq_id: str, token_ids: list[int]) -> BlockTable:
        if seq_id in self.tables:
            raise ValueError(f"Duplicate sequence ID: {seq_id}")
        if not token_ids:
            raise ValueError("token_ids must be non-empty")
        needed_blocks = math.ceil(len(token_ids) / self.block_size)
        if needed_blocks > len(self.free_block_ids):
            raise MemoryError(
                f"Need {needed_blocks} blocks for {seq_id}, only {len(self.free_block_ids)} free"
            )
        table = BlockTable(seq_id=seq_id, block_size=self.block_size)
        self.tables[seq_id] = table
        for token in token_ids:
            self.append_token(seq_id, token)
        return table

    def fork_sequence(self, parent_seq_id: str, child_seq_id: str) -> BlockTable:
        """Share physical blocks with ref_count += 1 for beam search / parallel sampling."""
        if parent_seq_id not in self.tables:
            raise KeyError(f"Unknown parent sequence: {parent_seq_id}")
        if child_seq_id in self.tables:
            raise ValueError(f"Duplicate child sequence: {child_seq_id}")
        parent = self.tables[parent_seq_id]
        for block_id in parent.logical_blocks:
            self.blocks[block_id].ref_count += 1
        child = BlockTable(
            seq_id=child_seq_id,
            block_size=self.block_size,
            logical_blocks=list(parent.logical_blocks),
            num_tokens=parent.num_tokens,
        )
        self.tables[child_seq_id] = child
        return child

    def append_token(
        self, seq_id: str, token_id: int, enforce_cow: bool = True
    ) -> None:
        table = self.tables[seq_id]
        if (
            not table.logical_blocks
            or len(self.blocks[table.logical_blocks[-1]].tokens) == self.block_size
        ):
            new_block = self._acquire_block()
            new_block.tokens.append(token_id)
            table.logical_blocks.append(new_block.block_id)
            table.num_tokens += 1
            return

        last_block_id = table.logical_blocks[-1]
        last_block = self.blocks[last_block_id]
        if last_block.ref_count > 1 and enforce_cow:
            # Copy-on-write: allocate a private physical block, copy existing tokens, decrement old ref_count
            private_block = self._acquire_block()
            private_block.tokens = list(last_block.tokens)
            private_block.tokens.append(token_id)
            last_block.ref_count -= 1
            table.logical_blocks[-1] = private_block.block_id
            table.num_tokens += 1
            self.cow_copies_performed += 1
        else:
            last_block.tokens.append(token_id)
            table.num_tokens += 1

    def read_sequence_tokens(self, seq_id: str) -> list[int]:
        table = self.tables[seq_id]
        out: list[int] = []
        for block_id in table.logical_blocks:
            out.extend(self.blocks[block_id].tokens)
        return out

    def free_sequence(self, seq_id: str) -> None:
        table = self.tables.pop(seq_id)
        for block_id in table.logical_blocks:
            self._release_block(block_id)

    def metrics(self) -> dict[str, object]:
        allocated_blocks = [b for b in self.blocks.values() if b.ref_count > 0]
        reserved_tokens = len(allocated_blocks) * self.block_size
        physical_stored_tokens = sum(len(b.tokens) for b in allocated_blocks)
        logical_tokens = sum(t.num_tokens for t in self.tables.values())
        internal_frag_tokens = reserved_tokens - physical_stored_tokens
        frag_ratio = (
            (internal_frag_tokens / reserved_tokens) if reserved_tokens else 0.0
        )
        return {
            "active_sequences": len(self.tables),
            "allocated_blocks": len(allocated_blocks),
            "free_blocks": len(self.free_block_ids),
            "reserved_tokens": reserved_tokens,
            "physical_stored_tokens": physical_stored_tokens,
            "logical_tokens_served": logical_tokens,
            "internal_fragmentation_tokens": internal_frag_tokens,
            "waste_ratio": round(frag_ratio, 4),
            "cow_copies_performed": self.cow_copies_performed,
        }


def compare_contiguous_vs_paged() -> dict[str, object]:
    total_capacity = 4096
    max_seq_len = 512
    block_size = 16
    request_lengths = [
        68,
        95,
        114,
        52,
        140,
        83,
        77,
        129,
        61,
        105,
        88,
        73,
        119,
        91,
        64,
        110,
        79,
        102,
        58,
        134,
        85,
        70,
        99,
        122,
        66,
        108,
        74,
        115,
        81,
        93,
        62,
        125,
    ]

    contiguous = ContiguousKvAllocator(
        total_token_capacity=total_capacity, max_seq_len=max_seq_len
    )
    contiguous_admitted = 0
    contiguous_rejected = 0
    for idx, length in enumerate(request_lengths):
        try:
            contiguous.allocate_sequence(f"req-{idx}", length)
            contiguous_admitted += 1
        except MemoryError:
            contiguous_rejected += 1

    paged = PagedKvAllocator(total_token_capacity=total_capacity, block_size=block_size)
    paged_admitted = 0
    paged_rejected = 0
    for idx, length in enumerate(request_lengths):
        try:
            paged.allocate_sequence(f"req-{idx}", list(range(length)))
            paged_admitted += 1
        except MemoryError:
            paged_rejected += 1

    # Demonstrate shared prefix + copy-on-write parallel sampling
    cow_allocator = PagedKvAllocator(total_token_capacity=512, block_size=16)
    shared_prompt = list(
        range(40)
    )  # 2 full blocks (32 tokens) + 1 partial block (8 tokens)
    cow_allocator.allocate_sequence("beam-0", shared_prompt)
    cow_allocator.fork_sequence("beam-0", "beam-1")
    cow_allocator.fork_sequence("beam-0", "beam-2")
    blocks_before_decode = len(
        [b for b in cow_allocator.blocks.values() if b.ref_count > 0]
    )
    cow_allocator.append_token("beam-1", 9001)
    cow_allocator.append_token("beam-2", 9002)
    cow_allocator.append_token("beam-0", 9000)

    return {
        "pool_config": {
            "total_token_capacity": total_capacity,
            "max_seq_len": max_seq_len,
            "block_size": block_size,
            "submitted_requests": len(request_lengths),
        },
        "contiguous": {
            "admitted_requests": contiguous_admitted,
            "rejected_requests": contiguous_rejected,
            **contiguous.metrics(),
        },
        "paged": {
            "admitted_requests": paged_admitted,
            "rejected_requests": paged_rejected,
            **paged.metrics(),
        },
        "concurrency_multiplier": round(paged_admitted / contiguous_admitted, 2),
        "copy_on_write_demo": {
            "prompt_tokens": len(shared_prompt),
            "shared_beams": 3,
            "blocks_before_decode_append": blocks_before_decode,
            **cow_allocator.metrics(),
            "beam_tails": {
                "beam_0_last_token": cow_allocator.read_sequence_tokens("beam-0")[-1],
                "beam_1_last_token": cow_allocator.read_sequence_tokens("beam-1")[-1],
                "beam_2_last_token": cow_allocator.read_sequence_tokens("beam-2")[-1],
            },
        },
    }


def main() -> None:
    print(
        json.dumps(
            {
                "execution_mode": "CPU algorithm with controlled inputs; any latency/capacity coefficients are assumptions",
                **compare_contiguous_vs_paged(),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
