"""Serve the tasks server over stdio or Streamable HTTP.

Run: python serve.py                      (stdio: the host starts this process)
     python serve.py --http --port 8000   (Streamable HTTP at http://127.0.0.1:8000/mcp)
"""
import argparse

from tasks_server import server

parser = argparse.ArgumentParser()
parser.add_argument("--http", action="store_true", help="serve Streamable HTTP instead of stdio")
parser.add_argument("--port", type=int, default=8000)
args = parser.parse_args()

if args.http:
    server.run("streamable-http", host="127.0.0.1", port=args.port)
else:
    server.run()
