"""A throwaway PostgreSQL 17 cluster with pgvector, for this lesson only.

    with Cluster() as pg:          # initdb in a temporary directory, start on a free port
        print(pg.url)              # postgresql+psycopg://rag@127.0.0.1:<port>/rag

It listens on 127.0.0.1 only, never on port 5432, has no Unix socket, and is
stopped and deleted on exit. Set PG_BIN if the PostgreSQL 17 binaries are not in
/opt/homebrew/opt/postgresql@17/bin.
"""
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile

PG_BIN = Path(os.environ.get('PG_BIN', '/opt/homebrew/opt/postgresql@17/bin'))
ENV = {**os.environ, 'LC_ALL': 'C'}


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    if port == 5432:
        raise RuntimeError('refusing port 5432')
    return port


class Cluster:
    def __enter__(self):
        version = subprocess.run([PG_BIN / 'postgres', '--version'], capture_output=True, text=True, check=True).stdout
        if ' 17.' not in version:
            raise RuntimeError(f'this lesson needs PostgreSQL 17, found {version.strip()}')
        self.dir, self.port = Path(tempfile.mkdtemp(prefix='rag-pg-')), free_port()
        data = self.dir / 'data'
        try:
            subprocess.run([PG_BIN / 'initdb', '-D', data, '-U', 'rag', '-A', 'trust', '-E', 'UTF8', '--locale=C'],
                           check=True, capture_output=True, env=ENV)
            options = f"-p {self.port} -c listen_addresses=127.0.0.1 -c unix_socket_directories=''"
            subprocess.run([PG_BIN / 'pg_ctl', '-D', data, '-o', options, '-l', self.dir / 'server.log', '-w', 'start'],
                           check=True, capture_output=True, env=ENV)
            subprocess.run([PG_BIN / 'createdb', '-h', '127.0.0.1', '-p', str(self.port), '-U', 'rag', 'rag'],
                           check=True, capture_output=True, env=ENV)
        except BaseException:
            self.__exit__()
            raise
        self.url = f'postgresql+psycopg://rag@127.0.0.1:{self.port}/rag'
        return self

    def __exit__(self, *exc):
        if (self.dir / 'data' / 'postmaster.pid').exists():
            subprocess.run([PG_BIN / 'pg_ctl', '-D', self.dir / 'data', '-m', 'fast', '-w', 'stop'],
                           check=True, capture_output=True, env=ENV)
        shutil.rmtree(self.dir, ignore_errors=True)
