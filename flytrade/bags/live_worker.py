"""LIVE adapter for the existing frozen neural loop. Entry remains a neural decision.

The float Account/Fill objects are compatibility views for existing instrumentation;
real settlement and holder liabilities use receipt base units exclusively.
"""
import json
from pathlib import Path
from types import SimpleNamespace
from flytrade import execution as X,records as REC
from flytrade.product.live import ProductPaperExecution,ProductLoop
from flytrade.pons import paper as PAPER
from flytrade.pons.curve import quote_curve_sell
from .bridge import CommunityExecution
from .live_pons import EntryRefused
from .live_rpc import Pending,TransactionFailed
from .store import Store,canonical

class LiveExecution(CommunityExecution,ProductPaperExecution):
    execution_mode='LIVE'
    version='pons_live_receipts_v1'
    engine=None
    distributions=None
    last_live_settlement=None

    def refresh_account(self,extra_liability=0):
        balance=int(self.engine.rpc.call('eth_getBalance',[self.engine.sender.limits.wallet,'finalized']),16)
        with self.engine.sender.store.read() as db:
            position=db.execute('SELECT entry FROM live_positions WHERE closed IS NULL').fetchone()
        with self.bag_room.store.read() as db:
            liabilities=[json.loads(r[0]) for r in db.execute("SELECT evidence FROM bag_distributions WHERE status='AWAITING_FUNDING'")]
        pending=sum(int(e['funded_amount']) for e in liabilities)+int(extra_liability)
        deployed=int(json.loads(position[0])['amount_in']) if position and position[0] else 0
        self.account.cash=(balance-pending)/10**18
        projection={'execution':'LIVE','asset':'ETH','wallet_balance_wei':str(balance),
            'fly_bankroll_available_wei':str(balance-pending),'fly_bankroll_deployed_wei':str(deployed),
            'fly_bankroll_pending_settlement_wei':str(pending),'holder_liability_in_wallet_wei':str(pending),
            'source':'native balance less unfunded bag liabilities; deployed amount from confirmed receipts'}
        with self.bag_room.store.transaction() as db:Store.put(db,'live_bankroll',projection)
        return projection

    def open_long(self,*,episode_id,tape,stable_id,cutoff,clock):
        if self.account.position:
            if self.account.position.episode_id!=episode_id:raise ValueError('Another LIVE position is open')
            return self.account.position
        decision=f'{self.bag_run_id}:{episode_id}:entry'
        fill=self.engine.buy(decision,tape.token,self.size_wei)
        self.last_live_entry=fill
        quantity=int(fill['amount_out'])/10**18
        net=int(fill['amount_in'])-int(fill['fee'])-int(fill['tax'])
        fee=(int(fill['gas'])+int(fill['fee'])+int(fill['tax']))/10**18
        price=net/int(fill['amount_out'])
        entry=X.Fill(side=X.Side.BUY,symbol=tape.token,bar_index=fill['block'],ts=fill['ts'],reference_price=price,
            fill_price=price,quantity=quantity,fee=fee,delay_minutes=max(0,fill['ts']-cutoff),flag='LIVE_RECEIPT')
        self.account.cash=int(self.engine.rpc.call('eth_getBalance',[self.engine.sender.limits.wallet,'latest']),16)/10**18
        self.account.fees_paid+=fee
        self.account.position=X.Position(episode_id=int(episode_id),symbol=tape.token,stable_id=int(stable_id),entry=entry,horizon_bar=fill['block'],day=tape.curve)
        self.entry_tokens_wei=int(fill['amount_out']);self.entry_cutoff=cutoff;self.horizon_ts=None
        return self.account.position

    def plan_horizon_exit(self,tape,cutoff,clock):
        bag=self._bag()
        if not bag or not bag['exit_intent']:raise PAPER.Unresolved('NO_COMMUNITY_EXIT')
        decision=f'{self.bag_run_id}:{self.account.position.episode_id}:entry'
        try:result=self.engine.sell(decision,bag['id'])
        except (Pending,TransactionFailed,ValueError) as exc:raise PAPER.Unresolved('LIVE_EXIT_PENDING',str(exc)) from exc
        self.last_live_settlement=result
        fill=result['exit'];quantity=self.account.position.quantity
        fees=(int(result['sell_gas'])+int(result['approval_gas'])+int(result['failed_gas']))/10**18
        # Curve fee/tax already reduce received amount. This compatibility price is net of them.
        price=int(fill['amount_out'])/10**18/quantity
        return SimpleNamespace(block_number=fill['block'],block_timestamp=fill['ts'],quantity=quantity,
            fill_price=price,reference_price=price,fee=fees,delay_s=0)

    def close(self,*,tape,reason,cutoff,clock):
        position=self.account.position
        plan=self.plan_horizon_exit(tape,cutoff,clock)
        fill=X.Fill(side=X.Side.SELL,symbol=position.symbol,bar_index=plan.block_number,ts=plan.block_timestamp,
            reference_price=plan.reference_price,fill_price=plan.fill_price,quantity=plan.quantity,fee=plan.fee,delay_minutes=0,flag='LIVE_RECEIPT')
        # Actual wallet deposits, funding gas and sweeps do not obey the PAPER
        # identity cash=initial+PnL. Settlement base units remain authoritative.
        result=self.last_live_settlement
        net=int(result['net_realized_pnl'])/10**18
        fees=position.entry.fee+fill.fee
        outcome=X.OutcomeRecord(episode_id=position.episode_id,symbol=position.symbol,stable_id=position.stable_id,
            entry=position.entry,exit=fill,close_reason=reason,gross_pnl=net+fees,fees=fees,net_pnl=net,
            notional=int(result['entry_principal'])/10**18,bars_held=fill.bar_index-position.entry.bar_index,
            market_seconds_held=fill.ts-position.entry.ts,market_minutes_held=(fill.ts-position.entry.ts)//60,
            gross_reference_pnl=net+fees,execution_version=self.version)
        self.account.position=None
        self.account.fees_paid+=fill.fee;self.account.realized_pnl+=net;self.account.trades+=1
        self.outcomes.append(outcome)
        self.refresh_account(result['holder_profit'])
        self.entry_tokens_wei=None;self.horizon_ts=None;self.entry_cutoff=None
        return outcome

    def mark(self,tape,cutoff,clock):
        position=self.account.position
        if not position:return {}
        try:
            curve,block=self.engine.route(tape.token);state=self.engine.state(curve,block)
            if state.graduated or not state.sellable_tokens:
                quote=self.engine.v4.quoter.quote(tape,self.entry_tokens_wei,minimum_ts=cutoff)
                value=int(quote['amount_out_wei'])
            else:value=quote_curve_sell(state,self.entry_tokens_wei).quote_out
            estimate=(self.engine.sender.limits.max_gas_per_tx*self.engine.sender.limits.max_gas_price_wei*2)
            cost=position.quantity*position.entry.fill_price+position.entry.fee
            self.last_mark={'available':True,'block_number':int(block,16),'cutoff_ts':cutoff,
                'mark_value_eth':(value-estimate)/10**18,'cost_eth':cost,'unrealised_eth':(value-estimate)/10**18-cost,
                'estimated_exit_gas_wei':str(estimate),'estimate_kind':'conservative authorized gas ceiling',
                'execution':'LIVE','is_a_reward':False}
        except Exception as exc:self.last_mark={'available':False,'cutoff_ts':cutoff,'reason':'LIVE_MARK_UNAVAILABLE','detail':type(exc).__name__}
        return self.last_mark

    def fund_pending(self):
        try:self.distributions.tick()
        except (Pending,ValueError,TransactionFailed):pass
        with self.bag_room.store.read() as db:
            row=db.execute("SELECT bag_id FROM bag_distributions WHERE status='AWAITING_FUNDING' ORDER BY bag_id LIMIT 1").fetchone()
        if not row:
            self.refresh_account()
            return
        try:self.distributions.fund(row[0])
        except (Pending,ValueError,TransactionFailed):return # Liability remains; entries stay blocked.
        self.refresh_account()

