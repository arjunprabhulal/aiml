"""A throwaway PostgreSQL 17 cluster plus an MCP Toolbox server in front of it.

Run: python lab.py            # starts both, prints the Toolbox URL, stops and deletes both on Ctrl-C
Set PG_BIN if the PostgreSQL 17 binaries are not in /opt/homebrew/opt/postgresql@17/bin,
and TOOLBOX_BIN if `toolbox` (MCP Toolbox for Databases 0.21.0) is not on PATH.
The cluster lives in a new temporary directory, listens on 127.0.0.1 only and never uses port 5432.
"""
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import psycopg
from psycopg import sql

HERE = Path(__file__).resolve().parent
PG_BIN = Path(os.environ.get("PG_BIN", "/opt/homebrew/opt/postgresql@17/bin"))
TOOLBOX = os.environ.get("TOOLBOX_BIN", shutil.which("toolbox") or "toolbox")
ENV = {**os.environ, "LC_ALL": "C"}


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    assert port != 5432, "never touch the default PostgreSQL port"
    return port


def config_error(tools_file: Path) -> str:
    """Start toolbox on a tools file it should refuse and return the first line of its error."""
    result = subprocess.run([TOOLBOX, "--tools-file", str(tools_file), "--port", str(free_port())],
                            capture_output=True, text=True, timeout=20, env={**os.environ, "PG_PORT": "1", "PG_PASSWORD": "x"})
    lines = [line for line in (result.stdout + result.stderr).splitlines() if " ERROR " in line]
    message = lines[0].split(" ERROR ", 1)[1].split("\\n", 1)[0] if lines else f"exit {result.returncode}"
    return message.replace(str(tools_file), tools_file.name)


class Lab:
    """create() starts PostgreSQL and Toolbox; destroy() stops both and deletes the data directory."""

    def __init__(self, tools_file: Path = HERE / "tools.yaml"):
        self.tools_file = tools_file
        self.root = Path(tempfile.mkdtemp(prefix="adk-toolbox-lab-"))
        self.pg_port, self.toolbox_port = free_port(), free_port()
        self.admin_password, self.reader_password = secrets.token_urlsafe(18), secrets.token_urlsafe(18)
        self.toolbox = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.toolbox_port}"

    def admin(self, database: str = "docs_analytics"):
        return psycopg.connect(host="127.0.0.1", port=self.pg_port, dbname=database,
                               user="lab_admin", password=self.admin_password, autocommit=True)

    def create(self) -> "Lab":
        try:
            pwfile = self.root / "admin-password"
            pwfile.write_text(self.admin_password + "\n")
            subprocess.run([PG_BIN / "initdb", "-D", self.root / "data", "-U", "lab_admin", "--auth=scram-sha-256",
                            f"--pwfile={pwfile}", "-E", "UTF8", "--locale=C"], check=True, capture_output=True, env=ENV)
            options = f"-p {self.pg_port} -c listen_addresses=127.0.0.1 -c unix_socket_directories=''"
            subprocess.run([PG_BIN / "pg_ctl", "-D", self.root / "data", "-o", options, "-l", self.root / "pg.log",
                            "-w", "start"], check=True, capture_output=True, env=ENV)
            with self.admin("postgres") as conn:
                conn.execute(sql.SQL("CREATE ROLE toolbox_reader LOGIN PASSWORD {}").format(sql.Literal(self.reader_password)))
                conn.execute("CREATE DATABASE docs_analytics")
            with self.admin() as conn:
                conn.execute((HERE / "schema.sql").read_text())
                conn.execute((HERE / "grants.sql").read_text())
            self.start_toolbox()
        except BaseException:
            self.destroy()
            raise
        return self

    def start_toolbox(self) -> None:
        env = {**os.environ, "PG_PORT": str(self.pg_port), "PG_PASSWORD": self.reader_password}
        self.toolbox = subprocess.Popen(
            [TOOLBOX, "--tools-file", str(self.tools_file), "--port", str(self.toolbox_port), "--disable-reload"],
            env=env, stdout=open(self.root / "toolbox.log", "w"), stderr=subprocess.STDOUT)
        for _ in range(100):
            try:
                urllib.request.urlopen(self.url + "/", timeout=1)
                return
            except OSError:
                if self.toolbox.poll() is not None:
                    raise RuntimeError("toolbox exited:\n" + (self.root / "toolbox.log").read_text())
                time.sleep(0.1)
        raise RuntimeError("toolbox did not start")

    def stop_toolbox(self) -> None:
        if self.toolbox and self.toolbox.poll() is None:
            self.toolbox.terminate()
            self.toolbox.wait(timeout=10)

    def destroy(self) -> None:
        self.stop_toolbox()
        if (self.root / "data" / "postmaster.pid").exists():
            subprocess.run([PG_BIN / "pg_ctl", "-D", self.root / "data", "-m", "fast", "-w", "stop"],
                           check=True, capture_output=True, env=ENV)
        shutil.rmtree(self.root, ignore_errors=True)

    def __enter__(self) -> "Lab":
        return self.create()

    def __exit__(self, *exc) -> None:
        self.destroy()


if __name__ == "__main__":
    with Lab() as lab:
        print(f"PostgreSQL on 127.0.0.1:{lab.pg_port}; MCP Toolbox at {lab.url}. Ctrl-C stops both.", flush=True)
        try:
            lab.toolbox.wait()
        except KeyboardInterrupt:
            pass
        sys.exit(0)
