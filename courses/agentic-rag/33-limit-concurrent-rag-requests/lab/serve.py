"""Start actual Uvicorn with a prebound loopback socket supplied by the demo."""
import argparse
import socket
import uvicorn

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--fd',type=int,required=True);parser.add_argument('--app',default='api:app');args=parser.parse_args()
    listener=socket.socket(fileno=args.fd)
    try:uvicorn.Server(uvicorn.Config(args.app,log_level='info',access_log=False)).run(sockets=[listener])
    finally:listener.close()
