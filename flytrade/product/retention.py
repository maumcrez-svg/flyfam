"""Product-only active history checkpoints; lossless gzip evidence archives.

Single writer, invoked only between completed ticks. A manifest publishes all
chain files together. Before publication a crash uses the previous generation;
after publication it uses the complete new generation. Archives are never
expired automatically. Scientific ChainStore and EventLog remain unchanged.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
import time
import uuid
import warnings
from pathlib import Path

from ..pons.budget import _atomic_write_json
from ..pons.storage import ChainStore, _append_jsonl, _read_jsonl
from .registry import PersistentUniverse, PersistentDiscoveries, PersistentSettlements
from .collections import DiskSequence
from .history import RecoveryError


def _sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def archive(path: Path, destination: Path) -> None:
    """Durably preserve exact source bytes before any active-file replacement."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_suffix(destination.suffix + '.tmp')
    with open(path, 'rb') as source, open(temp, 'wb') as output:
        with gzip.GzipFile(fileobj=output, mode='wb', mtime=0) as zipped:
            shutil.copyfileobj(source, zipped, length=1024 * 1024)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temp, destination)
    _sync_dir(destination.parent)


def file_digest(path, size=None):
    sha = hashlib.sha256()
    remaining = size
    with Path(path).open('rb') as source:
        while remaining is None or remaining > 0:
            chunk = source.read(1024 * 1024 if remaining is None else min(1024 * 1024, remaining))
            if not chunk:
                if remaining:
                    raise RecoveryError('Checkpoint prefix was truncated')
                break
            sha.update(chunk)
            if remaining is not None:
                remaining -= len(chunk)
    return sha.hexdigest()


