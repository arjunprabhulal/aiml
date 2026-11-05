"""Same-origin browser inspector over the unchanged local FastAPI adapter."""
import argparse
import asyncio
from pathlib import Path
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app import create_app
from tools import DocumentationTools

class ControlledFaultTools(DocumentationTools):
    def search(self,**arguments):
        super().search(**arguments)
        raise RuntimeError('controlled_inspector_tool_failure')

def create_inspector_app(*,fixture_delay_seconds=0,controlled_fault=False):
    if not 0<=fixture_delay_seconds<=1:raise ValueError('unsupported_fixture_delay')
    app=create_app(tool_factory=ControlledFaultTools if controlled_fault else DocumentationTools)
    static=Path(__file__).parent/'static'
    app.mount('/inspector-assets',StaticFiles(directory=static),name='inspector-assets')
    @app.get('/inspector',include_in_schema=False)
    def inspector():return FileResponse(static/'inspector.html.txt',media_type='text/html',headers={'Cache-Control':'no-store'})
    if fixture_delay_seconds:
        @app.middleware('http')
        async def controlled_delay(request,call_next):
            if request.method=='POST' and request.url.path=='/retrieve':await asyncio.sleep(fixture_delay_seconds)
            return await call_next(request)
    return app

app=create_inspector_app()

if __name__=='__main__':
    import uvicorn
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--fixture-delay-ms',type=int,default=0,help='Controlled screenshot/test fixture, not normal response timing')
    parser.add_argument('--controlled-fault',action='store_true',help='Deliberate tool failure fixture, not a production option')
    args=parser.parse_args()
    uvicorn.run(create_inspector_app(fixture_delay_seconds=args.fixture_delay_ms/1000,controlled_fault=args.controlled_fault),host='127.0.0.1',port=args.port,log_level='warning')
