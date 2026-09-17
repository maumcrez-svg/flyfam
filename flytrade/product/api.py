"""Read-only spectator HTTP API. Each request reads one SQLite snapshot."""
import argparse
import hashlib
import faulthandler
import http.client
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import re
from urllib.parse import parse_qs, unquote, urlsplit
from .history import ProductHistory, canonical
from .views import Views
from .identity import IdentityCache, IdentityResolver, tokens_in, ADDRESS, CHAIN_ID

EPISODE_ID=re.compile(r'[A-Za-z0-9_-]{1,48}:[0-9]{1,20}\Z')
CSP="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; font-src 'self'; connect-src 'self' blob:; media-src 'self' blob:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'"


def worker_running(path):
    if path is None:
        return None
    try:
        pid=int(Path(path).read_text().strip())
        if pid<=0:
            return False
        os.kill(pid,0)
        args=Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
        return any(arg.endswith(b'/product/run.py') or arg==b'product/run.py' for arg in args)
    except (OSError,ValueError):
        return False


class ResponseWatchdog:
    """Exercise the HTTP + projection path; terminate only an unresponsive viewer.

    A responsive OFFLINE/STALE/error projection is not a process failure. Three
    consecutive transport/read timeouts dump local stacks and exit nonzero so
    the existing user service can restart this read-only process independently.
    """
    def __init__(self,server,*,interval=10,timeout=3,failures=3,terminate=None):
        host,port=server.server_address[:2]
        self.host='127.0.0.1' if host in ('','0.0.0.0') else '::1' if host=='::' else host
        self.port=port;self.interval=interval;self.timeout=timeout;self.failures=failures
        self.terminate=terminate or os._exit
        self.stopped=threading.Event()
        self.thread=threading.Thread(target=self._run,name='spectator-http-watchdog',daemon=True)

    def start(self):self.thread.start()

    def close(self):
        self.stopped.set()
        self.thread.join(timeout=self.timeout+.5)

    def _run(self):
        failed=0
        while not self.stopped.wait(self.interval):
            connection=http.client.HTTPConnection(self.host,self.port,timeout=self.timeout)
            try:
                connection.request('GET','/api/live')
                response=connection.getresponse()
                response.read(1024*1024+1)
                failed=0
            except (OSError,http.client.HTTPException):
                failed+=1
            finally:connection.close()
            if failed>=self.failures and not self.stopped.is_set():
                print('[viewer-watchdog] API unresponsive on consecutive probes; '
                      'capturing stacks and exiting for service recovery. Trader is untouched.',
                      file=sys.stderr,flush=True)
                try:faulthandler.dump_traceback(file=sys.stderr,all_threads=True)
                except (OSError,ValueError):pass
                self.terminate(70)
                return


class SpectatorServer(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,address,*,database,static_dir=None,pid_path=None,metadata_rpc=None,identity_cache=None,bag_room=None,fixture_port=None,public_origin=None):
        import sqlite3
        self.sqlite_runtime={'sqlite_version':sqlite3.sqlite_version,'sqlite_threadsafety':sqlite3.threadsafety}
        self.bag_room=bag_room
        from .wallet_config import public_config
        self.wallet_config=public_config(test_holders=bool(bag_room and (bag_room.config.fixture or bag_room.config.integration)))
        self.database=Path(database)
        self.static_dir=Path(static_dir).resolve() if static_dir else None
        self.pid_path=pid_path
        self.identities=IdentityCache(identity_cache or self.database.with_suffix('.identities.sqlite3'),IdentityResolver(metadata_rpc)) if metadata_rpc else None
        super().__init__(address,Handler)
        from .fixture_gateway import FixtureGateway
        self.fixture_gateway=FixtureGateway(fixture_port,public_origin or f'http://127.0.0.1:{self.server_port}') if fixture_port else None

    def server_close(self):
        super().server_close()
        if self.identities:self.identities.close()


