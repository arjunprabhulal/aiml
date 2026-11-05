"""Try one guardrail scenario against a temporary docs copy (fresh model requests)."""
import argparse
import asyncio
import shutil
import tempfile
from pathlib import Path

import guardrails


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question")
    parser.add_argument("--role", choices=guardrails.POLICY, default="reader")
    parser.add_argument("--confirmation", choices=["pause", "deny", "approve"], default="pause",
                        help="local test decision for any delete confirmation; default leaves it paused")
    return parser.parse_args()


async def main(args):
    original_docs = guardrails.DOCS
    with tempfile.TemporaryDirectory(prefix="adk-guardrails-") as temporary:
        guardrails.DOCS = Path(temporary) / "docs"
        shutil.copytree(original_docs, guardrails.DOCS)
        try:
            before = set(p.name for p in guardrails.DOCS.glob("*.md"))
            approve = None if args.confirmation == "pause" else lambda call: args.confirmation == "approve"
            events = await guardrails.ask(guardrails.build_app(), args.question, args.role, approve=approve)
            print("\n".join(guardrails.show(events)))
            after = set(p.name for p in guardrails.DOCS.glob("*.md"))
            print("temporary corpus added:", sorted(after - before), "removed:", sorted(before - after))
        finally:
            guardrails.DOCS = original_docs


if __name__ == "__main__":
    asyncio.run(main(parse_args()))
