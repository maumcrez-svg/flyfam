"""Disk-backed diagnostic histories; no second accounting engine."""
from dataclasses import asdict
import uuid
import zlib
from .history import canonical, unpack
from .. import execution as X


class DiskSequence:
    def __init__(self, history, values=(), *, codec='dict'):
        self.db = history.db
        self.key = uuid.uuid4().hex
        self.codec = codec
        self.db.execute('CREATE TABLE IF NOT EXISTS collections '
            '(collection TEXT, idx INTEGER, payload BLOB NOT NULL, PRIMARY KEY(collection,idx))')
        self.db.commit()
        with self.db:
            for index, value in enumerate(values):
                self.db.execute('INSERT INTO collections VALUES (?,?,?)',
                    (self.key,index,self._pack(value)))

    def _pack(self, value):
        return zlib.compress(canonical(value if self.codec=='dict' else asdict(value)))

    def _unpack(self, blob):
        value = unpack(blob)
        if self.codec=='outcome':
            for name in ('entry','exit'):
                value[name]['side'] = X.Side(value[name]['side'])
                value[name] = X.Fill(**value[name])
            value['close_reason'] = X.CloseReason(value['close_reason'])
            return X.OutcomeRecord(**value)
        if self.codec=='rejection':
            value['reason'] = X.RejectReason(value['reason'])
            return X.Rejection(**value)
        return value

    def __len__(self):
        return self.db.execute('SELECT count(*) FROM collections WHERE collection=?',(self.key,)).fetchone()[0]

    def append(self, value):
        with self.db:
            self.db.execute('INSERT INTO collections VALUES (?,?,?)',(self.key,len(self),self._pack(value)))

    def __iter__(self):
        for row in self.db.execute('SELECT payload FROM collections WHERE collection=? ORDER BY idx',(self.key,)):
            yield self._unpack(row[0])

    def __getitem__(self, index):
        size = len(self)
        if isinstance(index,slice):
            start,stop,step = index.indices(size)
            return [self[i] for i in range(start,stop,step)]
        if index < 0:
            index += size
        if not 0 <= index < size:
            raise IndexError(index)
        row = self.db.execute('SELECT payload FROM collections WHERE collection=? AND idx=?',(self.key,index)).fetchone()
        return self._unpack(row[0])

    def recent(self, limit=100):
        return self[max(0,len(self)-int(limit)):]