class LiveProductLoop(ProductLoop):
    def _tick_flat(self,cutoff,tick):
        self.x.fund_pending()
        with self.x.engine.sender.store.read() as db:pending=Store.get(db,'live_entry_request')
        if pending:
            self.global_tick=self.tick_offset+int(tick)
            try:return self._resume_live_entry(pending,tick)
            finally:self._end_of_tick(cutoff)
        with self.x.bag_room.store.read() as db:
            if db.execute("SELECT 1 FROM bag_distributions WHERE status='AWAITING_FUNDING'").fetchone():
                self._end_of_tick(cutoff)
                return
        return super()._tick_flat(cutoff,tick)

    def _tick_holding(self,cutoff,tick,held):
        with self.x.engine.sender.store.read() as db:request=Store.get(db,'live_entry_request')
        if request:self._resume_live_entry(request,tick)
        return super()._tick_holding(cutoff,tick,held)

    def commit_live_entry(self,rec,traces,candidate,cutoff,tick):
        decision=f'{self.x.bag_run_id}:{rec.episode_id}:entry'
        try:self.x.bag_room.prepare_entry(decision)
        except (ValueError,Pending):return # No signature or public bag while index is unavailable.
        path=self.journal.dir/'live-entry.npz'
        REC.write_pending(path,episode_id=rec.episode_id,symbol=rec.symbol,stable_id=rec.stable_id,
            trace=traces,decision_bar=rec.bar_index,graph_sha256=self.journal.versions.graph_sha256)
        request={'record':rec.as_dict(),'extra':self._chain_extra(candidate),'trace_path':str(path),
            'cutoff':cutoff,'decision':decision,'publication_seq':self.journal.product_history.seq}
        with self.x.engine.sender.store.transaction() as db:Store.put(db,'live_entry_request',request)
        return self._resume_live_entry(request,tick)

    def _refuse_live_entry(self,request,rec,refusal):
        """An entry declined before signing. Published through the existing
        DECISION ``rejection`` field, so the feed shows EXECUTION_REJECTED and
        no OPEN is ever written. No bag, no nonce, no inventory."""
        rec.rejection={'kind':'LIVE_ENTRY_REFUSED','reason':refusal.reason,
            'detail':refusal.detail,'evidence':refusal.evidence}
        history=self.journal.product_history
        rows=history.events(after=request['publication_seq'],limit=1000,kinds=['PICK'])
        published={r['event']['kind'] for r in rows if r['event'].get('episode_id')==rec.episode_id}
        if 'PICK' not in published:self.journal.record_decision(rec,extra=request['extra'])
        with self.x.engine.sender.store.transaction() as db:
            Store.emit(db,'LIVE_ENTRY_REFUSED',None,{'decision_id':request['decision'],'token':rec.symbol,
                'episode_id':rec.episode_id,'reason':refusal.reason,'detail':refusal.detail,
                'evidence':refusal.evidence,'fixture':self.x.engine.sender.limits.fixture})
            Store.put(db,'live_entry_request',None)
        REC.clear_pending(request['trace_path'])
        return None

    def _resume_live_entry(self,request,tick):
        rec=REC.DecisionRecord(**request['record']);tape=self.tapes.get(rec.symbol)
        if tape is None:return # Wait for canonical discovery/coverage, never substitute another token.
        pending=REC.read_pending(request['trace_path'],graph_sha256=self.journal.versions.graph_sha256)
        if not pending or pending['episode_id']!=rec.episode_id:raise ValueError('Missing committed LIVE decision trace')
        try:opened=self.x.open_long(episode_id=rec.episode_id,tape=tape,stable_id=rec.stable_id,cutoff=request['cutoff'],clock=self.driver.block_clock)
        except Pending:return
        except EntryRefused as refusal:return self._refuse_live_entry(request,rec,refusal)
        # ValueError/reverted tx stop the worker with the signed outbox preserved.
        # Automatic new-nonce retry/cancellation is never inferred from an RPC error.
        history=self.journal.product_history
        rows=history.events(after=request['publication_seq'],limit=1000,kinds=['PICK','OPEN'])
        published={r['event']['kind'] for r in rows if r['event'].get('episode_id')==rec.episode_id}
        if 'PICK' not in published:self.journal.record_decision(rec,extra=request['extra'])
        if 'OPEN' not in published:
            self.journal.open_episode(rec,pending['traces'],{**opened.entry.as_dict(),'market_ts':opened.entry.ts,
                'token':tape.token,'curve':tape.curve,'block_number':opened.entry.bar_index,'cutoff_ts':request['cutoff'],
                'horizon_ts':None,'tokens_out_wei':str(self.x.entry_tokens_wei),'branch':self.branch,
                'execution':'LIVE','entry_receipt':self.x.last_live_entry})
        with self.x.engine.sender.store.transaction() as db:Store.put(db,'live_entry_request',None)
        REC.clear_pending(request['trace_path'])
        self.tally.after_execution['BUY']+=1
