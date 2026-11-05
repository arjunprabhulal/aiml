"""Run one chosen question with the configured ADK simulation App (fresh model requests)."""
import argparse
import asyncio

import simulated


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question")
    parser.add_argument("--fault", choices=["none", *simulated.FAULTS], default="outage")
    parser.add_argument("--retry", choices=["none", "raise", "answer"], default="none")
    return parser.parse_args()


async def main(args):
    events = []
    app = simulated.build_app(fault=None if args.fault == "none" else args.fault,
                              instruction=simulated.INSTRUCTION + simulated.ON_ERROR,
                              retry=None if args.retry == "none" else args.retry)
    try:
        await simulated.ask(app, args.question, events)
    finally:
        print("\n".join(simulated.show(events)))


if __name__ == "__main__":
    asyncio.run(main(parse_args()))
