"""Explicit production configuration. Imports do not load a key or activate a worker."""
import os
import json
from pathlib import Path
from .config import address
from .indexer import Indexer
from .live_rpc import LiveRpc,Limits,Sender,keystore_signer
from .live_pons import PonsLive
from .live_v4 import V4LiveExit
from .store import Store


def bind(execution,room,bridge,*,url,paths,quoter):
    limits=Limits.environment()
    if os.environ.get('BAG_ROOM_MODE')!='PRODUCTION' or os.environ.get('TRADING_MODE')!='LIVE':raise ValueError('Explicit BAG_ROOM_MODE=PRODUCTION and TRADING_MODE=LIVE required')
    if os.environ.get('CLAIMS_MODE')!='PAYOUT_WALLET':raise ValueError('LIVE holder profit requires CLAIMS_MODE=PAYOUT_WALLET')
    if os.environ.get('LEARNING_MODE','FROZEN')!='FROZEN':raise ValueError('LIVE public brain must remain frozen')
    if room.config.fixture or room.config.integration:raise ValueError('Production worker cannot use fixture holders')
    if quoter is None:raise ValueError('LIVE needs the verified V4 route as well as curve execution')
    if Path(paths['dir']).name=='live':raise ValueError('Use a separate LIVE execution data directory; never adopt PAPER inventory')
    password_file=Path(os.environ['LIVE_KEYSTORE_PASSWORD_FILE'])
    if password_file.stat().st_mode&0o077:raise ValueError('Keystore password file must be owner-readable only')
    signer=keystore_signer(os.environ['LIVE_KEYSTORE_FILE'],password_file.read_text().rstrip('\r\n'))
    rpc=LiveRpc(url)
    room.indexer=Indexer(room.store,room.config,rpc)
    from .preflight import verify
    if verify(room.indexer)['status']!='TOKEN_INDEX_READY':raise ValueError('Holder index must finish syncing before LIVE activation')
    sender=Sender(Store(Path(paths['dir'])/'private-live.sqlite3'),rpc,limits,signer)
    exit_adapter=V4LiveExit(sender,room,quoter,{},os.environ['PONS_V4_EXIT_ADDRESS'],os.environ['PONS_V4_EXIT_CODE_HASH'])
    exit_adapter.verify()
    from .payout import WalletDistributions,PayoutConfig
    distributions=WalletDistributions(room,sender,PayoutConfig.environment())
    engine=PonsLive(sender,room,quoter.registry['factory']['address'],quoter.registry['factory']['runtime_keccak256'],v4=exit_adapter)
    execution.engine=engine;execution.distributions=distributions;bridge.live_distributions=distributions
    if execution.size_wei>limits.max_entry_wei:raise ValueError('Worker entry size exceeds explicit LIVE limit')
    if execution.account.position and not sender.lookup(f'{execution.bag_run_id}:{execution.account.position.episode_id}:entry:buy'):
        raise ValueError('Restored position has no signed LIVE entry; refusing paper-to-live conversion')
    if execution.account.position is None:
        execution.refresh_account()
    return engine
