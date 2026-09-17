"""Bounded token activation check. No signer, deployment or transaction methods."""
import argparse,json,os
from eth_abi import decode
from eth_utils import keccak
from .config import Config
from .indexer import Indexer,Rpc
from .store import Store

def verify(indexer):
    cfg=indexer.config;rpc=indexer.rpc
    header=indexer.finalized();block=header['number']
    if int(block,16)<cfg.deployment_block:raise ValueError('Deployment is not finalized')
    code=rpc.call('eth_getCode',[cfg.token,block])
    if code in ('0x','0x0'):raise ValueError('Project token has no bytecode')
    def read(signature,kind):
        data='0x'+keccak(text=signature)[:4].hex()
        return decode([kind],bytes.fromhex(rpc.call('eth_call',[{'to':cfg.token,'data':data},block])[2:]))[0]
    decimals=read('decimals()','uint8')
    if cfg.decimals is None or decimals!=cfg.decimals:raise ValueError('Set PROJECT_TOKEN_DECIMALS to the verified token decimals')
    metadata={'chain_id':cfg.chain_id,'token':cfg.token,'deployment_block':cfg.deployment_block,
        'decimals':decimals,'symbol':read('symbol()','string'),'name':read('name()','string'),
        'total_supply':str(read('totalSupply()','uint256')),'verified_block':int(block,16),'verified_hash':header['hash']}
    cursor=indexer.sync(int(block,16))
    if not cursor or cursor['block']<int(block,16):return {**metadata,'status':'INDEXING','cursor':cursor}
    with indexer.store.read() as db:
        balances=[int(r[0]) for r in db.execute('SELECT amount FROM balances')]
    if sum(balances)!=int(metadata['total_supply']):raise ValueError('Transfer ledger does not reconcile to total supply at finalized block')
    metadata.update(status='TOKEN_INDEX_READY',holder_count=sum(n>0 for n in balances))
    with indexer.store.transaction() as db:Store.put(db,'token_verified',metadata)
    return metadata

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--database',required=True);args=parser.parse_args()
    cfg=Config.environment()
    if not cfg.configured:print(json.dumps({'status':'READY_FOR_TOKEN_ADDRESS','production_enabled':False}));return
    result=verify(Indexer(Store(args.database),cfg,Rpc(os.environ['FLYTRADE_LOCAL_RPC'])))
    print(json.dumps(result,indent=2))
if __name__=='__main__':main()
