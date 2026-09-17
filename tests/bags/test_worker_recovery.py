"""Clock recovery preserves canonical rounds, entries and snapshots."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import pytest
from flytrade.bags.watchdog import RoundWatchdog
from flytrade.bags.service import Room
from flytrade.bags.store import Store
from .test_real_paper_bridge import setup
from .test_room import vote

ROOT = Path(__file__).resolve().parents[2]


def test_watchdog_only_tracks_committed_progress():
    now = [0.0]
    ended = threading.Event()
    codes = []
    def terminate(code):
        codes.append(code)
        ended.set()
    dog = RoundWatchdog(timeout=30, interval=.005, clock=lambda: now[0], terminate=terminate)
    dog.start()
    try:
        now[0] = 29
        dog.progress()
        now[0] = 58
        assert not ended.wait(.03)
        now[0] = 60
        assert ended.wait(1)
        assert codes == [70]
    finally:
        dog.close()


@pytest.mark.parametrize('choice', [None, 'HOLD', 'EXIT'])
def test_recovery_finalizes_only_existing_round_once(tmp_path, choice):
    room, bridge, node, now, opened, wallets = setup(tmp_path)
    bridge.event(opened)
    room.tick()
    before = room.view()['bag']
    if choice:
        vote(room, before['id'], wallets[0], choice)
    with room.store.read() as db:
        prefix = [tuple(r) for r in db.execute('SELECT * FROM audit ORDER BY seq')]
    now[0] += 15 * 3600
    recovered = Room(Store(room.store.path), room.config, now=lambda: now[0])
    recovered.tick()
    recovered.tick()
    after = recovered.view()['bag']
    for key in ('id', 'episode_id', 'entry', 'snapshot'):
        assert after[key] == before[key]
    with recovered.store.read() as db:
        audit = [tuple(r) for r in db.execute('SELECT * FROM audit ORDER BY seq')]
        assert audit[:len(prefix)] == prefix
        assert db.execute("SELECT count(*) FROM audit WHERE kind='VOTE_ROUND_CLOSED'").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM audit WHERE kind='EXIT_REQUESTED'").fetchone()[0] == (1 if choice == 'EXIT' else 0)
    if choice == 'EXIT':
        assert after['status'] == 'EXIT_REQUESTED'
        assert after['round']['number'] == 1
    else:
        assert after['status'] == 'OPEN'
        assert after['round']['number'] == 2
        assert after['round']['closes_at'] == now[0] + room.config.round_seconds
        assert after['rounds'][1]['result']['decision'] == ('COMMUNITY_HOLD' if choice else 'NO_QUORUM_HOLD')


def test_blocked_worker_exits_without_waiting_for_sqlite(tmp_path):
    library = os.getenv('FLY_VIEWER_SQLITE_LIBRARY')
    if not library:
        pytest.skip('Set FLY_VIEWER_SQLITE_LIBRARY to the verified runtime')
    code = """
import sys, threading
from functools import partial
from flytrade.product.sqlite_runtime import activate
activate(sys.argv[1])
from flytrade.bags import worker
worker.RoundWatchdog = partial(worker.RoundWatchdog, timeout=.1, interval=.02)
worker.Room.tick = lambda self: threading.Event().wait()
sys.argv = ['worker', '--database', sys.argv[2]]
worker.main()
"""
    env = {k:v for k,v in os.environ.items() if not k.startswith(('PROJECT_TOKEN_', 'BAG_ROOM_', 'ELIGIBILITY_', 'HOLDER_SOURCE', 'FIXTURE_HOLDERS'))}
    result = subprocess.run([sys.executable, '-c', code, library, str(tmp_path/'stuck.sqlite')], cwd=ROOT, env=env, capture_output=True, text=True, timeout=8)
    assert result.returncode == 70, result.stderr
    assert '[bag-watchdog]' in result.stderr and 'worker.py' in result.stderr


def test_bag_launcher_verifies_library_and_rejects_old_runtime(tmp_path, monkeypatch):
    import sqlite3
    from flytrade.bags.worker import main
    monkeypatch.setattr(sqlite3, 'sqlite_version_info', (3, 51, 0))
    with pytest.raises(RuntimeError, match='product/run_bags.py'):
        main()
    library = os.getenv('FLY_VIEWER_SQLITE_LIBRARY')
    if not library:
        pytest.skip('Set FLY_VIEWER_SQLITE_LIBRARY to the verified runtime')
    result = subprocess.run([sys.executable, str(ROOT/'product/run_bags.py'), '--sqlite-library', library, '--verify-runtime'], capture_output=True, text=True, timeout=8)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['sqlite_version'] == '3.51.3'

def test_busy_health_report_does_not_kill_index_retry():
    import sqlite3
    from contextlib import contextmanager
    from flytrade.bags.worker import write_health
    class Busy:
        @contextmanager
        def transaction(self):
            raise sqlite3.OperationalError('database is locked')
            yield
    assert write_health(Busy(),'index_health',{'status':'INDEX_ERROR'}) is False


def test_non_busy_health_failure_is_not_hidden():
    import sqlite3
    from contextlib import contextmanager
    from flytrade.bags.worker import write_health
    class Broken:
        @contextmanager
        def transaction(self):
            raise sqlite3.OperationalError('disk I/O error')
            yield
    with pytest.raises(sqlite3.OperationalError,match='disk I/O'):
        write_health(Broken(),'index_health',{'status':'INDEX_ERROR'})
