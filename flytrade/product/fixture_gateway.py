"""Bounded, opt-in bridge to the isolated local demo. Never a general RPC proxy."""
from collections import deque
import http.client
import json
import re
import threading
import time
from urllib.parse import urlsplit


class FixtureGateway:
    def __init__(self, port, origin):
        if not 1 <= port <= 65535:
            raise ValueError('Invalid local fixture port')
        self.port = port
        self.origin = origin
        self.verified_until = 0
        self.lock = threading.Lock()
        self.writes = deque()

    def allow_write(self, address):
        with self.lock:
            now = time.monotonic()
            while self.writes and self.writes[0][0] < now - 60:
                self.writes.popleft()
            if len(self.writes) >= 240 or sum(ip == address for _, ip in self.writes) >= 60:
                return False
            self.writes.append((now, address))
            return True

    def exchange(self, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=4)
        try:
            conn.request(method, path, body=body, headers={
                'Content-Type': 'application/json',
                'Origin': f'http://127.0.0.1:{self.port}',
            })
            response = conn.getresponse()
            payload = response.read(1024 * 1024 + 1)
            if len(payload) > 1024 * 1024:
                raise ValueError('Fixture response exceeded bound')
            return response.status, payload
        finally:
            conn.close()

    def verify(self):
        with self.lock:
            if time.monotonic() < self.verified_until:
                return
            status, payload = self.exchange('GET', '/api/bags')
            if status != 200 or json.loads(payload).get('fixture') is not True:
                raise ValueError('Upstream is not an explicit fixture')
            self.verified_until = time.monotonic() + 5

    def handle(self, handler, parsed):
        path = parsed.path.removeprefix('/fixture')
        read_paths = {'/api/live', '/api/health', '/api/watchlist', '/api/position',
                      '/api/career', '/api/story', '/api/highlights', '/api/missed',
                      '/api/away', '/api/episodes', '/api/bags', '/api/bags/claims',
                      '/api/bags/money', '/api/bags/proof', '/api/bags/audit', '/demo/wallets'}
        reads = path in read_paths or re.fullmatch(
            r'/api/episode/[A-Za-z0-9_%:-]{1,150}(?:/points|/artifacts)?', path)
        writes = path in {'/api/bags/challenge', '/api/bags/action', '/demo/sign'}
        if len(handler.path) > 4096 or not (
            handler.command in ('GET', 'HEAD') and reads or handler.command == 'POST' and writes
        ):
            handler._json(404, {'error': 'Unknown fixture route', 'fixture': True})
            return
        try:
            body = None
            if handler.command == 'POST':
                origin = handler.headers.get('Origin')
                accepted = {self.origin}
                own = urlsplit(self.origin)
                if own.hostname in ('127.0.0.1', 'localhost'):
                    accepted |= {f'http://{host}:{own.port}' for host in ('127.0.0.1', 'localhost')}
                if origin not in accepted:
                    handler._json(403, {'error': 'Fixture origin is not authorized'})
                    return
                if not self.allow_write(handler.client_address[0]):
                    handler._json(429, {'error': 'Fixture action rate limit reached'})
                    return
                length = int(handler.headers.get('Content-Length', '0'))
                if not 0 < length <= 8192 or handler.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    raise ValueError('Invalid fixture body')
                handler.connection.settimeout(5)
                body = handler.rfile.read(length)
                if not isinstance(json.loads(body), dict):
                    raise ValueError('Expected an object')
            self.verify()
            status, payload = self.exchange('POST' if body is not None else 'GET',
                                            path + ('?' + parsed.query if parsed.query else ''), body)
            data = json.loads(payload)
            handler._json(status, data)
        except (ValueError, OSError, http.client.HTTPException):
            handler._json(503, {'error': 'Isolated demo unavailable. The live broadcast is separate.', 'fixture': True})
