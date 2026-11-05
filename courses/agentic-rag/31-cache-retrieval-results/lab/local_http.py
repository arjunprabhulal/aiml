"""Actual Uvicorn subprocesses on prebound loopback sockets, no external traffic."""
from contextlib import contextmanager
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import httpx

@contextmanager
def server(root, logs, module='app:app'):
    logs=Path(logs);logs.mkdir(parents=True,exist_ok=True)
    listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(128)
    port=listener.getsockname()[1]
    with (logs/'server.stdout.txt').open('w') as out,(logs/'server.stderr.txt').open('w') as err:
        process=subprocess.Popen([sys.executable,'-m','uvicorn',module,'--fd',str(listener.fileno()),'--no-access-log'],cwd=root,pass_fds=(listener.fileno(),),stdout=out,stderr=err)
        listener.close()
        try:
            with httpx.Client(base_url=f'http://127.0.0.1:{port}',timeout=5,trust_env=False) as client:
                deadline=time.monotonic()+10
                while True:
                    if process.poll() is not None:raise RuntimeError('server_start_failed')
                    try:
                        if client.get('/health').status_code==200:break
                    except httpx.TransportError:pass
                    if time.monotonic()>=deadline:raise RuntimeError('server_start_timeout')
                    time.sleep(.02)
                yield client
        finally:
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
