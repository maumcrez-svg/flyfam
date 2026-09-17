"""Private transaction boundary. Explicit limits, durable signed outbox, finalized receipts.

Never exposed through the spectator HTTP server. No key discovery or automatic
production activation. Test RPC mutations are absent from this production client.
"""
from dataclasses import dataclass
from pathlib import Path
import json
import os
import time
from urllib.request import Request,urlopen
from eth_account import Account
from eth_utils import keccak,to_checksum_address
from .config import address
from .economics import uint
from .store import Store,canonical,digest

class Pending(RuntimeError):pass
class TransactionFailed(RuntimeError):pass

class LiveRpc:
    def __init__(self,url): self.url=url
    def call(self,method,params):
        if method not in {'web3_clientVersion','eth_chainId','eth_getBlockByNumber','eth_getCode','eth_call','eth_getLogs',
            'eth_getBalance','eth_getTransactionCount','eth_getTransactionReceipt','eth_getTransactionByHash',
            'eth_estimateGas','eth_gasPrice','eth_sendRawTransaction'}:raise ValueError('Unsupported LIVE RPC method')
        request=Request(self.url,data=json.dumps({'jsonrpc':'2.0','id':1,'method':method,'params':params}).encode(),headers={'Content-Type':'application/json'})
        with urlopen(request,timeout=10) as response:body=response.read(16*1024*1024+1)
        if len(body)>16*1024*1024:raise ValueError('RPC response too large')
        data=json.loads(body)
        if 'error' in data:raise ValueError('RPC rejected '+method) # Never expose endpoint/signing material.
        return data['result']
    def block(self,n):
        b=self.call('eth_getBlockByNumber',[hex(n) if type(n)is int else n,False])
        if not b or not b.get('hash'):raise Pending('Block unavailable')
        return b

@dataclass(frozen=True)
class Limits:
    wallet:str
    max_entry_wei:int
    max_total_outgoing_wei:int
    max_gas_price_wei:int
    max_gas_per_tx:int
    max_slippage_bps:int
    fixture:bool=False
    production_enabled:bool=False
    role:str="TRADE"
    #: L1 A3. Ceiling on what buying and immediately selling the same inventory
    #: back costs, in bps of what the buy spends. Refuses an entry the curve's
    #: own fees and depth would eat before the community can vote on it.
    max_round_trip_bps:int=600
    def __post_init__(self):
        object.__setattr__(self,'wallet',address(self.wallet))
        if self.role not in ('TRADE','PAYOUT'):raise ValueError('Unknown wallet role')
        if type(self.max_round_trip_bps)is not int or not 1<=self.max_round_trip_bps<=10000:raise ValueError('Round-trip ceiling must be 1-10000 bps')
        for key in ('max_entry_wei','max_total_outgoing_wei','max_gas_price_wei','max_gas_per_tx'):
            if uint(getattr(self,key))==0:raise ValueError('Explicit nonzero monetary limits required')
        if type(self.max_slippage_bps)is not int or not 0<=self.max_slippage_bps<=1000:raise ValueError('Slippage must be 0-1000 bps')
        if not self.fixture and not self.production_enabled:raise ValueError('Explicit production enable required')
    @classmethod
    def environment(cls):
        return cls(wallet=os.environ['FLY_WALLET_ADDRESS'],
            max_entry_wei=int(os.environ['LIVE_MAX_ENTRY_WEI']),
            max_total_outgoing_wei=int(os.environ['LIVE_MAX_TOTAL_OUTGOING_WEI']),
            max_gas_price_wei=int(os.environ['LIVE_MAX_GAS_PRICE_WEI']),
            max_gas_per_tx=int(os.environ['LIVE_MAX_GAS_PER_TX']),
            max_slippage_bps=int(os.environ['LIVE_MAX_SLIPPAGE_BPS']),
            max_round_trip_bps=int(os.getenv('LIVE_MAX_ROUND_TRIP_BPS','600')),
            production_enabled=os.environ.get('LIVE_EXECUTION_ENABLED')=='YES')


def keystore_signer(path,password):
    file=Path(path)
    if file.stat().st_mode&0o077:raise ValueError('Keystore must be owner-readable only')
    return Account.from_key(Account.decrypt(json.loads(file.read_text()),password))

