"""Explicitly activated, separately keyed native payout worker; no trading executor."""
import argparse
import fcntl
import os
from pathlib import Path
import time
from .config import Config
from .store import Store
from .service import Room
from .live_rpc import LiveRpc,Limits,Sender,keystore_signer
from .payout import PayoutConfig,PayoutWorker


def main():
    p=argparse.ArgumentParser();p.add_argument('--database',required=True);p.add_argument('--private-database',required=True)
    p.add_argument('--rpc',default='http://127.0.0.1:8645');p.add_argument('--once',action='store_true');args=p.parse_args()
    if os.getenv('PAYOUT_EXECUTION_ENABLED')!='YES' or os.getenv('CLAIMS_MODE')!='PAYOUT_WALLET':raise ValueError('Explicit payout activation required')
    config=PayoutConfig.environment();public=Path(args.database).resolve();private=Path(args.private_database).resolve()
    if public==private:raise ValueError('Payout signed outbox must remain private and separate')
    private.parent.mkdir(parents=True,exist_ok=True)
    lock=open(str(private)+'.lock','a');os.chmod(lock.name,0o600);fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    password=Path(os.environ['PAYOUT_KEYSTORE_PASSWORD_FILE'])
    if password.stat().st_mode&0o077:raise ValueError('Payout password file must be owner-readable only')
    signer=keystore_signer(os.environ['PAYOUT_KEYSTORE_FILE'],password.read_text().rstrip('\r\n'))
    limits=Limits(config.wallet,int(os.environ['PAYOUT_MAX_TRANSFER_WEI']),int(os.environ['PAYOUT_MAX_TOTAL_OUTGOING_WEI']),
        int(os.environ['PAYOUT_MAX_GAS_PRICE_WEI']),int(os.environ['PAYOUT_MAX_GAS_PER_TX']),0,role='PAYOUT',production_enabled=True)
    room=Room(Store(public),Config.environment());sender=Sender(Store(private),LiveRpc(args.rpc),limits,signer)
    worker=PayoutWorker(room,sender,config)
    while True:
        try:worker.step()
        except Exception as exc:
            # Never output endpoint credentials, keystore contents or signed bytes.
            with room.store.transaction() as db:Store.put(db,'payout_worker_health',{'status':'ERROR','kind':type(exc).__name__,'ts':time.time()})
            print('Payout paused:',type(exc).__name__,flush=True)
            if args.once:raise
        else:
            with room.store.transaction() as db:Store.put(db,'payout_worker_health',{'status':'RUNNING','ts':time.time()})
        if args.once:break
        time.sleep(2)

if __name__=='__main__':main()
