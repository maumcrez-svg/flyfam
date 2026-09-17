"""Holder adapters are independent of the real worker's position source."""
import json
from pathlib import Path
from .config import address
from .store import Store,digest
from .indexer import Indexer,Rpc


class FixtureHolders:
    """Declared test balances anchored to real finalized Pons headers, never token holdings."""
    def __init__(self,store,config,rpc):
        if not config.integration:raise ValueError('Fixture adapter requires explicit real-PAPER/test-holder mode')
        self.store,self.config,self.rpc=store,config,rpc
        raw=Path(config.fixture_holders_file).read_bytes()
        if len(raw)>65536:raise ValueError('Test-holder fixture exceeds bound')
        fixture=json.loads(raw)
        if fixture.get('holder_source')!='FIXTURE' or fixture.get('chain_id')!=4663:raise ValueError('Invalid test-holder fixture')
        self.balances={address(w):str(n) for w,n in fixture['balances'].items()}
        if not self.balances or len(self.balances)>100 or any(not n.isdecimal() or not 0<int(n)<2**256 for n in self.balances.values()):raise ValueError('Invalid fixture balances')
        self.identity=digest({'fixture_id':fixture['fixture_id'],'balances':self.balances,'chain_id':4663})
        with store.transaction() as db:
            old=Store.get(db,'fixture_holder_identity')
            if old and old!=self.identity and db.execute("SELECT 1 FROM bags WHERE status!='CLOSED'").fetchone():raise ValueError('Cannot change test holders during an open bag')
            Store.put(db,'fixture_holder_identity',self.identity)

    def finalized(self):
        if int(self.rpc.call('eth_chainId',[]),16)!=4663:raise ValueError('Pons header chain mismatch')
        return self.rpc.block('finalized')

    def sync(self,**kwargs):
        header=self.finalized()
        with self.store.transaction() as db:
            Store.put(db,'fixture_holder_cursor',{'block':int(header['number'],16),'hash':header['hash'],'holder_source':'FIXTURE'})
        return header

    def materialize(self,entry_block,*,cutoff=None):
        final=self.finalized();block=min(int(final['number'],16),int(entry_block)-1)
        if cutoff: block=int(cutoff['block'])
        if block<0 or block>=entry_block or block>int(final['number'],16):raise ValueError('Snapshot must precede entry and be finalized')
        header=self.rpc.block(block)
        if cutoff and header['hash']!=cutoff['hash']:raise ValueError('Finalized snapshot hash changed')
        balances={w:n for w,n in sorted(self.balances.items()) if w not in self.config.excluded}
        holders=list(balances)
        from eth_utils import keccak
        from .economics import tree
        leaves=[keccak(json.dumps(['TEST_HOLDERS',self.identity,4663,block,w,n],separators=(',',':')).encode()) for w,n in balances.items()]
        evidence={'snapshot_block':block,'snapshot_block_hash':header['hash'],
            'eligible_wallet_count':len(holders),'eligibility_version':2,'snapshot_hash':digest(holders),
            'hash_algorithm':'sha256(sorted lowercase address JSON)','token':None,'chain_id':4663,
            'excluded_addresses':list(self.config.excluded),'holder_source':'FIXTURE',
            'fixture_identity':self.identity,'holder_evidence':'DECLARED TEST BALANCES; NOT ERC20 OWNERSHIP',
            'economic_version':1,'snapshot_balances':balances,'eligible_token_balance_total':str(sum(map(int,balances.values()))),
            'economic_snapshot_hash':digest(balances),'eligibility_root':tree(leaves)[0],'claimable':False}
        return evidence,holders


def build_source(store,config,rpc):
    if not config.configured:return None
    return FixtureHolders(store,config,rpc) if config.integration else Indexer(store,config,rpc)
