"""Permanent, compact product evidence. No brain, network or trading imports.

SQLite WAL is the transaction boundary for event identity and projection state.
Payloads are compressed canonical JSON; duplicate delivery is idempotent and
conflicting delivery under an existing identity fails loudly. Raw chain expiry
never touches this database. Readers use query_only connections.
"""
from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import warnings
import zlib

SCHEMA_VERSION = 1


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(blob):
    return hashlib.sha256(blob).hexdigest()


def unpack(blob):
    return json.loads(zlib.decompress(blob))


class EvidenceConflict(ValueError):
    pass


class RecoveryError(RuntimeError):
    pass


class ProductHistory:
    def __init__(self, path, *, readonly=False):
        self.path = Path(path)
        self.readonly = readonly
        if readonly:
            self.db = sqlite3.connect(self.path.resolve().as_uri()+'?mode=ro', uri=True, timeout=10)
            self.db.execute('PRAGMA query_only=ON')
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.db = sqlite3.connect(self.path, timeout=10)
            self.db.execute('PRAGMA journal_mode=WAL')
            self.db.execute('PRAGMA synchronous=FULL')
        self.db.row_factory = sqlite3.Row
        version = self.db.execute('PRAGMA user_version').fetchone()[0]
        if version not in (0, SCHEMA_VERSION):
            raise RecoveryError(f'Unsupported product history schema: {version}')
        if not readonly:
            self.db.executescript('''
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    source TEXT NOT NULL,
                    source_seq INTEGER,
                    kind TEXT NOT NULL,
                    ts INTEGER,
                    token TEXT,
                    episode_id TEXT,
                    round_id TEXT,
                    sha256 TEXT NOT NULL,
                    payload BLOB NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS event_source_seq
                    ON events(source, source_seq) WHERE source_seq IS NOT NULL;
                CREATE INDEX IF NOT EXISTS event_episode ON events(episode_id,seq);
                CREATE INDEX IF NOT EXISTS event_kind_time ON events(kind,ts,seq);
                CREATE INDEX IF NOT EXISTS event_token ON events(token,seq);
                CREATE TABLE IF NOT EXISTS imports (
                    source TEXT PRIMARY KEY, inode INTEGER, offset INTEGER NOT NULL,
                    prefix_sha256 TEXT, updated_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS checkpoints (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
                    seq INTEGER NOT NULL, compatibility TEXT NOT NULL,
                    sha256 TEXT NOT NULL, payload BLOB NOT NULL,
                    created_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS checkpoint_name ON checkpoints(name,id DESC);
                CREATE TABLE IF NOT EXISTS state (
                    name TEXT PRIMARY KEY, seq INTEGER NOT NULL, payload BLOB NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS immutable_events_update BEFORE UPDATE ON events
                    BEGIN SELECT RAISE(ABORT,'canonical product events are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS immutable_events_delete BEFORE DELETE ON events
                    BEGIN SELECT RAISE(ABORT,'canonical product events are permanent'); END;
                PRAGMA user_version=1;
            ''')
        elif version != SCHEMA_VERSION:
            raise RecoveryError('Product history is not initialized')

    def close(self):
        self.db.close()

    @property
    def seq(self):
        return self.db.execute('SELECT coalesce(max(seq),0) FROM events').fetchone()[0]

    def append(self, event_id, event, *, source='spectacle-v2', source_seq=None):
        with self.db:
            return self._append(event_id, event, source=source, source_seq=source_seq)

    def _append(self, event_id, event, *, source, source_seq):
        blob = canonical(event)
        sha = digest(blob)
        previous = self.db.execute('SELECT seq,sha256 FROM events WHERE event_id=?', (event_id,)).fetchone()
        if previous:
            if previous['sha256'] != sha:
                raise EvidenceConflict(f'Conflicting canonical event {event_id}')
            return previous['seq']
        try:
            cursor = self.db.execute('''INSERT INTO events
                (event_id,source,source_seq,kind,ts,token,episode_id,round_id,sha256,payload)
                VALUES (?,?,?,?,?,?,?,?,?,?)''',
                (event_id, source, source_seq, event['kind'], event.get('ts', event.get('cutoff_ts')),
                 event.get('token', event.get('symbol')),
                 str(event['episode_id']) if event.get('episode_id') is not None else None,
                 event.get('round_id'), sha, zlib.compress(blob, 6)))
        except sqlite3.IntegrityError as exc:
            raise EvidenceConflict('Canonical source sequence reused') from exc
        return cursor.lastrowid

    def ingest_p1(self, event):
        source = 'p1:'+str(event.get('run_id', 'pons-live'))
        return self.append(f'{source}:{event["seq"]}', event, source=source, source_seq=int(event['seq']))

    def events(self, *, after=0, limit=100, kinds=None, episode=None, through=None, max_payload_bytes=8*1024*1024):
        clauses, args = ['seq > ?'], [int(after)]
        if kinds:
            clauses.append('kind IN ('+','.join('?' for _ in kinds)+')')
            args.extend(kinds)
        if episode is not None:
            clauses.append('episode_id=?')
            args.append(str(episode))
        if through is not None:
            clauses.append('seq<=?')
            args.append(int(through))
        args.append(min(1000, max(1, int(limit))))
        rows = self.db.execute('SELECT * FROM events WHERE '+' AND '.join(clauses)+' ORDER BY seq LIMIT ?',args)
        output=[]; total=0
        for row in rows:
            raw=zlib.decompress(row['payload'])
            if output and total+len(raw)>max_payload_bytes:
                break
            output.append({'seq':row['seq'],'event_id':row['event_id'],'source':row['source'],
                'source_seq':row['source_seq'],'event':json.loads(raw)})
            total+=len(raw)
        return output


    def save_state(self, name, value, seq=None):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO state VALUES (?,?,?)',
                            (name, self.seq if seq is None else int(seq), zlib.compress(canonical(value))))

    def state(self, name):
        row = self.db.execute('SELECT seq,payload FROM state WHERE name=?', (name,)).fetchone()
        return None if row is None else {'seq':row['seq'], 'value':unpack(row['payload'])}

    def checkpoint(self, name, value, *, compatibility, seq=None):
        blob = canonical(value)
        with self.db:
            self.db.execute('INSERT INTO checkpoints(name,seq,compatibility,sha256,payload,created_at) VALUES (?,?,?,?,?,?)',
                            (name, self.seq if seq is None else int(seq), compatibility, digest(blob), zlib.compress(blob), int(time.time())))
            self.db.execute('DELETE FROM checkpoints WHERE name=? AND id NOT IN (SELECT id FROM checkpoints WHERE name=? ORDER BY id DESC LIMIT 2)',(name,name))

    def recover_checkpoint(self, name, *, compatibility, max_tail=10000):
        rows = self.db.execute('SELECT * FROM checkpoints WHERE name=? ORDER BY id DESC LIMIT 2',(name,)).fetchall()
        if not rows:
            return None
        failures=[]
        for row in rows:
            try:
                if row['compatibility'] != compatibility:
                    raise ValueError('incompatible checkpoint')
                blob = zlib.decompress(row['payload'])
                if digest(blob) != row['sha256']:
                    raise ValueError('checkpoint digest mismatch')
                value = json.loads(blob)
                tail = self.seq - row['seq']
                if not 0 <= tail <= max_tail:
                    raise ValueError('verified recovery tail exceeds bound')
            except (ValueError, zlib.error) as exc:
                failures.append(str(exc))
                continue
            if failures:
                warnings.warn('Invalid latest checkpoint; using verified bounded fallback: '+ '; '.join(failures), RuntimeWarning)
            return {'value':value,'seq':row['seq'],'fallback':bool(failures),'tail_events':tail}
        raise RecoveryError('No valid bounded checkpoint recovery: '+ '; '.join(failures))

    def import_public_file(self, path, *, max_rows=10000):
        """Import a closed prefix, committing cursor and rows together. Read-only source."""
        path=Path(path)
        source='public-file:'+path.name
        stat=path.stat()
        prior=self.db.execute('SELECT * FROM imports WHERE source=?',(source,)).fetchone()
        if prior and (prior['inode']!=stat.st_ino or prior['offset']>stat.st_size):
            raise RecoveryError('Public append-only source was replaced or truncated')
        offset=prior['offset'] if prior else 0
        count=0
        with path.open('rb') as stream, self.db:
            stream.seek(offset)
            for _ in range(max_rows):
                start=stream.tell()
                line=stream.readline()
                if not line or not line.endswith(b'\n'):
                    stream.seek(start)
                    break
                event=json.loads(line)
                event_source='p1:'+str(event.get('run_id','pons-live'))
                self._append(f'{event_source}:{event["seq"]}',event,source=event_source,source_seq=int(event['seq']))
                count+=1
            self.db.execute('INSERT OR REPLACE INTO imports VALUES (?,?,?,?,?)',
                            (source,stat.st_ino,stream.tell(),None,int(time.time())))
        return count

    def ingest_internal(self, event):
        # Internal P1 journals have no sequence. Exact canonical content,
        # including its original timestamp, identifies a durable observation.
        return self.append('internal:'+digest(canonical(event)), event, source='internal')

    def preserve_internal_file(self, path):
        count = 0
        opener = gzip.open if Path(path).suffix == '.gz' else open
        with opener(path, 'rb') as stream, self.db:
            for line in stream:
                if not line.endswith(b'\n'):
                    raise RecoveryError('Cannot rotate a torn internal journal')
                if not line.strip():
                    continue
                event = json.loads(line)
                self._append('internal:'+digest(canonical(event)), event, source='internal', source_seq=None)
                count += 1
        return count

    def health(self):
        return {'schema':SCHEMA_VERSION,'seq':self.seq,'journal_mode':self.db.execute('PRAGMA journal_mode').fetchone()[0],
                'database_bytes':sum(p.stat().st_size for p in [self.path,Path(str(self.path)+'-wal')] if p.exists()),
                'permanent_history':True}
