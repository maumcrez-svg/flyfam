"""Schema v3, short per-operation connections, atomic writes and immutable audit log."""
from contextlib import contextmanager, closing
from pathlib import Path
import hashlib
import json
import sqlite3
import time


def canonical(x): return json.dumps(x, sort_keys=True, separators=(',', ':'), allow_nan=False)
def digest(x): return hashlib.sha256(canonical(x).encode()).hexdigest()

SCHEMA = '''
PRAGMA journal_mode=WAL;
PRAGMA synchronous=FULL;
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit(seq INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL,
 bag_id TEXT, ts REAL NOT NULL, payload TEXT NOT NULL, previous_hash TEXT NOT NULL, hash TEXT NOT NULL UNIQUE);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit BEGIN SELECT RAISE(ABORT,'immutable audit'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit BEGIN SELECT RAISE(ABORT,'immutable audit'); END;
CREATE TABLE IF NOT EXISTS transfers(block INTEGER NOT NULL, log_index INTEGER NOT NULL, block_hash TEXT NOT NULL,
 tx_hash TEXT NOT NULL, sender TEXT NOT NULL, recipient TEXT NOT NULL, amount TEXT NOT NULL, PRIMARY KEY(block,log_index));
CREATE INDEX IF NOT EXISTS transfers_by_block ON transfers(block);
CREATE TABLE IF NOT EXISTS balances(wallet TEXT PRIMARY KEY, amount TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS bags(id TEXT PRIMARY KEY, number INTEGER NOT NULL UNIQUE, source_event TEXT NOT NULL UNIQUE,
 episode_id TEXT NOT NULL UNIQUE, token TEXT NOT NULL, opened_at INTEGER NOT NULL, entry_block INTEGER NOT NULL,
 status TEXT NOT NULL, entry TEXT NOT NULL, snapshot TEXT, result TEXT, market TEXT, exit_intent TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_bag ON bags((1)) WHERE status != 'CLOSED';
CREATE TABLE IF NOT EXISTS eligible(bag_id TEXT NOT NULL REFERENCES bags(id), wallet TEXT NOT NULL, PRIMARY KEY(bag_id,wallet));
CREATE TABLE IF NOT EXISTS rounds(bag_id TEXT NOT NULL REFERENCES bags(id), number INTEGER NOT NULL, opened_at REAL NOT NULL,
 closes_at REAL NOT NULL, status TEXT NOT NULL, result TEXT, PRIMARY KEY(bag_id,number));
CREATE TABLE IF NOT EXISTS votes(bag_id TEXT NOT NULL, round INTEGER NOT NULL, wallet TEXT NOT NULL,
 choice TEXT NOT NULL CHECK(choice IN ('HOLD','EXIT')), event_seq INTEGER NOT NULL, ts REAL NOT NULL,
 PRIMARY KEY(bag_id,round,wallet), FOREIGN KEY(bag_id,round) REFERENCES rounds(bag_id,number));
CREATE TABLE IF NOT EXISTS challenges(nonce TEXT PRIMARY KEY, wallet TEXT NOT NULL, expires REAL NOT NULL, typed TEXT NOT NULL, used INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS challenge_expiry ON challenges(expires);
CREATE TABLE IF NOT EXISTS chat(id INTEGER PRIMARY KEY AUTOINCREMENT, bag_id TEXT NOT NULL REFERENCES bags(id), wallet TEXT NOT NULL, ts REAL NOT NULL, message TEXT NOT NULL, holder INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS vault(bag_id TEXT PRIMARY KEY REFERENCES bags(id), amount_wei TEXT NOT NULL, source_event TEXT NOT NULL UNIQUE, ts REAL NOT NULL);
CREATE TABLE IF NOT EXISTS limits(key TEXT PRIMARY KEY, start REAL NOT NULL, count INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS entry_snapshots(decision_id TEXT PRIMARY KEY, evidence TEXT NOT NULL, prepared_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS bag_distributions(bag_id TEXT PRIMARY KEY REFERENCES bags(id), evidence TEXT NOT NULL,
 status TEXT NOT NULL, funding_tx TEXT, deadline INTEGER, paid TEXT NOT NULL DEFAULT '0', sweep_tx TEXT);
CREATE TABLE IF NOT EXISTS holder_claims(bag_id TEXT NOT NULL REFERENCES bags(id), wallet TEXT NOT NULL,
 amount TEXT NOT NULL, tx_hash TEXT NOT NULL, block_number INTEGER NOT NULL, PRIMARY KEY(bag_id,wallet));
CREATE TABLE IF NOT EXISTS bag_allocations(bag_id TEXT NOT NULL REFERENCES bags(id), wallet TEXT NOT NULL,
 evidence TEXT NOT NULL, PRIMARY KEY(bag_id,wallet));
CREATE INDEX IF NOT EXISTS allocations_by_wallet ON bag_allocations(wallet,bag_id);
CREATE TABLE IF NOT EXISTS payout_jobs(id TEXT PRIMARY KEY, bag_id TEXT NOT NULL REFERENCES bags(id),
 wallet TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('CLAIM','SWEEP')), amount TEXT NOT NULL,
 status TEXT NOT NULL, created_at REAL NOT NULL, tx_hash TEXT, block_number INTEGER,
 confirmed_at REAL, error TEXT, UNIQUE(bag_id,wallet,kind));
CREATE INDEX IF NOT EXISTS payout_jobs_pending ON payout_jobs(status,created_at);
CREATE TRIGGER IF NOT EXISTS payout_intent_immutable BEFORE UPDATE ON payout_jobs
 WHEN NEW.id!=OLD.id OR NEW.bag_id!=OLD.bag_id OR NEW.wallet!=OLD.wallet OR NEW.kind!=OLD.kind OR NEW.amount!=OLD.amount
 BEGIN SELECT RAISE(ABORT,'immutable payout intent'); END;
PRAGMA user_version=3;
'''