class ProductChainStore(ChainStore):
    """Same collector interface, with a compact active generation on resume."""

    def __init__(self, directory):
        self.root = Path(directory)
        self.manifest = self.root / 'active.json'
        active = self.root
        self.launches_pruned = 0
        self.compacted_at = None
        if self.manifest.exists():
            meta = json.loads(self.manifest.read_text())
            if meta.get('version') not in (1, 2):
                raise RecoveryError('Unsupported chain checkpoint version')
            name = meta['generation']
            self.launches_pruned = int(meta.get('launches_pruned', 0))
            self.compacted_at = int(meta['cutoff'])
            if not name.startswith('generation-') or Path(name).name != name:
                raise ValueError('invalid chain generation')
            active = self.root / name
            if not active.is_dir():
                raise ValueError('missing active chain generation')
            if meta.get('version') == 2:
                active = self._verify_or_recover(active, meta)
        super().__init__(active)

    def _verify_or_recover(self, active, meta):
        files = meta['checkpoint_files']
        if set(files) != {'raw.jsonl', 'events.jsonl', 'headers.jsonl', 'cursor.json'}:
            raise RecoveryError('Invalid checkpoint file manifest')
        failures = []
        # Cursor is an atomic replace, unlike the other append-only files.
        for name, proof in files.items():
            if name == 'cursor.json':
                continue
            try:
                if file_digest(active / name, proof['bytes']) != proof['sha256']:
                    failures.append(name)
            except (OSError, RecoveryError):
                failures.append(name)
        try:
            cursor = json.loads((active / 'cursor.json').read_text())
            if not isinstance(cursor, dict) or (meta.get('cursor') is not None and cursor.get('block_number') is None):
                failures.append('cursor.json')
        except (OSError, ValueError):
            failures.append('cursor.json')
        if not failures:
            return active
        tail = sum(max(0, (active / name).stat().st_size - proof['bytes'])
                   for name, proof in files.items() if (active / name).exists())
        if tail > int(meta['max_recovery_tail_bytes']):
            raise RecoveryError('Corrupt chain checkpoint exceeds bounded recovery tail')
        checkpoint = meta['checkpoint']
        if not checkpoint.startswith('generation-') or Path(checkpoint).name != checkpoint:
            raise RecoveryError('Invalid checkpoint identity')
        target = self.root / ('generation-' + uuid.uuid4().hex)
        target.mkdir()
        for name, proof in files.items():
            source = self.root / 'checkpoints' / checkpoint / (name + '.gz')
            try:
                with gzip.open(source, 'rb') as zipped, (target / name).open('wb') as output:
                    # A corrupt compressed file must not expand without bound.
                    remaining = int(proof['bytes'])
                    while remaining:
                        chunk = zipped.read(min(1024 * 1024, remaining))
                        if not chunk:
                            raise RecoveryError('Truncated backup checkpoint')
                        output.write(chunk)
                        remaining -= len(chunk)
                    if zipped.read(1):
                        raise RecoveryError('Oversized backup checkpoint')
                    output.flush()
                    os.fsync(output.fileno())
                if file_digest(target / name) != proof['sha256']:
                    raise RecoveryError('Backup checkpoint digest mismatch')
            except (OSError, EOFError) as exc:
                raise RecoveryError('No verified chain checkpoint recovery') from exc
        _sync_dir(target)
        warnings.warn('Corrupt chain checkpoint '+','.join(failures)+
                      '; restoring verified snapshot and bounded source-cursor backfill', RuntimeWarning)
        _atomic_write_json(self.manifest, {**meta, 'generation':target.name,
                                          'recovered_from':active.name})
        _sync_dir(self.root)
        return target

    def prune_checkpoints(self):
        active_meta = json.loads(self.manifest.read_text())
        entries = []
        for path in (self.root/'checkpoints').glob('generation-*'):
            meta = path/'checkpoint.json'
            if meta.exists():
                record = json.loads(meta.read_text())
                if record['generation'] != path.name:
                    raise RecoveryError('Checkpoint identity mismatch')
                entries.append((int(record['cutoff']), path, record))
        entries.sort(key=lambda row:(row[0], row[1].name), reverse=True)
        keep = {path.name for _,path,_ in entries[:2]} | {active_meta['checkpoint']}
        for _,path,record in entries:
            if path.name in keep:
                continue
            expected = {name+'.gz' for name in record['files']} | {'checkpoint.json'}
            if not {p.name for p in path.iterdir()} <= expected:
                raise RecoveryError('Unregistered checkpoint files')
            for name in expected-{'checkpoint.json'}:
                (path/name).unlink(missing_ok=True)
            (path/'checkpoint.json').unlink()
            path.rmdir()
        _sync_dir(self.root/'checkpoints')

    def compact(self, *, cutoff: int, keep_seconds: int, pinned_curves=(),
                fault=None) -> dict:
        """Keep full recent/pinned curve histories plus the recent event range.

        The oldest retained event/header and the original confirmed cursor
        anchor remain available for entry/exit confirmation. A long-lived
        position intentionally prevents strict constant-size retention.
        """
        edge = int(cutoff) - int(keep_seconds)
        curves = {str(c).lower() for c in pinned_curves}
        for e in self.events:
            if (e.get('event') == 'TokenLaunched'
                    and int(e['block_timestamp']) >= edge):
                curves.add(str(e.get('curve') or '').lower())
        retained = [e for e in self.events
                    if int(e['block_timestamp']) >= edge
                    or str(e.get('curve') or e.get('address') or '').lower() in curves]
        ids = {e['log_id'] for e in retained}
        launches_pruned = self.launches_pruned + sum(
            e.get('event') == 'TokenLaunched' and e.get('source') == 'factory'
            and e['log_id'] not in ids and e['log_id'] not in self.orphaned
            for e in self.events)
        orphaned = self.orphaned & ids
        numbers = [int(e['block_number']) for e in retained]
        cursor = self.cursor or {}
        numbers.extend(int(cursor[k]) for k in ('block_number', 'confirmed_block')
                       if cursor.get(k) is not None)
        floor = min(numbers) if numbers else 0
        anchor = self.header_at_or_below(floor)
        if anchor:
            floor = int(anchor['number'])
        headers = [h for h in self.headers.values() if int(h['number']) >= floor]
        generation = 'generation-' + uuid.uuid4().hex
        target = self.root / generation
        target.mkdir(parents=True)
        new = ChainStore(target)
        _append_jsonl(new.events_path, retained)
        if orphaned:
            _append_jsonl(new.events_path, [{'kind': 'ORPHANED',
                'log_ids': sorted(orphaned), 'at_block': cursor.get('block_number'),
                'reason': 'retained orphan markers'}])
        # Stream raw evidence: migration must not double a multi-GB file in RAM.
        with open(new.raw_path, 'w') as output:
            if self.raw_path.exists():
                with open(self.raw_path) as source:
                    for line in source:
                        if line.endswith('\n') and line.strip():
                            record = json.loads(line)
                            if record['log_id'] in ids:
                                output.write(line)
            output.flush()
            os.fsync(output.fileno())
        _append_jsonl(new.headers_path, headers)
        if self.cursor is not None:
            _atomic_write_json(new.cursor_path, self.cursor)
        _sync_dir(target)
        proofs = {}
        backup = self.root / 'checkpoints' / generation
        for path in (new.raw_path, new.events_path, new.headers_path, new.cursor_path):
            if not path.exists():
                # Empty stores have an explicit empty cursor, not a missing file.
                if path == new.cursor_path:
                    _atomic_write_json(path, {})
                else:
                    path.touch()
            proofs[path.name] = {'bytes': path.stat().st_size, 'sha256':file_digest(path)}
            archive(path, backup / (path.name + '.gz'))
        _atomic_write_json(backup / 'checkpoint.json', {
            'generation':generation, 'cutoff':int(cutoff), 'files':proofs})
        _sync_dir(backup.parent)
        # Full old segments intentionally overlap retained evidence. This
        # makes each archive independently inspectable without a custom codec.
        archive_dir = self.root / 'archive' / generation
        old_paths = (self.raw_path, self.events_path, self.headers_path, self.cursor_path)
        for path in old_paths:
            if path.exists():
                archive(path, archive_dir / (path.name + '.gz'))
        if archive_dir.exists():
            _sync_dir(archive_dir.parent)
        _atomic_write_json(archive_dir / 'segment.json', {
            'version':1, 'id':generation, 'closed_at':int(cutoff),
            'range_start_ts':min((int(e['block_timestamp']) for e in self.events), default=None),
            'range_end_ts':max((int(e['block_timestamp']) for e in self.events), default=None),
            'files':{p.name+'.gz':file_digest(archive_dir/(p.name+'.gz'))
                     for p in old_paths if p.exists()}})
        _sync_dir(self.root)
        if fault == 'before_publish':
            raise RuntimeError(fault)
        _atomic_write_json(self.manifest, {'version': 2, 'generation': generation,
            'checkpoint': generation, 'checkpoint_files': proofs,
            'max_recovery_tail_bytes': 256 * 1024 * 1024,
            'range_start_ts': min((int(e['block_timestamp']) for e in retained), default=None),
            'range_end_ts': max((int(e['block_timestamp']) for e in retained), default=None),
            'cutoff': int(cutoff), 'keep_seconds': int(keep_seconds),
            'events': len(retained), 'cursor': self.cursor,
            'launches_pruned': launches_pruned})
        if fault == 'after_publish':
            raise RuntimeError(fault)
        self.launches_pruned = launches_pruned
        self.compacted_at = int(cutoff)
        before = len(self.events)
        old_directory = self.directory
        # Swap the existing instance; the collector holds its identity.
        loaded = new.load()
        for name in ('directory', 'raw_path', 'events_path', 'headers_path',
                     'cursor_path', 'seen', 'orphaned', 'events', 'headers',
                     'headers_by_number', 'cursor'):
            setattr(self, name, getattr(loaded, name))
        for path in old_paths:
            path.unlink(missing_ok=True)
        if old_directory != self.root:
            old_directory.rmdir()
        _sync_dir(self.root)
        self.prune_checkpoints()
        return {'events_before': before, 'events_after': len(self.events),
                'generation': generation, 'archive': str(archive_dir)}