class Handler(BaseHTTPRequestHandler):
    server_version='FlySpectacle/2'

    def log_message(self,*args):
        pass

    def _headers(self,status,content_type,length=0,etag=None,max_age=None):
        self.send_response(status)
        self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(length))
        self.send_header('Cache-Control','no-cache' if max_age is None else f'public, max-age={max_age}')
        self.send_header('X-Content-Type-Options','nosniff')
        policy=CSP
        if self.server.wallet_config['walletconnect_enabled']:
            from .wallet_config import CONNECT_ORIGINS
            policy=policy.replace("connect-src 'self' blob:","connect-src 'self' blob: "+' '.join(CONNECT_ORIGINS))
            policy+="; frame-src https://verify.walletconnect.com https://verify.walletconnect.org"
        self.send_header('Content-Security-Policy',policy)
        self.send_header('Referrer-Policy','same-origin')
        self.send_header('Permissions-Policy','camera=(), microphone=(), geolocation=()')
        if etag:
            self.send_header('ETag',etag)
        self.end_headers()

    def _json(self,status,payload,etag=None):
        body=canonical(payload)
        if len(body)>1024*1024:
            status=503;body=b'{"error":"Projection response exceeded its bound"}'
        self._headers(status,'application/json; charset=utf-8',len(body),etag)
        if self.command!='HEAD':
            self.wfile.write(body)

    def do_HEAD(self):
        self.do_GET()

    def do_POST(self):
        from flytrade.bags.http import handle
        parsed=urlsplit(self.path)
        if parsed.path.startswith('/fixture/'):return self._fixture(parsed)
        if handle(self,unquote(parsed.path),parsed.query,post=True):return
        self._json(405,{'error':'Spectator API is read-only'})

    do_PUT=do_POST
    do_PATCH=do_POST
    do_DELETE=do_POST

    def do_GET(self):
        parsed=urlsplit(self.path);path=unquote(parsed.path)
        if parsed.path.startswith('/fixture/'):return self._fixture(parsed)
        if path=='/api/wallet-config':return self._json(200,self.server.wallet_config)
        if path=='/api/site':
            room=self.server.bag_room;proof=None
            if room:
                from flytrade.bags.store import Store
                with room.store.read() as db:proof=Store.get(db,'phase_a_bridge_proof')
            integration=bool(room and room.config.integration)
            return self._json(200,{'fixture_enabled':bool(self.server.fixture_gateway),
                'fixture':bool(room and room.config.fixture),'test_holders':integration,
                'bridge_enabled':bool(room and room.config.configured),'bridge_verified':bool(proof) if integration else None,
                **(room.config.sources if room else {}),
                'bag_configured':bool(room and room.config.configured and (proof or not integration))})
        if path.startswith(('/api/bags','/api/test-holders','/api/claims')) or path=='/api/vault/summary':
            from flytrade.bags.http import handle
            if handle(self,path,parsed.query):return
        if not path.startswith('/api/'):
            return self._static(path)
        if path.startswith('/api/token-icon/'):
            parts=path.removeprefix('/api/token-icon/').split('/')
            if len(parts)!=2 or parts[0]!=str(CHAIN_ID) or not ADDRESS.fullmatch(parts[1]) or not self.server.identities:
                self._json(404,{'error':'Token icon unavailable'});return
            icon=self.server.identities.icon(parts[1])
            if not icon:self._json(404,{'error':'Token icon unavailable'});return
            data,mime=icon;icon_etag='"'+hashlib.sha256(data).hexdigest()[:24]+'"'
            if self.headers.get('If-None-Match')==icon_etag:
                self._headers(304,mime,etag=icon_etag,max_age=3600);return
            self._headers(200,mime,len(data),etag=icon_etag,max_age=3600)
            if self.command!='HEAD':self.wfile.write(data)
            return
        try:
            query=parse_qs(parsed.query,keep_blank_values=True)
            if any(len(value)!=1 for value in query.values()):
                raise ValueError('Query parameters must have one value')
            def integer(name,default=None):
                value=query.get(name,[default])[0]
                if value is None:return None
                result=int(value)
                if not 0<=result<=2**63-1:raise ValueError('Cursor outside range')
                return result
            with_read=ProductHistory(self.server.database,readonly=True)
            try:
                with_read.db.execute('BEGIN')
                views=Views(with_read)
                status=views.health()
                running=worker_running(self.server.pid_path)
                status['worker_running']=running
                status['viewer_runtime']=self.server.sqlite_runtime
                if running is False:status['status']='OFFLINE'
                stamp=f"{self.server.sqlite_runtime['sqlite_version']}:{self.path}:{status['projected_seq']}:{status['status']}:{running}:{self.server.identities.revision if self.server.identities else 0}"
                etag='"'+hashlib.sha256(stamp.encode()).hexdigest()[:24]+'"'
                if self.headers.get('If-None-Match')==etag and not path.endswith('/artifacts'):
                    self._headers(304,'application/json',etag=etag)
                    return
                if path=='/api/live':
                    result=views.live();result['health']=status
                elif path=='/api/health':result=status
                elif path=='/api/watchlist':result=views.watchlist()
                elif path=='/api/position':result=views.position()
                elif path=='/api/career':result=views.career()
                elif path=='/api/story':
                    result=views.story(after=integer('after'),limit=integer('limit',50),through=integer('through'))
                elif path=='/api/highlights':result=views.highlights()
                elif path=='/api/missed':
                    result=views.missed(category=query.get('category',[None])[0],before=integer('before'),limit=integer('limit',20))
                elif path=='/api/away':result=views.away(integer('after',0))
                elif path=='/api/episodes':result=views.episodes(before=integer('before'),limit=integer('limit',20))
                elif path.startswith('/api/episode/'):
                    key=path.removeprefix('/api/episode/')
                    points=key.endswith('/points');artifacts=key.endswith('/artifacts')
                    if points:key=key[:-7]
                    if artifacts:key=key[:-10]
                    if not EPISODE_ID.fullmatch(key):
                        self._json(404,{'error':'Unknown episode'});return
                    if artifacts:
                        root=self.server.static_dir
                        def exists(suffix):
                            if root is None:return False
                            candidate=(root/'shares'/(key+suffix)).resolve()
                            return candidate.is_relative_to(root) and candidate.is_file()
                        self._json(200,{'episode_id':key,'mode':'REPLAY','execution':'PAPER',
                            'card':'/shares/'+key+'.png' if exists('.png') else None,
                            'clips':[{'aspect':aspect,'url':'/shares/'+key+'.'+aspect+'.mp4'}
                                for aspect in ('16x9','9x16') if exists('.'+aspect+'.mp4')]})
                        return
                    result=(views.points(key,after=integer('after',0),limit=integer('limit',200),through=integer('through'))
                            if points else views.episode(key,through=integer('through')))
                    if result is None:
                        self._json(404,{'error':'Episode evidence unavailable at this sequence'});return
                else:
                    self._json(404,{'error':'Unknown read-only endpoint'});return
                if self.server.identities and isinstance(result,dict):
                    result['token_identities']=self.server.identities.lookup(tokens_in(result))
                    result['identity_revision']=self.server.identities.revision
                self._json(200,result,etag)
            finally:
                with_read.close()
        except (ValueError,TypeError):
            self._json(400,{'error':'Invalid query'})
        except (BrokenPipeError,ConnectionResetError):
            return
        except Exception:
            # Never expose filesystem paths, SQL or environment in HTTP errors.
            self._json(503,{'error':'Canonical projection unavailable'})

    def _fixture(self,parsed):
        if not self.server.fixture_gateway:
            return self._json(503,{'error':'Isolated demo is not connected','fixture':True})
        return self.server.fixture_gateway.handle(self,parsed)

    def _static(self,path):
        root=self.server.static_dir
        if root is None:
            self._json(404,{'error':'No spectator frontend configured'});return
        if path=='/' or path.startswith('/episode/'):
            relative='index.html'
        else:
            relative=path.lstrip('/')
        resolved=(root/relative).resolve()
        allowed={'.html','.js','.css','.svg','.png','.webp','.woff2','.ttf','.ico','.txt','.mp4','.glb'}
        if not resolved.is_relative_to(root) or resolved.suffix not in allowed or not resolved.is_file():
            self._json(404,{'error':'Asset not found'});return
        self._headers(200,mimetypes.guess_type(resolved.name)[0] or 'application/octet-stream',resolved.stat().st_size)
        if self.command!='HEAD':
            try:
                with resolved.open('rb') as source:
                    while chunk:=source.read(256*1024):self.wfile.write(chunk)
            except (BrokenPipeError,ConnectionResetError):pass


