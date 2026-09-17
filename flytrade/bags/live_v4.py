"""Pons V4 exact inventory exit via a dedicated, wallet-bound adapter.

Quotes/provenance reuse the existing V4ExitRouter. The adapter must be deployed
and its code hash/fly/manager/hook verified before enabling LIVE entries.
"""
import json
import time
from eth_abi import decode
from eth_utils import keccak
from .live_pons import calldata
from .config import address
from .economics import waterfall
from .store import Store,canonical

SOLD='0x'+keccak(text='Sold(address,bytes32,uint256,uint256)').hex()

class V4LiveExit:
    def __init__(self,sender,room,quoter,tapes,router,expected_code_hash,*,now=time.time):
        self.sender,self.room,self.rpc=sender,room,sender.rpc
        self.quoter,self.tapes,self.router,self.hash,self.now=quoter,tapes,address(router),expected_code_hash,now

    def verify(self):
        raw=self.rpc.call('eth_getCode',[self.router,'latest'])
        if '0x'+keccak(bytes.fromhex(raw[2:])).hex()!=self.hash:raise ValueError('V4 exit adapter bytecode mismatch')
        for name,expected in [('fly()',self.sender.limits.wallet),('manager()',self.quoter.registry['manager']['address']),('hook()',self.quoter.registry['hook']['address'])]:
            actual=self.rpc.call('eth_call',[{'to':self.router,'data':calldata(name)},'latest'])
            if decode(['address'],bytes.fromhex(actual[2:]))[0]!=address(expected):raise ValueError('V4 exit adapter binding mismatch')

    def sell(self,decision,bag_id,position):
        self.verify();entry=json.loads(position['entry']);token=position['token'];tokens=int(entry['amount_out'])
        tape=self.tapes[token]
        approval_key=decision+':v4approve';key=decision+':v4sell'
        approval=self.sender.transact(approval_key,'APPROVE',token,calldata('approve(address,uint256)',['address','uint256'],[self.router,tokens]))
        if self.sender.lookup(key):receipt=self.sender.receipt(key)
        else:
            quote=self.quoter.quote(tape,tokens,minimum_ts=int(self.now())-30)
            pool=quote['proof']['pool_key']
            if pool['currency0']!='0x'+'00'*20 or pool['currency1']!=token:raise ValueError('V4 exit requires native ETH/token pool')
            values=(pool['currency0'],pool['currency1'],pool['fee'],pool['tickSpacing'],pool['hooks'])
            minimum=int(quote['amount_out_wei'])*(10000-self.sender.limits.max_slippage_bps)//10000
            if not 0<tokens<2**127 or not 0<minimum<2**127:raise ValueError('V4 amount outside exact-input bounds')
            deadline=int(self.rpc.block('latest')['timestamp'],16)+120
            self.room.execution_state(bag_id,'SELLING')
            receipt=self.sender.transact(key,'SELL',self.router,
                calldata('sell((address,address,uint24,int24,address),uint128,uint128,uint64)',
                    ['(address,address,uint24,int24,address)','uint128','uint128','uint64'],[values,tokens,minimum,deadline]))
        logs=[l for l in receipt['logs'] if address(l['address'])==self.router and l['topics'][0].lower()==SOLD]
        if len(logs)!=1 or address('0x'+logs[0]['topics'][1][-40:])!=token:raise ValueError('Missing exact V4 exit evidence')
        amount,output=decode(['uint256','uint256'],bytes.fromhex(logs[0]['data'][2:]))
        if amount!=tokens:raise ValueError('V4 did not consume full inventory')
        gas=self.sender.gas_cost(approval)
        curve_approval=self.sender.lookup(decision+':approve')
        if curve_approval and curve_approval['receipt']:gas+=self.sender.gas_cost(json.loads(curve_approval['receipt']))
        stamp=int(self.rpc.block(int(receipt['blockNumber'],16))['timestamp'],16)
        fill={'side':'SELL','amount_in':str(amount),'amount_out':str(output),'fee':None,'tax':None,
            'fee_accounting':'Pons hook fees included in final native output; no fabricated separate breakdown',
            'gas':str(self.sender.gas_cost(receipt)),'tx_hash':receipt['transactionHash'],
            'block':int(receipt['blockNumber'],16),'block_hash':receipt['blockHash'],'ts':stamp,'route':'PONS_V4'}
        result=waterfall(spent=entry['amount_in'],received=fill['amount_out'],buy_gas=entry['gas'],sell_gas=fill['gas'],approval_gas=gas)
        result.update(entry=entry,exit=fill,execution='LIVE',fixture=self.sender.limits.fixture,learning='FROZEN')
        with self.sender.store.transaction() as db:
            db.execute('UPDATE live_positions SET closed=? WHERE decision=?',(canonical(result),decision))
            Store.emit(db,'LIVE_SELL_CONFIRMED',bag_id,result)
        return result
