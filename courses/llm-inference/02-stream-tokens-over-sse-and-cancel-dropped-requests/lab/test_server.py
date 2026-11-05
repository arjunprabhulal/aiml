"""Real loopback HTTP tests. Backend pieces are a controlled transport fixture, not inference."""

import contextlib
import json
import socket
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from server import handler_for


class FixtureBackend:
    def __init__(self):
        self.released = threading.Event()
        self.count = 0

    def stream(self, prompt, limit):
        try:
            for _ in range(limit):
                self.count += 1
                yield "line one\nline two"
                time.sleep(0.005)
        finally:
            self.released.set()


@contextlib.contextmanager
def serving(backend):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(backend))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


class StreamingTests(unittest.TestCase):
    def test_sse_frames_escape_newlines(self):
        backend = FixtureBackend()
        with serving(backend) as (host, port):
            req = urllib.request.Request(
                f"http://{host}:{port}/generate",
                data=json.dumps(
                    {"prompt": "Explain caching", "max_new_tokens": 2}
                ).encode(),
            )
            with urllib.request.urlopen(req) as response:
                body = response.read().decode()
        frames = body.strip().split("\n\n")
        self.assertEqual(len(frames), 3)
        self.assertEqual(json.loads(frames[0][6:])["token"], "line one\nline two")
        self.assertEqual(frames[-1], "data: [DONE]")
        self.assertTrue(backend.released.is_set())

    def test_disconnect_closes_backend_before_output_cap(self):
        backend = FixtureBackend()
        with serving(backend) as (host, port):
            connection = socket.create_connection((host, port))
            body = json.dumps(
                {"prompt": "Explain caches", "max_new_tokens": 128}
            ).encode()
            connection.sendall(
                f"POST /generate HTTP/1.1\r\nHost: localhost\r\nContent-Length: {len(body)}\r\n\r\n".encode()
                + body
            )
            received = b""
            while b"data:" not in received:
                received += connection.recv(4096)
            connection.shutdown(socket.SHUT_RDWR)
            connection.close()
            self.assertTrue(backend.released.wait(2))
            self.assertLess(backend.count, 128)

    def test_empty_prompt_is_rejected_before_backend_starts(self):
        backend = FixtureBackend()
        with serving(backend) as (host, port):
            req = urllib.request.Request(
                f"http://{host}:{port}/generate", data=b'{"prompt":""}'
            )
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(req)
            self.assertEqual(caught.exception.code, 400)
            self.assertEqual(backend.count, 0)


if __name__ == "__main__":
    unittest.main()


class AdmissionTests(unittest.TestCase):
    def test_second_active_request_is_rejected(self):
        backend = FixtureBackend()
        with serving(backend) as (host, port):
            url = f"http://{host}:{port}/generate"
            request = lambda: urllib.request.Request(
                url, data=b'{"prompt":"Explain caching","max_new_tokens":128}'
            )
            first = urllib.request.urlopen(request())
            try:
                self.assertTrue(first.readline().startswith(b"data:"))
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(request())
                self.assertEqual(caught.exception.code, 429)
            finally:
                first.close()
            self.assertTrue(backend.released.wait(2))
