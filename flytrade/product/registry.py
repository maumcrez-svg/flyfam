"""Persistent neural IDs with bounded caches; retention cannot renumber RNG seeds."""
from collections import OrderedDict
from pathlib import Path
import sqlite3


class PersistentUniverse:
    def __init__(self, path, *, cache_size=2048):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_size = max(0, int(cache_size))
        self._cache = OrderedDict()
        self.db = sqlite3.connect(self.path)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS symbols '
                        '(symbol TEXT PRIMARY KEY, stable_id INTEGER UNIQUE NOT NULL)')
        self.db.commit()

    def _remember(self, symbol, stable_id):
        if self.cache_size:
            self._cache[symbol] = stable_id
            self._cache.move_to_end(symbol)
            while len(self._cache) > self.cache_size:
                self._cache.popitem(last=False)
        return stable_id

    def stable_id(self, symbol):
        if symbol in self._cache:
            self._cache.move_to_end(symbol)
            return self._cache[symbol]
        row = self.db.execute('SELECT stable_id FROM symbols WHERE symbol=?', (symbol,)).fetchone()
        if row is None:
            raise KeyError(symbol)
        return self._remember(symbol, row[0])

    def register(self, symbol):
        try:
            return self.stable_id(symbol)
        except KeyError:
            pass
        with self.db:
            stable_id = self.db.execute('SELECT coalesce(max(stable_id)+1,0) FROM symbols').fetchone()[0]
            self.db.execute('INSERT INTO symbols VALUES (?,?)', (symbol, stable_id))
        return self._remember(symbol, stable_id)

    def import_universe(self, universe):
        with self.db:
            for symbol, stable_id in universe.items():
                row = self.db.execute('SELECT stable_id FROM symbols WHERE symbol=?', (symbol,)).fetchone()
                if row and row[0] != stable_id:
                    raise ValueError('Stable neural identity conflicts with registry')
                if row is None:
                    self.db.execute('INSERT INTO symbols VALUES (?,?)', (symbol, stable_id))

    def symbol(self, stable_id):
        row = self.db.execute('SELECT symbol FROM symbols WHERE stable_id=?', (stable_id,)).fetchone()
        if row is None:
            raise KeyError(stable_id)
        return row[0]

    def rename(self, old, new):
        if new in self:
            raise ValueError(f'{new} is already registered')
        self.stable_id(old)
        with self.db:
            self.db.execute('UPDATE symbols SET symbol=? WHERE symbol=?', (new, old))
        self._cache.pop(old, None)

    def __contains__(self, symbol):
        try:
            self.stable_id(symbol)
            return True
        except KeyError:
            return False

    def __len__(self):
        return self.db.execute('SELECT count(*) FROM symbols').fetchone()[0]

    def items(self):
        return iter(self.db.execute('SELECT symbol,stable_id FROM symbols ORDER BY stable_id'))

    def close(self):
        self.db.close()


class PersistentDiscoveries:
    """Exact lifetime census without retaining all discovered token strings."""
    def __init__(self, registry):
        self.db = registry.db
        self.db.execute('CREATE TABLE IF NOT EXISTS discoveries (token TEXT PRIMARY KEY)')
        self.db.commit()

    def add(self, token):
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO discoveries VALUES (?)', (token,))

    def import_tokens(self, tokens):
        with self.db:
            self.db.executemany('INSERT OR IGNORE INTO discoveries VALUES (?)', ((t,) for t in tokens))

    def __len__(self):
        return self.db.execute('SELECT count(*) FROM discoveries').fetchone()[0]

    def __contains__(self, token):
        return self.db.execute('SELECT 1 FROM discoveries WHERE token=?',(token,)).fetchone() is not None


class PersistentSettlements:
    def __init__(self, registry, values=()):
        self.db = registry.db
        self.db.execute('CREATE TABLE IF NOT EXISTS settlements (episode INTEGER PRIMARY KEY)')
        self.db.commit()
        self.__ior__(values)

    def __ior__(self, values):
        with self.db:
            self.db.executemany('INSERT OR IGNORE INTO settlements VALUES (?)', ((int(v),) for v in values))
        return self

    def add(self, episode):
        self.__ior__([episode])

    def __len__(self):
        return self.db.execute('SELECT count(*) FROM settlements').fetchone()[0]

    def __contains__(self, episode):
        return self.db.execute('SELECT 1 FROM settlements WHERE episode=?',(int(episode),)).fetchone() is not None
