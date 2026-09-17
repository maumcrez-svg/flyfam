"""Finalized ERC-20 Transfer ledger. No per-holder balanceOf RPC fanout."""
import json
from urllib.request import Request, urlopen
from .config import address
from .store import Store, digest

ZERO = '0x' + '0'*40
TRANSFER = '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef'

class Rpc:
    def __init__(self, url): self.url = url
    def call(self, method, params):
        if method not in {'eth_chainId','eth_getBlockByNumber','eth_getLogs','eth_getCode','eth_call'}:
            raise ValueError('Read-only holder RPC')
        req = Request(self.url, data=json.dumps({'jsonrpc':'2.0','id':1,'method':method,'params':params}).encode(), headers={'Content-Type':'application/json'})
        with urlopen(req, timeout=8) as response:
            body = response.read(16*1024*1024+1)
        if len(body)>16*1024*1024: raise ValueError('RPC response exceeds bound; reduce index range')
        result = json.loads(body)
        if 'error' in result: raise ValueError('Holder RPC request failed')
        return result['result']
    def block(self, number):
        result = self.call('eth_getBlockByNumber', [hex(number) if isinstance(number,int) else number,False])
        if not result or not result.get('hash'): raise ValueError('Finality/header unavailable')
        return result

class Indexer:
    def __init__(self, store, config, rpc):
        self.store, self.config, self.rpc = store, config, rpc
        if not config.configured: raise ValueError('Project token is not configured')
        identity = {'chain_id':config.chain_id,'token':config.token,'deployment_block':config.deployment_block}
        with store.transaction() as db:
            old = Store.get(db,'token_identity')
            if old and old != identity: raise ValueError('Token changed: use a separate database')
            cursor = Store.get(db,'holder_cursor')
            # Initial Phase A release used this key for explicitly labeled test headers.
            # They are not an ERC-20 index frontier: activation must backfill deployment.
            if cursor and cursor.get('holder_source') == 'FIXTURE':
                if db.execute("SELECT 1 FROM bags WHERE status!='CLOSED'").fetchone():
                    raise ValueError('Finish the TEST-holder bag before activating the token index')
                if db.execute('SELECT 1 FROM transfers LIMIT 1').fetchone() or db.execute('SELECT 1 FROM balances LIMIT 1').fetchone():
                    raise ValueError('Test header cursor conflicts with an existing token ledger')
                Store.put(db,'fixture_holder_cursor',cursor)
                Store.put(db,'holder_cursor',None)
            Store.put(db,'token_identity',identity)

    def finalized(self):
        if int(self.rpc.call('eth_chainId',[]),16) != self.config.chain_id: raise ValueError('Holder RPC chain mismatch')
        return self.rpc.block('finalized')

    def target(self, entry_block):
        final = self.finalized()
        number = min(int(final['number'],16), int(entry_block)-1)
        if number < self.config.deployment_block: raise ValueError('No finalized project-token history before this entry')
        header = self.rpc.block(number)
        return number, header['hash']

    def sync(self, target=None, *, max_chunks=10, chunk=2000):
        final = self.finalized()
        end = min(int(final['number'],16), target if target is not None else int(final['number'],16))
        with self.store.read() as db: cursor = Store.get(db,'holder_cursor')
        if cursor and self.rpc.block(cursor['block'])['hash'] != cursor['hash']:
            raise ValueError('FINALIZED_REORG: holder ledger halted; restore verified history')
        start = cursor['block']+1 if cursor else self.config.deployment_block
        for _ in range(max_chunks):
            if start > end: break
            stop = min(end,start+chunk-1)
            header = self.rpc.block(stop)
            logs = self.rpc.call('eth_getLogs',[{'address':self.config.token,'fromBlock':hex(start),'toBlock':hex(stop),'topics':[TRANSFER]}])
            decoded = []
            for log in logs:
                if log.get('removed') or address(log['address']) != self.config.token or log['topics'][0].lower()!=TRANSFER:
                    raise ValueError('Inconsistent finalized Transfer evidence')
                if len(log['topics'])!=3 or len(log['data'])!=66: raise ValueError('Nonstandard Transfer event')
                block,index = int(log['blockNumber'],16),int(log['logIndex'],16)
                if not start<=block<=stop: raise ValueError('Transfer outside requested range')
                decoded.append((block,index,log['blockHash'],log['transactionHash'],address('0x'+log['topics'][1][-40:]),address('0x'+log['topics'][2][-40:]),str(int(log['data'],16))))
            if self.rpc.block(stop)['hash'] != header['hash']: raise ValueError('Block changed during holder indexing')
            with self.store.transaction() as db:
                current = Store.get(db,'holder_cursor')
                if current != cursor: raise ValueError('Concurrent holder indexer')
                for row in sorted(decoded):
                    db.execute('INSERT INTO transfers VALUES (?,?,?,?,?,?,?)',row)
                    for wallet, delta in ((row[4],-int(row[6])),(row[5],int(row[6]))):
                        if wallet==ZERO: continue  # Mint/burn accounting, never a synthetic zero-address holder.
                        old = db.execute('SELECT amount FROM balances WHERE wallet=?',(wallet,)).fetchone()
                        amount = (int(old[0]) if old else 0)+delta
                        if amount<0: raise ValueError('Incomplete Transfer ledger: negative balance; check deployment block')
                        db.execute('INSERT OR REPLACE INTO balances VALUES (?,?)',(wallet,str(amount)))
                cursor = {'block':stop,'hash':header['hash']}
                Store.put(db,'holder_cursor',cursor)
            start=stop+1
        return cursor

    def materialize(self, entry_block, *, cutoff=None):
        target, block_hash = self.target(entry_block) if cutoff is None else (cutoff['block'],cutoff['hash'])
        if target >= entry_block or target < self.config.deployment_block: raise ValueError('Invalid eligibility cutoff')
        if target > int(self.finalized()['number'],16): raise ValueError('Eligibility cutoff is not finalized')
        cursor = self.sync(target)
        if not cursor or cursor['block']<target: return None  # Catch up in bounded batches.
        with self.store.read() as db:
            balances = {r['wallet']:int(r['amount']) for r in db.execute('SELECT * FROM balances')}
            # Normally only a recent tail: entry OPEN may arrive behind the indexed finalized frontier.
            tail = db.execute('SELECT sender,recipient,amount FROM transfers WHERE block>? ORDER BY block DESC,log_index DESC LIMIT 100001',(target,)).fetchall()
            if len(tail)>100000: raise ValueError('Snapshot predates bounded rollback tail; use verified historical index')
            for row in tail:
                for wallet,delta in ((row['sender'],int(row['amount'])),(row['recipient'],-int(row['amount']))):
                    if wallet!=ZERO: balances[wallet]=balances.get(wallet,0)+delta
        if any(n<0 for n in balances.values()): raise ValueError('Invalid reconstructed holder state')
        eligible = sorted(w for w,n in balances.items() if n>0 and w not in self.config.excluded)
        if self.rpc.block(target)['hash'] != block_hash: raise ValueError('Snapshot finality changed')
        evidence = {'snapshot_block':target,'snapshot_block_hash':block_hash,'eligible_wallet_count':len(eligible),
                    'eligibility_version':1,'snapshot_hash':digest(eligible),'hash_algorithm':'sha256(sorted lowercase address JSON)',
                    'token':self.config.token,'chain_id':self.config.chain_id,'excluded_addresses':list(self.config.excluded)}
        from .economics import snapshot_tree
        economic = {w:str(balances[w]) for w in eligible}
        evidence.update(economic_version=1,snapshot_balances=economic,
                        eligible_token_balance_total=str(sum(balances[w] for w in eligible)),
                        economic_snapshot_hash=digest(economic),
                        eligibility_root=snapshot_tree(self.config.chain_id,self.config.token,target,economic))
        return evidence,eligible