class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db:
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0,1,2,3): raise ValueError('Incompatible Bag Room database')
            db.executescript(SCHEMA)
            # Chat is open to any verified wallet, holder or not, and every
            # message says which it was. Rows written before that column
            # existed were all holders: only holders could post.
            if 'holder' not in {r[1] for r in db.execute('PRAGMA table_info(chat)')}:
                db.execute('ALTER TABLE chat ADD COLUMN holder INTEGER NOT NULL DEFAULT 1')

    def connect(self):
        db = sqlite3.connect(self.path, timeout=3, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA synchronous=FULL')
        return db

    @contextmanager
    def transaction(self):
        db = self.connect()
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally: db.close()

    @contextmanager
    def read(self):
        db = self.connect()
        try:
            db.execute('BEGIN')
            yield db
        finally: db.close()

    @staticmethod
    def get(db, key, default=None):
        row = db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    @staticmethod
    def put(db, key, value):
        db.execute('INSERT INTO meta VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, canonical(value)))

    @staticmethod
    def emit(db, kind, bag_id, payload, now=None):
        ts = time.time() if now is None else now
        row = db.execute('SELECT hash FROM audit ORDER BY seq DESC LIMIT 1').fetchone()
        previous = row[0] if row else '0'*64
        hashed = digest([previous,kind,bag_id,ts,payload])
        cur = db.execute('INSERT INTO audit(kind,bag_id,ts,payload,previous_hash,hash) VALUES (?,?,?,?,?,?)',
                         (kind,bag_id,ts,canonical(payload),previous,hashed))
        return cur.lastrowid

    @staticmethod
    def rate(db, key, now, count=30, seconds=60):
        row = db.execute('SELECT start,count FROM limits WHERE key=?', (key,)).fetchone()
        start, used = (row[0],row[1]) if row and now-row[0] < seconds else (now,0)
        if used >= count: raise ValueError('Rate limit; wait before retrying')
        db.execute('INSERT OR REPLACE INTO limits VALUES (?,?,?)', (key,start,used+1))
        db.execute('DELETE FROM limits WHERE start < ?', (now-3600,))
