"""Create and remove a throwaway PostgreSQL 17 cluster for this lesson.

Usage:
  python lesson_cluster.py create DATA_DIR [--port 54329]   # prints the reader DSN
  python lesson_cluster.py destroy DATA_DIR

The cluster lives entirely in DATA_DIR, listens on localhost only, has no Unix
socket and uses scram-sha-256 passwords. It never touches another cluster or a
Homebrew service. Set PG_BIN if the PostgreSQL 17 binaries are not in
/opt/homebrew/opt/postgresql@17/bin.
"""
import argparse
import os
import re
import secrets
import shutil
import socket
import subprocess
from pathlib import Path

import psycopg
from psycopg import sql

HERE = Path(__file__).resolve().parent
PG_BIN = Path(os.environ.get("PG_BIN", "/opt/homebrew/opt/postgresql@17/bin"))
DATABASE = "docs_lesson"
ADMIN, OWNER, READER = "lesson_admin", "docs_owner", "mcp_reader"
ENV = {**os.environ, "LC_ALL": "C"}  # the macOS postmaster refuses to start without a valid locale


def dsn(user, password, port, database=DATABASE):
    return f"host=localhost port={port} dbname={database} user={user} password={password}"


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def server_version():
    output = subprocess.run([PG_BIN / "postgres", "--version"], capture_output=True, text=True, check=True).stdout
    match = re.search(r"\b(\d+)\.(\d+)", output)
    if not match or match[1] != "17":
        raise SystemExit(f"This lesson needs PostgreSQL 17; found: {output.strip()}")
    return f"{match[1]}.{match[2]}"


class LessonCluster:
    """A cluster in data_dir. create() starts and seeds it; destroy() stops it and deletes data_dir."""

    def __init__(self, data_dir, port=None):
        if not str(data_dir).strip():
            raise SystemExit("give the cluster a directory; an empty path is refused")
        self.data_dir = Path(data_dir).expanduser().resolve()
        if self.data_dir in (Path.cwd(), Path.home(), Path(self.data_dir.anchor)):
            raise SystemExit(f"refusing to use {self.data_dir} as a cluster directory")
        self.port = port or free_port()
        self.admin_password = secrets.token_urlsafe(18)
        self.reader_password = secrets.token_urlsafe(18)

    @property
    def reader_dsn(self):
        return dsn(READER, self.reader_password, self.port)

    def admin_dsn(self, database=DATABASE):
        return dsn(ADMIN, self.admin_password, self.port, database)

    def create(self):
        self.version = server_version()
        if self.data_dir.exists():
            raise SystemExit(f"{self.data_dir} already exists; destroy it first")
        try:
            self._create()
        except BaseException:
            self.destroy()  # never leave a running server behind a deleted data directory
            raise
        return self

    def _create(self):
        self.data_dir.mkdir(parents=True)
        password_file = self.data_dir / "admin-password"
        password_file.write_text(self.admin_password + "\n")
        password_file.chmod(0o600)
        subprocess.run([PG_BIN / "initdb", "-D", self.data_dir / "data", "-U", ADMIN, "--auth=scram-sha-256",
                        f"--pwfile={password_file}", "-E", "UTF8", "--locale=C"],
                       check=True, capture_output=True, env=ENV)
        options = f"-p {self.port} -c listen_addresses=localhost -c unix_socket_directories=''"
        subprocess.run([PG_BIN / "pg_ctl", "-D", self.data_dir / "data", "-o", options,
                        "-l", self.data_dir / "server.log", "-w", "start"], check=True, capture_output=True, env=ENV)
        self.seed()

    def seed(self):
        with psycopg.connect(self.admin_dsn("postgres"), autocommit=True) as admin:
            admin.execute(f"CREATE ROLE {OWNER} NOLOGIN")
            admin.execute(sql.SQL("CREATE ROLE {} LOGIN CONNECTION LIMIT 5 PASSWORD {}").format(
                sql.Identifier(READER), sql.Literal(self.reader_password)))
            admin.execute(f"CREATE DATABASE {DATABASE} OWNER {OWNER}")
        with psycopg.connect(self.admin_dsn(), autocommit=True) as admin:
            admin.execute(f"SET ROLE {OWNER}")
            admin.execute((HERE / "schema.sql").read_text())
            admin.execute("RESET ROLE")
            admin.execute((HERE / "grants.sql").read_text())

    def destroy(self):
        """Stop the server and delete data_dir, but only if data_dir looks like a lesson cluster."""
        if not self.data_dir.exists():
            return
        if any(self.data_dir.iterdir()) and not (self.data_dir / "admin-password").is_file():
            raise SystemExit(f"refusing to delete {self.data_dir}: it is not a lesson cluster (no admin-password file)")
        if (self.data_dir / "data" / "postmaster.pid").exists():
            subprocess.run([PG_BIN / "pg_ctl", "-D", self.data_dir / "data", "-m", "fast", "-w", "stop"],
                           check=True, capture_output=True, env=ENV)
        shutil.rmtree(self.data_dir)

    def __enter__(self):
        return self.create()

    def __exit__(self, *exc):
        self.destroy()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["create", "destroy"])
    parser.add_argument("data_dir")
    parser.add_argument("--port", type=int, default=54329)
    options = parser.parse_args(argv)
    cluster = LessonCluster(options.data_dir, options.port)
    if options.command == "create":
        cluster.create()
        dsn_file = cluster.data_dir / "reader.dsn"
        dsn_file.write_text(cluster.reader_dsn + "\n")
        dsn_file.chmod(0o600)
        print(f"PostgreSQL {cluster.version} on localhost:{cluster.port}; reader DSN saved in {dsn_file}")
    else:
        cluster.destroy()
        print(f"stopped and removed {cluster.data_dir}")


if __name__ == "__main__":
    main()
