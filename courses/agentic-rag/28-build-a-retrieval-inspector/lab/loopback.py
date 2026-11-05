"""Actual loopback HTTP harness, not an ASGI/TestClient transport."""
from contextlib import contextmanager
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import httpx

@contextmanager
def running_server(app_import='api:app'):
    with tempfile.TemporaryDirectory(prefix='rag-http-') as directory:
        root=Path(directory);out=(root/'stdout.txt').open('w');err=(root/'stderr.txt').open('w')
        listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(128)
        port=listener.getsockname()[1]
        command=[sys.executable,str(Path(__file__).parent/'serve.py'),'--fd',str(listener.fileno()),'--app',app_import]
        process=subprocess.Popen(command,cwd=Path(__file__).parent,pass_fds=(listener.fileno(),),stdout=out,stderr=err)
        listener.close()
        client=httpx.Client(base_url=f'http://127.0.0.1:{port}',timeout=5,trust_env=False)
        record={'command':['python3','serve.py','--fd','<inherited-loopback-socket>','--app',app_import],'startup_observed':False,'shutdown_exit_status':None}
        try:
            deadline=time.monotonic()+10
            while time.monotonic()<deadline:
                if process.poll() is not None:raise RuntimeError('uvicorn_exited_before_ready')
                try:
                    response=client.get('/health')
                    if response.status_code==200:
                        record['startup_observed']=True;break
                except httpx.TransportError:pass
                time.sleep(0.02)
            else:raise RuntimeError('uvicorn_startup_timeout')
            yield client,record
        finally:
            client.close()
            if process.poll() is None:process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
            record['shutdown_exit_status']=process.returncode
            out.close();err.close();record['stdout']=(root/'stdout.txt').read_text();record['stderr']=(root/'stderr.txt').read_text()
            record['shutdown_complete_observed']='Application shutdown complete.' in record['stderr']
            record['server_process_reaped']=process.poll() is not None
