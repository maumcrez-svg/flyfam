"""Read-only, loopback spectacle. Reads only the two public feed contracts."""
from __future__ import annotations

import argparse
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from urllib.parse import parse_qs, urlsplit

STATIC = Path(__file__).parent / 'static'
KINDS = {'SNIFF', 'PICK', 'OPEN', 'MARK', 'CLOSE', 'CREDIT', 'HEARTBEAT', 'THROTTLED', 'RPC_ERROR'}


class Feed:
    def __init__(self, root: Path):
        self.root = root
        self.events = deque(maxlen=12000)
        self.offsets = {}
        self.lock = threading.Lock()

    def read(self, after=0):
        with self.lock:
            state = json.loads((self.root / 'state.json').read_text())
            if state.get('version') != 'pons-live-state-1':
                raise ValueError('Unsupported feed version')
            # Bounded cold start; two UTC days cover midnight. Partial final lines
            # are retried, not consumed. Only the public spectacle journal is read.
            paths = sorted(self.root.glob('events-????-??-??.jsonl'))[-2:]
            for path in paths:
                stat = path.stat()
                old = self.offsets.get(path.name)
                offset = old[1] if old and old[0] == stat.st_ino and old[1] <= stat.st_size else max(0, stat.st_size - 16 * 1024 * 1024)
                with path.open('rb') as stream:
                    stream.seek(offset)
                    if not old and offset:
                        stream.readline()
                    for _ in range(16000):
                        start = stream.tell()
                        line = stream.readline()
                        if not line or not line.endswith(b'\n'):
                            stream.seek(start)
                            break
                        try:
                            event = json.loads(line)
                        except (ValueError, UnicodeError):
                            continue
                        if event.get('kind') in KINDS and isinstance(event.get('seq'), int):
                            if not self.events or event['seq'] > self.events[-1]['seq']:
                                self.events.append(event)
                    self.offsets[path.name] = (stat.st_ino, stream.tell())
            # The journal can be one event ahead of the atomic state snapshot.
            events = [e for e in self.events if e['seq'] <= state['seq']]
            latest_sniff = next((e for e in reversed(events) if e['kind'] == 'SNIFF' and not e.get('holding')), None)
            delta = [e for e in events if e['seq'] > after] if after else events[-200:]
            gap = any(b['seq'] != a['seq'] + 1 for a, b in zip(delta, delta[1:]))
            return {'state': state, 'events': delta[-1000:], 'last_sniff': latest_sniff,
                    'reset': bool(after and (after > state['seq'] or (events and after < events[0]['seq'] - 1) or len(delta) > 1000 or gap))}

    def replay(self, episode):
        self.read()
        with self.lock:
            events = list(self.events)
        start = next((i for i, e in enumerate(events) if e['kind'] == 'OPEN' and str(e.get('episode_id')) == episode), None)
        end = next((i for i, e in enumerate(events) if e['kind'] == 'CREDIT' and str(e.get('episode_id')) == episode), None)
        if start is None or end is None or end < start:
            raise LookupError('This episode is outside the available replay window.')
        # Include the actual choice and sniff before the entry, when available.
        beginning = start
        for i in range(start - 1, max(-1, start - 12), -1):
            if events[i].get('tick') != events[start].get('tick'):
                break
            beginning = i
        selected = events[beginning:end + 1]
        if any(b['seq'] != a['seq'] + 1 for a, b in zip(selected, selected[1:])):
            raise LookupError('The available episode has a journal gap; replay is unavailable.')
        return {'episode_id': episode, 'events': selected, 'mode': 'REPLAY'}


def handler(feed):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            url = urlsplit(self.path)
            args = parse_qs(url.query)
            try:
                if url.path == '/api/feed':
                    payload = feed.read(max(0, int(args.get('after', ['0'])[0])))
                    return self.send(200, json.dumps(payload).encode(), 'application/json')
                if url.path == '/api/replay':
                    payload = feed.replay(args.get('episode', [''])[0])
                    return self.send(200, json.dumps(payload).encode(), 'application/json')
                files = {'/': ('index.html', 'text/html'), '/app.js': ('app.js', 'text/javascript'), '/style.css': ('style.css', 'text/css'), '/fly.svg': ('fly.svg', 'image/svg+xml')}
                if url.path in files:
                    name, mime = files[url.path]
                    return self.send(200, (STATIC / name).read_bytes(), mime)
                self.send(404, b'Not found', 'text/plain')
            except LookupError as exc:
                self.send(404, json.dumps({'error': str(exc)}).encode(), 'application/json')
            except (OSError, ValueError, KeyError):
                self.send(503, b'{"error":"Feed temporarily unavailable"}', 'application/json')

        def send(self, code, data, mime):
            self.send_response(code)
            self.send_header('Content-Type', mime + '; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_):
            pass
    return Handler


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--feed-dir', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8796)
    options = parser.parse_args()
    server = ThreadingHTTPServer(('127.0.0.1', options.port), handler(Feed(options.feed_dir)))
    print(f'Spectacle: http://127.0.0.1:{options.port} (read-only feed)', flush=True)
    server.serve_forever()
