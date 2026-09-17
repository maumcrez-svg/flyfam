"""Private Pons native-ETH transaction adapter. Fill evidence comes from receipts.

The frozen worker calls buy after committing its decision/snapshot. No public
endpoint reaches this class. Curve provenance is checked against the registered
factory, not a token's self-asserted factory getter.
"""
import json
from eth_abi import encode,decode
from eth_utils import keccak
from .config import address
from .live_rpc import Pending,TransactionFailed
from .store import Store,canonical
from .economics import waterfall
from flytrade.pons.curve import (CurveState,QuoteError,quote_curve_buy,quote_curve_sell,
    quote_curve_round_trip)

ZERO='0x'+'00'*20
LAUNCH_TYPES=['address','address','address','address','address','uint256','uint24','int24','uint16','bool','uint8','uint256','uint256','uint256','bool']
BUY_TOPIC='0x'+keccak(text='CurveBuy(address,address,uint256,uint256,uint256,uint256)').hex()
SELL_TOPIC='0x'+keccak(text='CurveSell(address,address,uint256,uint256,uint256,uint256)').hex()

def calldata(signature,types=(),values=()):return '0x'+(keccak(text=signature)[:4]+encode(types,values)).hex()


class EntryRefused(RuntimeError):
    """This entry was declined before anything was signed. Not a worker fault.

    Separate from :class:`Pending` (same intent, retry later) and from
    ``ValueError`` (stop with the outbox preserved): nothing was reserved, no
    nonce was allocated and the loop is free to look at the next candidate.
    """
    def __init__(self,reason,detail,evidence=None):
        super().__init__(reason+': '+detail)
        self.reason,self.detail,self.evidence=reason,detail,dict(evidence or {})