class Sender:
    def __init__(self,store,rpc,limits,signer):
        self.store,self.rpc,self.limits,self.signer=store,rpc,limits,signer
        if address(signer.address)!=limits.wallet:raise ValueError('Signing wallet mismatch')
        if int(rpc.call('eth_chainId',[]),16)!=4663:raise ValueError('Wrong chain')
        if limits.fixture and 'anvil' not in rpc.call('web3_clientVersion',[]).lower():raise ValueError('Fixture signer requires an isolated Anvil node')
        with store.transaction() as db:
            db.execute('CREATE TABLE IF NOT EXISTS live_txs(id TEXT PRIMARY KEY,purpose TEXT NOT NULL,request TEXT NOT NULL,tx TEXT NOT NULL,raw TEXT NOT NULL,hash TEXT NOT NULL UNIQUE,reserved TEXT NOT NULL,receipt TEXT)')
            existing=Store.get(db,'live_wallet')
            if existing and existing!=limits.wallet:raise ValueError('Use a separate database for a different wallet')
            Store.put(db,'live_wallet',limits.wallet)
        # Raw signed transactions belong to the private worker; never serve this DB.
        os.chmod(store.path,0o600)

    def lookup(self,key):
        with self.store.read() as db:
            row=db.execute('SELECT * FROM live_txs WHERE id=?',(key,)).fetchone()
            return dict(row) if row else None

    def receipt(self,key):
        row=self.lookup(key)
        if not row:raise ValueError('Unknown transaction')
        receipt=self.rpc.call('eth_getTransactionReceipt',[row['hash']])
        if receipt is None:
            # Crash before/after broadcast: same signed bytes, never a new nonce.
            try:self.rpc.call('eth_sendRawTransaction',[row['raw']])
            except ValueError:pass
            raise Pending('Transaction awaiting receipt')
        if receipt['transactionHash'].lower()!=row['hash'].lower():raise ValueError('Receipt transaction identity mismatch')
        block=int(receipt['blockNumber'],16)
        if self.rpc.block(block)['hash'].lower()!=receipt['blockHash'].lower():raise Pending('Receipt reorg')
        if int(self.rpc.block('finalized')['number'],16)<block:raise Pending('Transaction not finalized')
        with self.store.transaction() as db:
            db.execute('UPDATE live_txs SET receipt=? WHERE id=?',(canonical(receipt),key))
        if int(receipt['status'],16)!=1:raise TransactionFailed('Transaction reverted; actual gas is retained in the ledger')
        return receipt

    def transact(self,key,purpose,to,data,value=0):
        value=uint(value);to=address(to)
        if self.limits.role=='PAYOUT':
            if purpose not in {'PAYOUT_CLAIM','PAYOUT_SWEEP'} or data!='0x':raise ValueError('Payout wallet only sends native claim/sweep transfers')
            if value>self.limits.max_entry_wei:raise ValueError('Payout exceeds per-transfer maximum')
        elif purpose not in {'BUY','APPROVE','SELL','VAULT_FUND','VAULT_SWEEP','PAYOUT_FUND'}:raise ValueError('Trading wallet cannot send holder claims')
        old=self.lookup(key)
        if old:
            req=json.loads(old['request'])
            if old['purpose']!=purpose or req['to']!=to or req['data']!=data or int(req['value'],16)!=value:raise ValueError('Transaction intent cannot change')
            return self.receipt(key)
        if purpose=='BUY' and value>self.limits.max_entry_wei:raise ValueError('Entry exceeds authorized limit')
        if not isinstance(data,str) or not data.startswith('0x') or len(data)>65538:raise ValueError('Invalid calldata')
        if int(self.rpc.call('eth_chainId',[]),16)!=4663:raise ValueError('Wrong chain')
        request={'from':self.limits.wallet,'to':to,'data':data,'value':hex(value)}
        self.rpc.call('eth_call',[request,'latest'])
        estimate=int(self.rpc.call('eth_estimateGas',[request]),16)
        gas=(estimate*120+99)//100
        price=int(self.rpc.call('eth_gasPrice',[]),16)
        if gas>self.limits.max_gas_per_tx or price>self.limits.max_gas_price_wei:raise ValueError('Gas exceeds authorized limit')
        with self.store.transaction() as db:
            if db.execute('SELECT 1 FROM live_txs WHERE id=?',(key,)).fetchone():raise Pending('Concurrent transaction preparation; retry same intent')
            if db.execute('SELECT 1 FROM live_txs WHERE receipt IS NULL').fetchone():raise Pending('Resolve pending wallet transaction first')
            used=0
            for row in db.execute('SELECT reserved,receipt,tx FROM live_txs'):
                if row['receipt']:
                    r=json.loads(row['receipt']);t=json.loads(row['tx'])
                    used+=int(r['gasUsed'],16)*int(r['effectiveGasPrice'],16)+(t['value'] if int(r['status'],16)==1 else 0)
                else:used+=int(row['reserved'])
            reserve=value+gas*price
            exit_reserve=4*self.limits.max_gas_per_tx*self.limits.max_gas_price_wei if purpose=='BUY' else 0
            if used+reserve+exit_reserve>self.limits.max_total_outgoing_wei:raise ValueError('Total outgoing budget exceeded, including reserved exit/funding gas')
            if int(self.rpc.call('eth_getBalance',[self.limits.wallet,'latest']),16)<reserve:raise ValueError('Insufficient wallet balance')
            nonce=int(self.rpc.call('eth_getTransactionCount',[self.limits.wallet,'pending']),16)
            if nonce!=int(self.rpc.call('eth_getTransactionCount',[self.limits.wallet,'latest']),16):raise Pending('Wallet has an external pending transaction')
            tx={'chainId':4663,'nonce':nonce,'to':to_checksum_address(to),'data':data,'value':value,'gas':gas,'gasPrice':price}
            signed=self.signer.sign_transaction(tx);raw='0x'+signed.raw_transaction.hex();hashed='0x'+keccak(signed.raw_transaction).hex()
            db.execute('INSERT INTO live_txs VALUES (?,?,?,?,?,?,?,NULL)',(key,purpose,canonical(request),canonical(tx),raw,hashed,str(reserve)))
            Store.emit(db,'LIVE_TX_PREPARED',None,{'id':key,'purpose':purpose,'hash':hashed,'value':str(value),'fixture':self.limits.fixture})
        # Durable outbox committed before touching the network.
        self.rpc.call('eth_sendRawTransaction',[raw])
        return self.receipt(key)

    def gas_cost(self,receipt):return int(receipt['gasUsed'],16)*int(receipt['effectiveGasPrice'],16)