def rotate_journal(journal, *, protected_episodes=()) -> dict:
    """Archive diagnostic volume, retaining every executed episode in hot log.

    Recovery still sees all outcomes/learning and all decisions/executions for
    actual positions. Episode history therefore grows with trades, not ticks.
    The archive contains every byte, including census and unexecuted picks.
    """
    path = journal.log.path
    if not path.exists():
        return {'before': 0, 'after': 0}
    history = getattr(journal, "product_history", None)
    if history is not None:
        history.preserve_internal_file(path)
    rows = _read_jsonl(path)
    protected = {int(e) for e in protected_episodes}
    protected.update(int(r['episode_id']) for r in rows
                     if r.get('kind') in ('EXECUTION', 'OUTCOME', 'LEARNING')
                     and r.get('episode_id') is not None)
    keep = [r for r in rows if r.get('kind') not in ('DISCOVERY', 'ROUND', 'DECISION')
            or (r.get('kind') == 'DECISION' and r.get('episode_id') in protected)
            or (r.get('kind') == 'ROUND' and any(c.get('episode_id') in protected
                for c in r.get('candidates', [])))]
    if history is not None and hasattr(journal, 'last_settled_episode'):
        settled = int(journal.last_settled_episode)
        # Frozen recovery is anchored by the brain checkpoint's settled ID.
        # All older records remain in permanent history, not the hot journal.
        recovery_ids = {int(row['episode_id']) for row in rows
                        if row.get('kind') in ('EXECUTION','OUTCOME','LEARNING')
                        and row.get('episode_id') is not None
                        and int(row['episode_id']) > settled}
        recovery_ids.update(int(e) for e in protected_episodes)
        recovery_ids.add(settled)
        def needed(row):
            ep = row.get('episode_id')
            if ep is not None and int(ep) in recovery_ids:
                return True
            return row.get('kind') == 'ROUND' and any(
                int(c.get('episode_id', -1)) in recovery_ids
                for c in row.get('candidates', []))
        # Do not treat every past executed episode as currently protected.
        protected = {int(e) for e in protected_episodes}
        tail_ids = {id(row) for row in rows[-100:]}
        keep = [row for row in rows if needed(row) or id(row) in tail_ids]
    archive(path, path.parent / 'archive' / (uuid.uuid4().hex + '.jsonl.gz'))
    temp = path.with_suffix('.compact.tmp')
    temp.unlink(missing_ok=True)
    _append_jsonl(temp, keep)
    if not temp.exists():
        with open(temp, 'wb') as out:
            out.flush()
            os.fsync(out.fileno())
    os.replace(temp, path)
    _sync_dir(path.parent)
    return {'before': len(rows), 'after': len(keep)}