def main():
    from .sqlite_runtime import require_fixed_runtime
    require_fixed_runtime()
    # Owner-only process diagnostics; no public HTTP route exposes stack traces.
    import faulthandler
    import signal
    faulthandler.enable()
    if hasattr(signal,'SIGUSR1'):
        faulthandler.register(signal.SIGUSR1,all_threads=True)
    parser=argparse.ArgumentParser()
    parser.add_argument('--database',required=True)
    parser.add_argument('--host',default='127.0.0.1')
    parser.add_argument('--port',type=int,default=8797)
    parser.add_argument('--static-dir')
    parser.add_argument('--worker-pid')
    parser.add_argument('--metadata-rpc',help='Local node used only by the spectator identity cache')
    parser.add_argument('--identity-cache',help='Separate disposable identity/icon cache SQLite file')
    parser.add_argument('--bag-database',help='Signed Bag Room database; no executor keys')
    parser.add_argument('--fixture-port',type=int,help='Opt-in isolated loopback demo, never production holders')
    parser.add_argument('--public-origin',help='Exact public origin for signed fixture actions')
    args=parser.parse_args()
    bag_room=None
    if args.bag_database:
        from flytrade.bags.config import Config as BagConfig
        from flytrade.bags.store import Store as BagStore
        from flytrade.bags.service import Room
        from flytrade.bags.indexer import Rpc as BagRpc
        bag_room=Room(BagStore(args.bag_database),BagConfig.environment(),signature_rpc=BagRpc(args.metadata_rpc) if args.metadata_rpc else None)
    server=SpectatorServer((args.host,args.port),database=args.database,
        static_dir=args.static_dir,pid_path=args.worker_pid,metadata_rpc=args.metadata_rpc,identity_cache=args.identity_cache,bag_room=bag_room,
        fixture_port=args.fixture_port,public_origin=args.public_origin)
    watchdog=ResponseWatchdog(server);watchdog.start()
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:
        watchdog.close()
        server.server_close()


if __name__=='__main__':main()
