"""Independent holder indexing / round clock. Never imports or instantiates a brain."""
import argparse
import time
import threading
import faulthandler
import sqlite3
import signal
from .config import Config
from .store import Store
from .service import Room
from .indexer import Rpc
from .holder_source import build_source
from .watchdog import RoundWatchdog


def write_health(store,key,value):
    """A busy DB cannot kill the retry loop while reporting its own error."""
    try:
        with store.transaction() as db:Store.put(db,key,value)
        return True
    except sqlite3.OperationalError as exc:
        code=getattr(exc,'sqlite_errorcode',0)
        if (code & 255) not in (sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED) and 'locked' not in str(exc).lower():
            raise
        print('Bag health deferred: database busy; next iteration will retry',flush=True)
        return False


def run_once(room):
    if room.indexer:
        room.tick()
        with room.store.read() as db:
            pending=db.execute("SELECT 1 FROM bags WHERE status='SNAPSHOT_PENDING'").fetchone()
        if not pending:room.indexer.sync(max_chunks=2)
    else:room.tick()


def main():
    from flytrade.product.sqlite_runtime import require_fixed_runtime
    require_fixed_runtime('Bag Room', 'product/run_bags.py')
    faulthandler.enable()
    if hasattr(signal, 'SIGUSR1'):
        faulthandler.register(signal.SIGUSR1, all_threads=True)
    p=argparse.ArgumentParser()
    p.add_argument('--database',required=True)
    p.add_argument('--rpc',default='http://127.0.0.1:8645')
    args=p.parse_args()
    config=Config.environment()
    store=Store(args.database)
    room=Room(store,config,indexer=build_source(store,config,Rpc(args.rpc)))
    print('Bag Room: '+('REAL PONS PAPER / TEST HOLDERS' if config.integration else 'INDEXING PROJECT TOKEN' if config.configured else 'TOKEN_NOT_CONFIGURED'),flush=True)
    stop=threading.Event()
    def indexing():
        while not stop.is_set():
            try:
                if room.indexer:
                    with store.read() as db:
                        pending=db.execute("SELECT id FROM bags WHERE status='SNAPSHOT_PENDING'").fetchone()
                    if pending:room.lock_snapshot(pending[0])
                    else:room.indexer.sync(max_chunks=1)
                    with store.transaction() as db:Store.put(db,'index_health',{'ts':time.time(),'status':'READY'})
            except Exception as exc:
                print('Holder index paused:',type(exc).__name__,str(exc)[:180],flush=True)
                write_health(store,'index_health',{'ts':time.time(),'status':'INDEX_ERROR'})
            stop.wait(2)
    threading.Thread(target=indexing,name="bag-holder-index",daemon=True).start()
    # Index catch-up/RPC latency never blocks the independent round clock.
    rounds=Room(store,config)
    watchdog=RoundWatchdog()
    watchdog.start()
    try:
        while not stop.is_set():
            try:
                rounds.tick()
                watchdog.progress()
            except Exception as exc:
                print('Round clock paused:',type(exc).__name__,flush=True)
                write_health(store,'room_heartbeat',{'ts':time.time(),'status':'ROUND_ERROR'})
            stop.wait(.5)
    except KeyboardInterrupt:stop.set()
    finally:
        stop.set()
        watchdog.close()

if __name__=='__main__':main()
