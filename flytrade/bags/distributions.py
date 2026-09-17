"""Bag-specific native ETH liabilities and confirmed HolderVault projection.

Only a private worker calls settle/fund/sync. Public proof reads cannot send a tx.
"""
import json
import os
from eth_abi import decode
from eth_utils import keccak
from .economics import allocate,bag_key,uint
from .config import address
from .live_pons import calldata
from .store import Store,canonical

class Distributions:
    def __init__(self,room,sender,vault,expected_code_hash):
        self.room,self.sender,self.rpc=room,sender,sender.rpc
        self.vault=address(vault);self.expected_code_hash=expected_code_hash

    def verify_contract(self):
        code=self.rpc.call('eth_getCode',[self.vault,'latest'])
        if '0x'+keccak(bytes.fromhex(code[2:])).hex()!=self.expected_code_hash:raise ValueError('HolderVault bytecode mismatch')
        window=int(os.environ.get('CLAIM_WINDOW_DAYS','30'))*86400
        raw=self.rpc.call('eth_call',[{'to':self.vault,'data':calldata('claimWindow()')},'latest'])
        if decode(['uint64'],bytes.fromhex(raw[2:]))[0]!=window:raise ValueError('HolderVault claim window mismatch')
        for name,expected in [('funder()',self.sender.limits.wallet),('flyBankroll()',self.sender.limits.wallet)]:
            result=self.rpc.call('eth_call',[{'to':self.vault,'data':calldata(name)},'latest'])
            if decode(['address'],bytes.fromhex(result[2:]))[0]!=expected:raise ValueError('HolderVault funder/bankroll mismatch')

    def tick(self):
        # One active distribution per tick, round-robin; never load all holders.
        with self.room.store.read() as db:
            cursor=Store.get(db,'distribution_poll_cursor','')
            row=db.execute("SELECT bag_id FROM bag_distributions WHERE status IN ('OPEN','EXPIRED') AND bag_id>? ORDER BY bag_id LIMIT 1",(cursor,)).fetchone()
            if not row:row=db.execute("SELECT bag_id FROM bag_distributions WHERE status IN ('OPEN','EXPIRED') ORDER BY bag_id LIMIT 1").fetchone()
        if not row:return
        bag_id=row[0];state=self.sync(bag_id)
        if state and state['status']=='EXPIRED':
            self.sender.transact(bag_id+':sweep','VAULT_SWEEP',self.vault,calldata('sweepExpired(bytes32)',['bytes32'],[bag_key(bag_id)]))
            self.sync(bag_id)
        with self.room.store.transaction() as db:Store.put(db,'distribution_poll_cursor',bag_id)

    def allocation(self,bag_id,profit,balances):
        return allocate(4663,self.vault,bag_id,profit,balances)

    def settle(self,bag_id,settlement):
        if settlement.get('execution')!='LIVE':raise ValueError('PAPER profit cannot fund an on-chain distribution')
        decision=None
        with self.room.store.read() as db:
            bag=self.room._bag(db,bag_id);entry=json.loads(bag['entry']);snapshot=json.loads(bag['snapshot'])
            decision=entry.get('decision_id')
        # Require the exact confirmed private executor outcome, not client-provided PnL.
        with self.sender.store.read() as db:
            position=db.execute('SELECT closed FROM live_positions WHERE decision=?',(decision,)).fetchone()
            if not position or not position[0] or json.loads(position[0])!=settlement:raise ValueError('Settlement is not a confirmed LIVE outcome')
        profit=uint(settlement['holder_profit'])
        evidence=None
        if profit:
            if 'snapshot_balances' not in snapshot:raise ValueError('Legacy bag has no economic snapshot; never reconstruct from current holdings')
            evidence=self.allocation(bag_id,profit,snapshot['snapshot_balances'])
            evidence.update(snapshot_root=snapshot['eligibility_root'],execution='LIVE',fixture=self.sender.limits.fixture)
        with self.room.store.transaction() as db:
            bag=self.room._bag(db,bag_id)
            if bag['status']=='CLOSED':return
            result={**settlement,'net_pnl_wei':settlement['net_realized_pnl'],
                'vault_credit_wei':str(profit),'principal_returned_wei':settlement['principal_returned_to_fly'],
                'close_reason':'COMMUNITY_EXIT','accounting':'LIVE; exact native units from finalized transaction receipts'}
            db.execute("UPDATE bags SET status='CLOSED',result=? WHERE id=?",(canonical(result),bag_id))
            db.execute("UPDATE rounds SET status='CANCELLED' WHERE bag_id=? AND status='OPEN'",(bag_id,))
            Store.emit(db,'EXIT_CONFIRMED',bag_id,{'tx_hash':settlement['exit']['tx_hash']},self.room.now())
            Store.emit(db,'BAG_SETTLEMENT_CREATED',bag_id,result,self.room.now())
            Store.emit(db,'BAG_CLOSED',bag_id,result,self.room.now())
            Store.emit(db,'LEARNING_FROZEN',bag_id,{'outcome':'OUTCOME_POSITIVE' if profit else 'OUTCOME_NONPOSITIVE','applied':False},self.room.now())
            if evidence:
                allocations=evidence.pop('allocations')
                db.executemany('INSERT INTO bag_allocations VALUES (?,?,?)',[(bag_id,a['wallet'],canonical(a)) for a in allocations])
                db.execute('INSERT INTO bag_distributions(bag_id,evidence,status) VALUES (?,?,?)',(bag_id,canonical(evidence),'AWAITING_FUNDING'))
                Store.emit(db,'BAG_PROFIT_REALIZED',bag_id,{'amount':str(profit),'distribution_status':'AWAITING_FUNDING'},self.room.now())

    def fund(self,bag_id):
        with self.room.store.read() as db:
            row=db.execute('SELECT * FROM bag_distributions WHERE bag_id=?',(bag_id,)).fetchone()
        if not row:return None
        if row['funding_tx']:return self.sync(bag_id)
        e=json.loads(row['evidence']);self.verify_contract()
        receipt=self.sender.transact(bag_id+':vault','VAULT_FUND',self.vault,
            calldata('openDistribution(bytes32,bytes32)',['bytes32','bytes32'],[bag_key(bag_id),bytes.fromhex(e['root'][2:])]),int(e['funded_amount']))
        with self.room.store.transaction() as db:
            db.execute('UPDATE bag_distributions SET funding_tx=? WHERE bag_id=?',(receipt['transactionHash'],bag_id))
            if Store.get(db,'vault_log_cursor') is None:
                Store.put(db,'vault_log_cursor',int(receipt['blockNumber'],16)-1)
        return self.sync(bag_id)

    def sync(self,bag_id):
        self.verify_contract()
        header=self.rpc.block('finalized');block=header['number']
        self.observe_claims(header)
        with self.room.store.read() as db:
            row=db.execute('SELECT * FROM bag_distributions WHERE bag_id=?',(bag_id,)).fetchone()
        if not row:return None
        e=json.loads(row['evidence'])
        raw=self.rpc.call('eth_call',[{'to':self.vault,'data':calldata('distributions(bytes32)',['bytes32'],[bag_key(bag_id)])},block])
        root,funded,paid,deadline,swept=decode(['bytes32','uint256','uint256','uint64','bool'],bytes.fromhex(raw[2:]))
        if not deadline:return None
        if root.hex()!=e['root'][2:] or funded!=int(e['funded_amount']):raise ValueError('Distribution does not match canonical liability')
        status='SWEPT' if swept else ('EXPIRED' if int(header['timestamp'],16)>=deadline else 'OPEN')
        # Projection advances only after reading finalized contract state.
        with self.room.store.transaction() as db:
            old=db.execute('SELECT status FROM bag_distributions WHERE bag_id=?',(bag_id,)).fetchone()[0]
            db.execute('UPDATE bag_distributions SET status=?,deadline=?,paid=? WHERE bag_id=?',(status,deadline,str(paid),bag_id))
            if old!=status:
                kind={'OPEN':'BAG_DISTRIBUTION_OPENED','EXPIRED':'BAG_DISTRIBUTION_EXPIRED','SWEPT':'UNCLAIMED_RETURNED_TO_FLY'}[status]
                Store.emit(db,kind,bag_id,{'funded':str(funded),'claimed':str(paid),'unclaimed':str(funded-paid),
                    'deadline':deadline,'block':int(block,16),'block_hash':header['hash'],'fixture':self.sender.limits.fixture},self.room.now())
        return {'bag_id':bag_id,'status':status,'funded':str(funded),'claimed':str(paid),'unclaimed':str(funded-paid),'deadline':deadline}

    def proof(self,bag_id,wallet):
        wallet=address(wallet)
        with self.room.store.read() as db:
            row=db.execute('SELECT * FROM bag_distributions WHERE bag_id=?',(bag_id,)).fetchone()
        if not row:return {'bag_id':bag_id,'wallet':wallet,'claimable':False,'status':'NO_DISTRIBUTION'}
        e=json.loads(row['evidence'])
        with self.room.store.read() as db:
            a=db.execute('SELECT evidence FROM bag_allocations WHERE bag_id=? AND wallet=?',(bag_id,wallet)).fetchone()
        allocation=json.loads(a[0]) if a else None
        header=self.rpc.block('finalized')
        already=decode(['bool'],bytes.fromhex(self.rpc.call('eth_call',[{'to':self.vault,'data':calldata('claimed(bytes32,address)',['bytes32','address'],[bag_key(bag_id),wallet])},header['number']])[2:]))[0]
        expired=bool(row['deadline'] and int(header['timestamp'],16)>=row['deadline'])
        return {'bag_id':bag_id,'wallet':wallet,'status':row['status'],'deadline':row['deadline'],
            'allocation':allocation,'claimed':already,'vault':self.vault,'root':e['root'],'fixture':e['fixture'],
            'claimable':row['status']=='OPEN' and not already and not expired and bool(allocation and int(allocation['amount']))}

    def observe_claims(self,header):
        """A bounded finalized-log projection; public clients never acknowledge claims."""
        with self.room.store.read() as db:
            cursor=Store.get(db,'vault_log_cursor')
            old_hash=Store.get(db,'vault_log_hash')
        if cursor is None:return
        if old_hash and self.rpc.block(cursor)['hash']!=old_hash:raise ValueError('Finalized vault cursor changed')
        target=min(int(header['number'],16),cursor+5000)
        if target<=cursor:return
        topic='0x'+keccak(text='Claimed(bytes32,address,uint256)').hex()
        logs=self.rpc.call('eth_getLogs',[{'address':self.vault,'fromBlock':hex(cursor+1),'toBlock':hex(target),'topics':[topic]}])
        end=self.rpc.block(target)
        with self.room.store.transaction() as db:
            for log in sorted(logs,key=lambda l:(int(l['blockNumber'],16),int(l['logIndex'],16))):
                if log.get('removed') or address(log['address'])!=self.vault or log['topics'][0]!=topic:raise ValueError('Invalid vault log')
                key=log['topics'][1].lower();wallet=address('0x'+log['topics'][2][-40:])
                amount=decode(['uint256'],bytes.fromhex(log['data'][2:]))[0]
                bag=db.execute("SELECT bag_id FROM bag_distributions WHERE json_extract(evidence,'$.bag_key')=?",(key,)).fetchone()
                if not bag:raise ValueError('Unknown funded distribution')
                bag_id=bag[0]
                allocation=db.execute('SELECT evidence FROM bag_allocations WHERE bag_id=? AND wallet=?',(bag_id,wallet)).fetchone()
                if not allocation or int(json.loads(allocation[0])['amount'])!=amount:raise ValueError('Claim differs from canonical allocation')
                old=db.execute('SELECT tx_hash FROM holder_claims WHERE bag_id=? AND wallet=?',(bag_id,wallet)).fetchone()
                if old:
                    if old[0]!=log['transactionHash']:raise ValueError('Conflicting confirmed claim')
                    continue
                db.execute('INSERT INTO holder_claims VALUES (?,?,?,?,?)',(bag_id,wallet,str(amount),log['transactionHash'],int(log['blockNumber'],16)))
                Store.emit(db,'HOLDER_CLAIMED',bag_id,{'wallet':wallet,'amount':str(amount),'transaction_hash':log['transactionHash'],
                    'block':int(log['blockNumber'],16),'block_hash':log['blockHash'],'fixture':self.sender.limits.fixture},self.room.now())
            Store.put(db,'vault_log_cursor',target);Store.put(db,'vault_log_hash',end['hash'])
            Store.put(db,'vault_log_complete',target==int(header['number'],16))
            Store.put(db,'vault_verified_at',self.room.now())
