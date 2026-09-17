"""Native-ETH holder payouts. Public jobs contain no key or signed transaction bytes.

Trading funds confirmed profit; a separate, restricted sender pays claims/sweeps.
Gas is a separate operating reserve and never reduces holder allocations.
"""
from dataclasses import dataclass
import json
import os
from .config import address
from .economics import uint
from .store import Store,canonical,digest
from .distributions import Distributions
from .live_rpc import Pending,TransactionFailed

MODE='PAYOUT_WALLET'

class ClaimExpired(ValueError):pass

@dataclass(frozen=True)
class PayoutConfig:
    wallet:str
    fly_wallet:str
    window_days:int=30
    gas_sponsor:str='UNCONFIGURED'
    fixture:bool=False
    def __post_init__(self):
        for key in ('wallet','fly_wallet'):object.__setattr__(self,key,address(getattr(self,key)))
        if self.wallet==self.fly_wallet or int(self.wallet,16)==0 or int(self.fly_wallet,16)==0:raise ValueError('Payout and Fly must be distinct nonzero wallets')
        if not 1<=self.window_days<=365:raise ValueError('Invalid claim window')
        if self.gas_sponsor not in ('FLY','OPERATIONS','UNCONFIGURED'):raise ValueError('Invalid gas sponsor')
    @classmethod
    def environment(cls):
        return cls(os.environ['HOLDER_PAYOUT_WALLET_ADDRESS'],os.environ['FLY_WALLET_ADDRESS'],
            int(os.getenv('CLAIM_WINDOW_DAYS','30')),os.getenv('PAYOUT_GAS_SPONSOR','UNCONFIGURED'))
    def public(self):
        return {'mode':MODE,'wallet':self.wallet,'fly_wallet':self.fly_wallet,'chain_id':4663,
            'asset':'NATIVE_ETH','window_days':self.window_days,'gas_sponsor':self.gas_sponsor,'fixture':self.fixture}


def configure(room,config):
    with room.store.transaction() as db:
        old=Store.get(db,'payout_config')
        if old and old!=config.public():
            if db.execute("SELECT 1 FROM bag_distributions WHERE status NOT IN ('SWEPT') AND json_extract(evidence,'$.mode')=?",(MODE,)).fetchone():
                raise ValueError('Resolve existing wallet distributions before changing payout identity/policy')
        Store.put(db,'payout_config',config.public())