def round_trip_cost(state,amount):
    """View-only cost of buying ``amount`` and selling the tokens straight back.

    Both legs carry the curve's base fee and creator tax; the buy leg also
    carries the decaying snipe tax the state was read with. The denominator is
    what the buy actually spends (a clamped buy refunds the rest), and the bps
    are rounded **up**, so the number never understates the cost. Gas is not in
    it: this measures the venue, and the authorized gas ceiling is a separate
    limit. Returns ``(bps, evidence)`` with ``bps`` None when the curve cannot
    price the sell-back at all.
    """
    trip=quote_curve_round_trip(state,amount)
    buy=trip['buy'];sell=trip['sell']
    evidence={'route':trip['route'],'requested_wei':str(amount),'spent_wei':str(buy.spent),
        'refund_wei':str(buy.refund),'tokens_out_wei':str(buy.tokens_out),
        'buy_fee_base_wei':str(buy.fee_base),'buy_fee_creator_wei':str(buy.fee_creator),
        'buy_fee_snipe_wei':str(buy.fee_snipe),'fee_bps':state.fee_bps,
        'creator_tax_bps':state.creator_tax_bps,'snipe_tax_bps':state.snipe_tax_bps,
        'sell_quote_out_wei':None,'round_trip_cost_wei':None,'round_trip_bps':None}
    if sell is None or buy.spent<=0:return None,evidence
    cost=buy.spent-sell.quote_out
    bps=-((-cost*10000)//buy.spent) if cost>0 else 0
    evidence.update(sell_quote_out_wei=str(sell.quote_out),sell_fee_base_wei=str(sell.fee_base),
        sell_fee_creator_wei=str(sell.fee_creator),round_trip_cost_wei=str(cost),round_trip_bps=bps)
    return bps,evidence


def check_round_trip(state,amount,limit_bps):
    """L1 A3 gate. Raises :class:`EntryRefused`; never signs and never mutates."""
    try:bps,evidence=round_trip_cost(state,amount)
    except QuoteError as exc:
        raise EntryRefused('ROUND_TRIP_UNQUOTABLE',exc.code,{'limit_bps':limit_bps,'quote_error':exc.code}) from exc
    evidence['limit_bps']=limit_bps
    if bps is None:
        raise EntryRefused('ROUND_TRIP_UNQUOTABLE','the curve cannot price selling this entry back',evidence)
    if bps>limit_bps:
        raise EntryRefused('ROUND_TRIP_TOO_EXPENSIVE',
            f'the round trip costs {bps} bps of the entry principal and the authorized ceiling is {limit_bps} bps',evidence)
    return bps,evidence

class PonsLive:
    def __init__(self,sender,room,factory,expected_factory_hash,*,v4=None):
        self.sender,self.room,self.rpc=sender,room,sender.rpc
        self.factory,self.factory_hash=address(factory),expected_factory_hash
        self.v4=v4
        with sender.store.transaction() as db:
            db.execute('CREATE TABLE IF NOT EXISTS live_positions(decision TEXT PRIMARY KEY,token TEXT NOT NULL,curve TEXT NOT NULL,entry TEXT,closed TEXT)')
            db.execute('CREATE UNIQUE INDEX IF NOT EXISTS single_live_position ON live_positions((1)) WHERE closed IS NULL')

    def call(self,to,signature,types=(),values=(),outputs=('uint256',),block='latest'):
        return decode(outputs,bytes.fromhex(self.rpc.call('eth_call',[{'to':to,'data':calldata(signature,types,values)},block])[2:]))

    def route(self,token):
        token=address(token);header=self.rpc.block('latest');block=header['number']
        code=self.rpc.call('eth_getCode',[self.factory,block])
        if '0x'+keccak(bytes.fromhex(code[2:])).hex()!=self.factory_hash:raise ValueError('Pons factory bytecode mismatch')
        launch=self.call(self.factory,'getLaunchedToken(address)',['address'],[token],LAUNCH_TYPES,block)
        if not launch[-1] or launch[0]!=token or launch[4]!=ZERO:raise ValueError('Only verified Pons native-ETH launches supported')
        curve=launch[1]
        if self.call(curve,'token()',outputs=['address'],block=block)[0]!=token:raise ValueError('Curve token mismatch')
        if self.call(curve,'pairToken()',outputs=['address'],block=block)[0]!=ZERO:raise ValueError('Curve quote mismatch')
        return curve,block

    def state(self,curve,block):
        q,t=self.call(curve,'getReserves()',outputs=['uint256','uint256'],block=block)
        def read(name):return self.call(curve,name,block=block)[0]
        return CurveState(q,t,read('realQuoteReserve()'),read('sellableTokens()'),read('feeBps()'),read('creatorTaxBps()'),
            self.call(curve,'currentSnipeTaxBps(address)',['address'],[self.sender.limits.wallet],block=block)[0],bool(read('graduated()')))

    def fill(self,receipt,curve,side):
        topic=BUY_TOPIC if side=='BUY' else SELL_TOPIC;wallet=self.sender.limits.wallet
        logs=[l for l in receipt['logs'] if address(l['address'])==curve and l['topics'][0].lower()==topic]
        if len(logs)!=1:raise ValueError('Missing or ambiguous confirmed Pons fill')
        log=logs[0]
        if len(log['topics'])!=3 or any(address('0x'+t[-40:])!=wallet for t in log['topics'][1:]):raise ValueError('Fill recipient/sender mismatch')
        amount_in,amount_out,fee,tax=decode(['uint256']*4,bytes.fromhex(log['data'][2:]))
        header=self.rpc.block(int(receipt['blockNumber'],16))
        return {'side':side,'amount_in':str(amount_in),'amount_out':str(amount_out),'fee':str(fee),'tax':str(tax),
            'gas':str(self.sender.gas_cost(receipt)),'tx_hash':receipt['transactionHash'],
            'block':int(receipt['blockNumber'],16),'block_hash':receipt['blockHash'],'ts':int(header['timestamp'],16)}

    def buy(self,decision,token,amount):
        token=address(token)
        if amount>self.sender.limits.max_entry_wei:raise ValueError('Entry exceeds limit')
        self.room.prepare_entry(decision) # Before signing, receipt or public BAG_CREATED.
        with self.sender.store.read() as db:old=db.execute('SELECT * FROM live_positions WHERE decision=?',(decision,)).fetchone()
        if old and old['token']!=token:raise ValueError('Committed neural token cannot change')
        if old and old['entry']:return json.loads(old['entry'])
        curve,block=self.route(token)
        gate_key='live_round_trip:'+decision
        if not old:
            # L1 A3: price the exit before the entry, on the same read of the
            # same curve. Refused here, nothing is reserved and no row is
            # written, so the loop can look at the next candidate.
            _,evidence=check_round_trip(self.state(curve,block),amount,self.sender.limits.max_round_trip_bps)
            # Keep a bounded gas cushion for approval, sell and vault funding.
            reserve=4*self.sender.limits.max_gas_per_tx*self.sender.limits.max_gas_price_wei
            balance=int(self.rpc.call('eth_getBalance',[self.sender.limits.wallet,'latest']),16)
            if balance<amount+reserve:raise ValueError('Entry would consume exit/funding gas reserve')
            with self.sender.store.transaction() as db:
                db.execute('INSERT INTO live_positions(decision,token,curve) VALUES (?,?,?)',(decision,token,curve))
                Store.put(db,gate_key,evidence)
        else:
            with self.sender.store.read() as db:evidence=Store.get(db,gate_key,{})
        key=decision+':buy'
        if self.sender.lookup(key):receipt=self.sender.receipt(key)
        else:
            state=self.state(curve,block);quote=quote_curve_buy(state,amount)
            if quote.tokens_out>=state.sellable_tokens:raise ValueError('Entry would graduate curve')
            minimum=quote.tokens_out*(10000-self.sender.limits.max_slippage_bps)//10000
            if minimum==0:raise ValueError('Zero minimum output')
            receipt=self.sender.transact(key,'BUY',curve,calldata('buy(uint256,uint256,address)',['uint256','uint256','address'],[amount,minimum,self.sender.limits.wallet]),amount)
        fill=self.fill(receipt,curve,'BUY')
        # The measurement that authorized this entry travels with it: the OPEN
        # event carries the fill, and the settlement carries it again on CLOSE.
        fill['round_trip_bps']=evidence.get('round_trip_bps')
        fill['round_trip_limit_bps']=evidence.get('limit_bps')
        fill['round_trip_quote']=evidence or None
        with self.sender.store.transaction() as db:
            db.execute('UPDATE live_positions SET entry=? WHERE decision=?',(canonical(fill),decision))
            Store.emit(db,'LIVE_BUY_CONFIRMED',None,{'decision_id':decision,'fill':fill,'fixture':self.sender.limits.fixture})
        return fill

    def sell(self,decision,bag_id):
        with self.sender.store.read() as db:position=db.execute('SELECT * FROM live_positions WHERE decision=?',(decision,)).fetchone()
        if not position or not position['entry']:raise ValueError('No confirmed LIVE inventory')
        if position['closed']:return json.loads(position['closed'])
        with self.room.store.read() as db:bag=self.room._bag(db,bag_id)
        if not bag['exit_intent']:raise ValueError('Community has not requested exit')
        if json.loads(bag['entry']).get('decision_id')!=decision:raise ValueError('Exit bag does not own this position')
        entry=json.loads(position['entry']);tokens=int(entry['amount_out']);token=position['token'];curve=position['curve']
        key=decision+':sell';approval_key=decision+':approve'
        if self.sender.lookup(key):receipt=self.sender.receipt(key)
        else:
            curve,block=self.route(token);state=self.state(curve,block)
            if state.graduated or not state.sellable_tokens:
                if self.v4 is None:raise Pending('V4 LIVE route unavailable; inventory retained')
                return self.v4.sell(decision,bag_id,position)
            approval=self.sender.transact(approval_key,'APPROVE',token,calldata('approve(address,uint256)',['address','uint256'],[curve,tokens]))
            # Approval was finalized. Re-read quote before creating the sell transaction.
            curve,block=self.route(token);state=self.state(curve,block)
            quote=quote_curve_sell(state,tokens)
            minimum=quote.quote_out*(10000-self.sender.limits.max_slippage_bps)//10000
            if minimum==0:raise ValueError('Zero minimum output')
            self.room.execution_state(bag_id,'SELLING')
            receipt=self.sender.transact(key,'SELL',curve,calldata('sell(uint256,uint256,address)',['uint256','uint256','address'],[tokens,minimum,self.sender.limits.wallet]))
        fill=self.fill(receipt,curve,'SELL')
        if int(fill['amount_in'])!=tokens:raise ValueError('Exit did not consume exact inventory')
        approval=self.sender.receipt(approval_key)
        result=waterfall(spent=entry['amount_in'],received=fill['amount_out'],buy_gas=entry['gas'],sell_gas=fill['gas'],approval_gas=self.sender.gas_cost(approval))
        result.update(entry=entry,exit=fill,execution='LIVE',fixture=self.sender.limits.fixture,learning='FROZEN')
        with self.sender.store.transaction() as db:
            db.execute('UPDATE live_positions SET closed=? WHERE decision=?',(canonical(result),decision))
            Store.emit(db,'LIVE_SELL_CONFIRMED',bag_id,result)
        return result