def expire_raw_archives(store, history, *, cutoff, keep_seconds=172800):
    """Expiry requires the product projector's durable follow-up watermark.

    A timestamp alone cannot authorize deletion: the projection records both
    its canonical sequence and the raw horizon it has fully consumed.
    """
    watermark = history.state('retention_watermark') if history is not None else None
    if watermark is None:
        return {'status':'AWAITING_PRODUCT_WATERMARK', 'expired':0}
    proof = watermark['value']
    if int(proof['canonical_seq']) > history.seq:
        raise RecoveryError('Retention watermark is ahead of permanent evidence')
    edge = min(int(cutoff)-int(keep_seconds), int(proof['raw_consumed_through_ts']))
    expired = 0
    for segment in sorted((store.root/'archive').glob('generation-*')):
        meta_path = segment/'segment.json'
        if not meta_path.exists():
            if history.state('expired:'+segment.name) is not None and not any(segment.iterdir()):
                segment.rmdir()
            continue  # Legacy evidence requires explicit migration, never guess.
        meta = json.loads(meta_path.read_text())
        if int(meta['closed_at']) >= edge:
            continue
        if meta['id'] != segment.name:
            raise RecoveryError('Archive identity mismatch')
        expected = set(meta['files']) | {'segment.json'}
        existing = {p.name for p in segment.iterdir()}
        resuming = history.state('expired:'+segment.name) is not None
        if not existing <= expected or (existing != expected and not resuming):
            raise RecoveryError('Archive contains missing or unregistered files')
        for name, sha in meta['files'].items():
            if resuming and name not in existing:
                continue
            if Path(name).name != name or file_digest(segment/name) != sha:
                raise RecoveryError('Archive verification failed before expiry')
        # Record expiry proof durably before unlinking already preserved raw data.
        history.save_state('expired:'+segment.name, {'segment':meta,
            'watermark':proof,'expired_at':int(cutoff)})
        for name in meta['files']:
            (segment/name).unlink(missing_ok=True)
        meta_path.unlink()
        segment.rmdir()
        expired += 1
    if expired:
        _sync_dir(store.root/'archive')
    return {'status':'BOUNDED', 'expired':expired,'raw_expiry_edge_ts':edge,
            'keep_seconds':int(keep_seconds)}


def rotate_product_journals(feed, journal, history, *, now=None, keep_seconds=172800):
    """Closed daily public files and expired audit archives have a DB successor."""
    if history is None:
        return
    now = time.time() if now is None else float(now)
    edge = now-int(keep_seconds)
    for path in sorted(feed.dir.glob('events-????-??-??.jsonl')):
        # A whole UTC day must be outside retention; the current file is never touched.
        import calendar
        day = calendar.timegm(time.strptime(path.name[7:17], '%Y-%m-%d'))
        if day+86400 >= edge:
            continue
        while history.import_public_file(path):
            pass
        archive(path, feed.dir/'archive'/(path.name+'.gz'))
        path.unlink()
        _sync_dir(feed.dir)
    for path in (journal.log.path.parent/'archive').glob('*.jsonl.gz'):
        if path.stat().st_mtime >= edge:
            continue
        history.preserve_internal_file(path)
        path.unlink()
        _sync_dir(path.parent)
    for path in (feed.dir/'archive').glob('events-????-??-??.jsonl.gz'):
        if path.stat().st_mtime >= edge:
            continue
        with gzip.open(path, 'rb') as source, history.db:
            for line in source:
                if not line.endswith(b'\n'):
                    raise RecoveryError('Torn archived public journal')
                event = json.loads(line)
                origin = 'p1:'+str(event.get('run_id','pons-live'))
                history._append(f'{origin}:{event["seq"]}',event,
                    source=origin,source_seq=int(event['seq']))
        path.unlink()
        _sync_dir(path.parent)


