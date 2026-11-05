"""Run an actual loopback transport example with a controlled backend; no model download."""

import json
import urllib.request
from test_server import FixtureBackend, serving


def main():
    backend = FixtureBackend()
    with serving(backend) as (host, port):
        request = urllib.request.Request(
            f"http://{host}:{port}/generate",
            data=json.dumps(
                {"prompt": "Explain cache ownership", "max_new_tokens": 2}
            ).encode(),
        )
        with urllib.request.urlopen(request) as response:
            status = response.status
            kind = response.headers["Content-Type"]
            frames = response.read().decode().strip().split("\n\n")
    print(
        json.dumps(
            {
                "execution_mode": "actual loopback HTTP; controlled text fixture, no model inference",
                "http_status": status,
                "content_type": kind,
                "content_events": len(frames) - 1,
                "done_marker": frames[-1],
                "first_payload": json.loads(frames[0][6:]),
                "backend_steps": backend.count,
                "backend_released": backend.released.is_set(),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
