"""Tests for server.py. Run: python3 -m unittest -v test_server.py

Each test talks to a real server on an unused port of 127.0.0.1.
"""
import http.client
import json
import subprocess
import sys
import unittest
from pathlib import Path

import evaluate_service as ev
import kv_cache as kv
import server

HERE = Path(__file__).parent


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = server.Service()
        cls.srv = server.start(service=cls.service)
        cls.port = cls.srv.server_address[1]
        cls.base = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def post(self, body):
        return ev.call(self.base, "POST", "/generate", body)

    def test_listens_on_loopback_only(self):
        self.assertEqual(self.srv.server_address[0], "127.0.0.1")

    def test_health_names_the_checkpoint(self):
        status, reply = ev.call(self.base, "GET", "/health")
        self.assertEqual((status, reply["status"]), (200, "ok"))
        self.assertEqual(reply["checkpoint"], self.service.checkpoint)

    def test_served_text_equals_direct_generation(self):
        for body in ({"prompt": "mia has a red ball."},
                     {"prompt": "zoe has a blue kite.", "temperature": 1.0, "top_k": 3, "seed": 4}):
            with self.subTest(body=body):
                status, reply = self.post(body)
                direct = kv.generate_cached(self.service.params, self.service.tok, **server.parse_request(json.dumps(body)))
                self.assertEqual(status, 200)
                self.assertEqual((reply["text"], reply["stopped"]), (direct["text"], direct["stopped"]))

    def test_bad_requests_get_400(self):
        cases = [(None, b"mia has"), ({"temperature": 1.0}, None), ({"prompt": "mia", "top_p": 0.9}, None),
                 ({"prompt": "mia", "temperature": True}, None), ({"prompt": "mia", "max_new_tokens": True}, None),
                 ({"prompt": "mia", "max_new_tokens": 0}, None),
                 ({"prompt": "mia", "temperature": -1}, None), ({"prompt": ""}, None), ([], None)]
        for body, raw in cases:
            with self.subTest(body=body, raw=raw):
                status, reply = ev.call(self.base, "POST", "/generate", body, raw)
                self.assertEqual(status, 400)
                self.assertTrue(reply["error"])

    def test_null_fields_obey_the_request_contract(self):
        for field in ("prompt", "max_new_tokens", "temperature", "seed"):
            body = {"prompt": "mia has a red ball.", field: None}
            with self.subTest(field=field):
                status, reply = self.post(body)
                self.assertEqual(status, 400)
                self.assertIn("wrong type", reply["error"])
        status, _ = self.post({"prompt": "mia has a red ball.", "top_k": None})
        self.assertEqual(status, 200)  # null means no top-k filter, as omission does

    def test_body_over_the_limit_gets_413(self):
        status, _ = ev.call(self.base, "POST", "/generate", raw=b"x" * (server.MAX_BODY_BYTES + 1))
        self.assertEqual(status, 413)

    def test_missing_length_gets_411(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.putrequest("POST", "/generate")
        conn.endheaders()
        self.assertEqual(conn.getresponse().status, 411)
        conn.close()

    def test_negative_length_gets_400(self):
        # rfile.read(-1) would wait for the client to close, blocking every later request.
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.putrequest("POST", "/generate")
        conn.putheader("Content-Length", "-1")
        conn.endheaders()
        self.assertEqual(conn.getresponse().status, 400)
        conn.close()
        status, _ = ev.call(self.base, "GET", "/health")
        self.assertEqual(status, 200)

    def test_command_line_server_listens_on_loopback_only(self):
        proc = subprocess.Popen([sys.executable, "server.py", "--port", "0"], cwd=HERE,
                                stdout=subprocess.PIPE, text=True)
        try:
            line = proc.stdout.readline().strip()
            self.assertRegex(line, r"^serving on http://127\.0\.0\.1:\d+$")
            status, reply = ev.call(line.split(" on ")[1], "GET", "/health")
            self.assertEqual((status, reply["status"]), (200, "ok"))
        finally:
            proc.terminate()
            proc.wait(timeout=10)
            proc.stdout.close()

    def test_unknown_routes_get_404(self):
        for method, path in (("GET", "/models"), ("POST", "/train")):
            with self.subTest(path=path):
                status, _ = ev.call(self.base, method, path, {"prompt": "mia"} if method == "POST" else None)
                self.assertEqual(status, 404)


class Recorded(unittest.TestCase):
    def test_recorded_report(self):
        result = subprocess.run([sys.executable, "evaluate_service.py", "--check"], cwd=HERE)
        self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