class WalletDistributions(Distributions):
    """Runs inside the Fly executor. Its signer never belongs to the Payout Wallet."""
    def __init__(self,room,sender,config):
        self.room,self.sender,self.rpc,self.config=room,sender,sender.rpc,config
        self.vault=config.wallet  # Compatibility field; always an EOA, no vault call.
        if sender.limits.role!='TRADE' or sender.limits.wallet!=config.fly_wallet:raise ValueError('Funding requires the dedicated Fly sender')
        if sender.limits.fixture!=config.fixture:raise ValueError('Payout fixture/production mismatch')
        if not config.fixture and (room.config.fixture or room.config.integration):raise ValueError('Real payouts require real-holder snapshots')
        configure(room,config)

    def allocation(self,bag_id,profit,balances):
        rows=sorted((address(w),uint(n)) for w,n in balances.items())
        total=sum(n for _,n in rows)
        if not total or any(n==0 for _,n in rows) or len({w for w,_ in rows})!=len(rows):raise ValueError('No valid immutable holder balances')
        allocations=[{'wallet':w,'snapshot_balance':str(n),'amount':str(profit*n//total)} for w,n in rows]
        allocated=sum(int(a['amount']) for a in allocations)
        return {'mode':MODE,'bag_id':bag_id,'chain_id':4663,'wallet':self.config.wallet,'vault':None,
            'fly_wallet':self.config.fly_wallet,'asset':'NATIVE_ETH','funded_amount':str(profit),
            'allocated_amount':str(allocated),'rounding_dust':str(profit-allocated),
            'eligible_balance_total':str(total),'allocations_hash':digest(allocations),'allocations':allocations,
            'window_seconds':self.config.window_days*86400,'gas_sponsor':self.config.gas_sponsor}

    def fund(self,bag_id):
        with self.room.store.read() as db:row=db.execute('SELECT * FROM bag_distributions WHERE bag_id=?',(bag_id,)).fetchone()
        if not row:return None
        e=json.loads(row['evidence'])
        if e.get('mode')!=MODE or e['wallet']!=self.config.wallet:raise ValueError('Wrong distribution funding adapter')
        if row['funding_tx']:return {'bag_id':bag_id,'status':row['status']}
        if self.rpc.call('eth_getCode',[self.config.wallet,'latest']) not in ('0x','0x0'):raise ValueError('Payout address must be an undelegated EOA')
        receipt=self.sender.transact(bag_id+':payout-funding','PAYOUT_FUND',self.config.wallet,'0x',int(e['funded_amount']))
        block=int(receipt['blockNumber'],16);opened=int(self.rpc.block(block)['timestamp'],16)
        with self.room.store.transaction() as db:
            current=db.execute('SELECT funding_tx FROM bag_distributions WHERE bag_id=?',(bag_id,)).fetchone()[0]
            if current:
                if current!=receipt['transactionHash']:raise ValueError('Conflicting funding receipt')
                return {'bag_id':bag_id,'status':'OPEN'}
            db.execute("UPDATE bag_distributions SET funding_tx=?,deadline=?,status='OPEN' WHERE bag_id=?",(receipt['transactionHash'],opened+e['window_seconds'],bag_id))
            Store.emit(db,'BAG_DISTRIBUTION_OPENED',bag_id,{'mode':MODE,'amount':e['funded_amount'],
                'recipient':self.config.wallet,'transaction_hash':receipt['transactionHash'],'block_number':block,
                'opened_at':opened,'claim_deadline':opened+e['window_seconds'],'fixture':self.config.fixture},self.room.now())
        return {'bag_id':bag_id,'status':'OPEN','funding_transaction':receipt['transactionHash']}

    def tick(self):
        # Claims and expiry are owned by the separately keyed payout process.
        return None


def claim_job(db,bag_id,wallet,now,*,create=False,evidence=None):
    row=db.execute('SELECT * FROM bag_distributions WHERE bag_id=?',(bag_id,)).fetchone()
    if not row:raise ValueError('No holder distribution for this bag')
    distribution=json.loads(row['evidence'])
    if distribution.get('mode')!=MODE:raise ValueError('This distribution is not a wallet payout')
    allocation=db.execute('SELECT evidence FROM bag_allocations WHERE bag_id=? AND wallet=?',(bag_id,wallet)).fetchone()
    if not allocation:raise ValueError('Wallet has no immutable allocation')
    amount=uint(json.loads(allocation[0])['amount'])
    if not amount:raise ValueError('Allocation rounds to zero')
    old=db.execute("SELECT * FROM payout_jobs WHERE bag_id=? AND wallet=? AND kind='CLAIM'",(bag_id,wallet)).fetchone()
    if old:return public_job(old)
    if row['deadline'] and now>=row['deadline']:raise ClaimExpired('Claim window expired')
    if row['status']!='OPEN' or not row['funding_tx'] or not row['deadline']:raise ValueError('Claim is not funded')
    if not create:return {'status':'AVAILABLE','amount':str(amount)}
    key=bag_id+':claim:'+wallet
    db.execute("INSERT INTO payout_jobs(id,bag_id,wallet,kind,amount,status,created_at) VALUES (?,?,?,'CLAIM',?,'QUEUED',?)",(key,bag_id,wallet,str(amount),now))
    Store.emit(db,'HOLDER_CLAIM_REQUESTED',bag_id,{'wallet':wallet,'amount':str(amount),'job_id':key,'evidence':evidence},now)
    return {'status':'PENDING','job_id':key,'amount':str(amount),'recipient':wallet,'transaction_hash':None}


def public_job(row):
    state=row['status']
    return {'job_id':row['id'],'status':state if state in ('CONFIRMED','FAILED','EXPIRED') else 'PENDING',
        'amount':row['amount'],'asset':'NATIVE_ETH','recipient':row['wallet'],'transaction_hash':row['tx_hash'],
        'block_number':row['block_number'],'confirmed_at':row['confirmed_at'],'error':row['error']}


def liabilities(db):
    total=0
    for r in db.execute("SELECT evidence,paid,status FROM bag_distributions WHERE funding_tx IS NOT NULL AND json_extract(evidence,'$.mode')=?",(MODE,)):
        if r['status']!='SWEPT':total+=int(json.loads(r['evidence'])['funded_amount'])-int(r['paid'])
    return total


class PayoutWorker:
    """Only consumes canonical jobs. A separate OS process owns this key/outbox."""
    def __init__(self,room,sender,config):
        self.room,self.sender,self.rpc,self.config=room,sender,sender.rpc,config
        if sender.limits.role!='PAYOUT' or sender.limits.wallet!=config.wallet:raise ValueError('Payout worker requires its exclusive restricted sender')
        if sender.limits.fixture!=config.fixture:raise ValueError('Payout signer mode mismatch')
        if config.gas_sponsor=='UNCONFIGURED':raise ValueError('Configure who sponsors payout gas separately from holder profit')
        if not config.fixture and (room.config.fixture or room.config.integration):raise ValueError('Real payouts require real-holder snapshots')
        configure(room,config)

    def reconcile(self):
        if self.rpc.call('eth_getCode',[self.config.wallet,'latest']) not in ('0x','0x0'):raise ValueError('Payout wallet must remain an undelegated EOA')
        head=self.rpc.block('finalized');balance=int(self.rpc.call('eth_getBalance',[self.config.wallet,head['number']]),16)
        latest=int(self.rpc.call('eth_getBalance',[self.config.wallet,'latest']),16)
        available=min(balance,latest) # Do not spend liabilities already missing from the latest state.
        with self.room.store.transaction() as db:
            owed=liabilities(db)
            projection={'wallet':self.config.wallet,'block_number':int(head['number'],16),'block_hash':head['hash'],
                'balance_wei':str(balance),'latest_balance_wei':str(latest),'available_balance_wei':str(available),
                'holder_liability_wei':str(owed),'gas_reserve_wei':str(max(0,available-owed)),
                'gas_sponsor':self.config.gas_sponsor,'status':'SOLVENT' if available>=owed else 'DEFICIT',
                'checked_at':self.room.now(),'fixture':self.config.fixture}
            Store.put(db,'payout_reconciliation',projection)
        return projection

    def _finish(self,job,receipt):
        key=job['id'];amount=int(job['amount']);block=int(receipt['blockNumber'],16)
        confirmed=int(self.rpc.block(block)['timestamp'],16)
        with self.room.store.transaction() as db:
            old=db.execute('SELECT status,tx_hash FROM payout_jobs WHERE id=?',(key,)).fetchone()
            if old['status']=='CONFIRMED':
                if old['tx_hash']!=receipt['transactionHash']:raise ValueError('Conflicting payout receipt')
                return
            db.execute("UPDATE payout_jobs SET status='CONFIRMED',tx_hash=?,block_number=?,confirmed_at=?,error=NULL WHERE id=?",(receipt['transactionHash'],block,confirmed,key))
            if job['kind']=='CLAIM':
                db.execute('INSERT INTO holder_claims VALUES (?,?,?,?,?)',(job['bag_id'],job['wallet'],str(amount),receipt['transactionHash'],block))
                paid=int(db.execute('SELECT paid FROM bag_distributions WHERE bag_id=?',(job['bag_id'],)).fetchone()[0])+amount
                db.execute('UPDATE bag_distributions SET paid=? WHERE bag_id=?',(str(paid),job['bag_id']))
                kind='HOLDER_CLAIMED'
            else:
                db.execute("UPDATE bag_distributions SET status='SWEPT',sweep_tx=? WHERE bag_id=?",(receipt['transactionHash'],job['bag_id']))
                kind='UNCLAIMED_RETURNED_TO_FLY'
            Store.emit(db,kind,job['bag_id'],{'amount':str(amount),'recipient':job['wallet'],'asset':'NATIVE_ETH',
                'transaction_hash':receipt['transactionHash'],'block_number':block,'block_hash':receipt['blockHash'],
                'confirmed_at':confirmed,'gas_wei':str(self.sender.gas_cost(receipt)),'fixture':self.config.fixture},self.room.now())

    def _run(self,job):
        key=job['id']
        try:
            if not self.sender.lookup(key):
                state=self.reconcile()
                gas=self.sender.limits.max_gas_per_tx*self.sender.limits.max_gas_price_wei
                if state['status']!='SOLVENT' or int(state['gas_reserve_wei'])<gas:raise Pending('Separate payout gas reserve is insufficient; holder funds remain reserved')
            receipt=self.sender.transact(key,'PAYOUT_'+job['kind'],job['wallet'],'0x',int(job['amount']))
            self._finish(job,receipt)
        except Pending as exc:
            private=self.sender.lookup(key)
            with self.room.store.transaction() as db:
                db.execute("UPDATE payout_jobs SET status=?,tx_hash=?,error=? WHERE id=? AND status!='CONFIRMED'",('PENDING' if private else 'QUEUED',private['hash'] if private else None,str(exc),key))
        except (ValueError,TransactionFailed) as exc:
            private=self.sender.lookup(key)
            # A broadcast/RPC error with signed bytes is uncertain, never a new payment.
            final_revert=bool(private and private['receipt'] and int(json.loads(private['receipt'])['status'],16)==0)
            with self.room.store.transaction() as db:
                db.execute("UPDATE payout_jobs SET status=?,tx_hash=?,error=? WHERE id=? AND status!='CONFIRMED'",
                    ('FAILED' if final_revert or not private else 'PENDING',private['hash'] if private else None,type(exc).__name__+': '+str(exc)[:180],key))
        except OSError:
            # Keep DISPATCHING durable. Restart rechecks the same private outbox key.
            with self.room.store.transaction() as db:db.execute("UPDATE payout_jobs SET error='RPC unavailable; reconciling the same payout intent' WHERE id=? AND status!='CONFIRMED'",(key,))

    def step(self):
        now=self.room.now()
        with self.room.store.transaction() as db:
            # Resolve sent/uncertain transfers before expiry or any new nonce.
            row=db.execute("SELECT * FROM payout_jobs WHERE status IN ('DISPATCHING','PENDING') ORDER BY created_at,id LIMIT 1").fetchone()
            if not row:
                for d in db.execute("SELECT bag_id,paid,evidence,status FROM bag_distributions WHERE funding_tx IS NOT NULL AND deadline<=? AND status IN ('OPEN','EXPIRED') AND json_extract(evidence,'$.mode')=?",(now,MODE)).fetchall():
                    if d['status']=='OPEN':
                        db.execute("UPDATE bag_distributions SET status='EXPIRED' WHERE bag_id=?",(d['bag_id'],))
                        Store.emit(db,'BAG_DISTRIBUTION_EXPIRED',d['bag_id'],{'mode':MODE},now)
                    # A signature accepted before the deadline reserves its allocation,
                    # even if gas/network recovery delays broadcast until after expiry.
                    if db.execute("SELECT 1 FROM payout_jobs WHERE bag_id=? AND kind='CLAIM' AND status IN ('QUEUED','DISPATCHING','PENDING')",(d['bag_id'],)).fetchone():continue
                    e=json.loads(d['evidence']);remaining=int(e['funded_amount'])-int(d['paid'])
                    if remaining:
                        db.execute("INSERT OR IGNORE INTO payout_jobs(id,bag_id,wallet,kind,amount,status,created_at) VALUES (?,?,?,'SWEEP',?,'QUEUED',?)",(d['bag_id']+':sweep',d['bag_id'],self.config.fly_wallet,str(remaining),now))
                    else:db.execute("UPDATE bag_distributions SET status='SWEPT' WHERE bag_id=?",(d['bag_id'],))
                row=db.execute("SELECT * FROM payout_jobs WHERE status='QUEUED' ORDER BY created_at,id LIMIT 1").fetchone()
                if row:db.execute("UPDATE payout_jobs SET status='DISPATCHING' WHERE id=?",(row['id'],))
        if row:self._run(dict(row))
        self.reconcile()