class Maintenance:
    """Hourly housekeeping after HEARTBEAT/state durability, no RPC calls."""

    def __init__(self, *, interval_seconds=3600):
        self.interval_seconds = int(interval_seconds)
        self.last = None

    def tick(self, loop, cutoff):
        if self.last is not None and cutoff - self.last < self.interval_seconds:
            return
        if not getattr(loop, "tick_completed", False):
            return
        driver = loop.driver
        collector = driver.collector
        store = collector.store
        if not isinstance(store, ProductChainStore):
            return
        if store.compacted_at is not None and cutoff - store.compacted_at < self.interval_seconds:
            return
        # A collector append not yet routed cannot be removed or renumbered.
        if driver._index != len(store.events):
            return
        guard = getattr(driver, 'disk_guard', None)
        if guard is not None:
            # New hot generation, immutable checkpoint and archived evidence
            # coexist until publication. Retain the normal safety floor too.
            hot_bytes = sum(path.stat().st_size for path in
                (store.raw_path,store.events_path,store.headers_path,store.cursor_path)
                if path.exists())
            guard.reserve_working_space(4 * hot_bytes)
            if guard.stop_reason() is not None:
                self.retention_state = {'status':'INSUFFICIENT_COMPACTION_SPACE',
                    'required_working_bytes':4 * hot_bytes}
                return
        # Persist RNG identities before removing any launch evidence.
        if not isinstance(loop.universe, PersistentUniverse):
            registry = PersistentUniverse(store.root / "neural-identities.sqlite")
            registry.import_universe(loop.universe)
            loop.universe = registry
        if not isinstance(loop.discovered, PersistentDiscoveries):
            discoveries = PersistentDiscoveries(loop.universe)
            discoveries.import_tokens(loop.discovered)
            loop.discovered = discoveries
        if not isinstance(loop.credit.settled, PersistentSettlements):
            loop.credit.settled = PersistentSettlements(loop.universe, loop.credit.settled)
        history = getattr(loop.journal, 'product_history', None)
        if history is not None:
            for owner, name, codec in ((loop,'episodes','dict'),
                    (loop.x,'outcomes','outcome'),(loop.x,'rejections','rejection'),
                    (loop.x,'unresolved','dict')):
                values = getattr(owner,name)
                if not isinstance(values, DiskSequence):
                    setattr(owner,name,DiskSequence(history,values,codec=codec))
        pinned = set(collector.held)
        pinned.update(curve for curve, deadline in
            (getattr(collector, "followup_until", None) or {}).items() if deadline >= cutoff)
        pinned.update(t.curve for t in loop.tapes.values())
        pinned.update(driver._held)
        result = store.compact(cutoff=cutoff,
            keep_seconds=loop.track_seconds * 2, pinned_curves=pinned)
        if guard is not None:
            guard.reserve_working_space(0)
        driver._index = len(store.events)
        driver._clock = None
        driver._clock_n = -1
        retained_curves = {str(e.get('curve') or '').lower() for e in store.events
                           if e.get('event') == 'TokenLaunched'} | pinned
        for curve in list(collector.launches):
            if curve not in retained_curves:
                collector.launches.pop(curve, None)
                collector.normalise.markets.pop(curve, None)
                collector.completed.discard(curve)
        tokens = {r.get('token') for r in collector.launches.values()}
        for token in list(driver.initial_states):
            if token not in tokens and token not in loop.tapes:
                driver.initial_states.pop(token, None)
        active_ids = {loop.universe.stable_id(token) for token in loop.tapes}
        for stable_id in list(loop.admission.last_presented):
            if stable_id not in active_ids:
                loop.admission.last_presented.pop(stable_id, None)
        for key in list(collector.state_cache):
            if str(key).split(':', 1)[0] not in retained_curves:
                collector.state_cache.pop(key, None)
        protected = [loop.x.account.position.episode_id] if loop.x.account.position else []
        if loop.pending:
            protected.append(int(loop.pending['episode_id']))
        rotate_journal(loop.journal, protected_episodes=protected)
        rotate_product_journals(loop.feed, loop.journal,
            getattr(loop.journal, "product_history", None))
        self.retention_state = expire_raw_archives(store,
            getattr(loop.journal, "product_history", None), cutoff=cutoff)
        self.last = int(cutoff)
        driver.log(f"[maintenance] chain events {result['events_before']} -> "
                   f"{result['events_after']}; archived evidence, cursor unchanged")
