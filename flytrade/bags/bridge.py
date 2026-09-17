"""Worker-only adapter. Votes request exit; the existing confirmed PAPER executor closes."""
import json
from .store import Store,digest
from flytrade import execution as X
from flytrade.pons import paper as PAPER

class WorkerBridge:
    def __init__(self,room,run_id,brain_digest):
        self.room,self.run_id,self.brain_digest=room,run_id,brain_digest
    def event(self,event,*,entry_state=None):
        episode=event.get('episode_id')
        if episode is None:return
        episode_id=f'{event.get("run_id",self.run_id)}:{episode}'
        event_id=f'p1:{event.get("run_id",self.run_id)}:{event["seq"]}'
        kind=event['kind']
        if self.room.config.integration:
            if event.get('run_id')!=self.run_id or self.run_id!='pons-live' or event.get('execution')!='PAPER':raise ValueError('Real PAPER bridge source mismatch')
            event={**event,**self.room.config.sources,'canonical_event_hash':digest(event)}
        if entry_state:event={**event,**entry_state}
        if kind=='OPEN':
            self.room.create(event_id,episode_id,{**event,'brain_digest':self.brain_digest,'decision_id':f'{episode_id}:entry','execution':event.get('execution','PAPER')})
        elif kind=='CLOSE':
            if event.get('execution')=='LIVE':
                bag=self.room.active_for(episode_id)
                if not bag:raise ValueError('LIVE close without canonical bag')
                self.live_distributions.settle(bag['id'],event['live_settlement'])
            else:self.room.close(episode_id,event_id,event)
        elif kind=='MARK':self.room.market(episode_id,event)

    def adopt(self,position,history,*,pending=None):
        """Attach only an existing canonical position; never manufacture a fill."""
        if not position or not self.room.config.integration or pending:return False
        episode_id=f'{self.run_id}:{position.episode_id}'
        if self.room.active_for(episode_id):return True
        rows=history.events(episode=position.episode_id,kinds=['OPEN'],limit=2)
        if len(rows)!=1:raise ValueError('Current position has no unique canonical OPEN')
        row=rows[0];event=row['event']
        if (event['run_id']!=self.run_id or event['token']!=position.symbol or
            event['entry_block']!=position.entry.bar_index or event['entry_ts']!=position.entry.ts or
            event['quantity']!=position.quantity or event['entry_fill_price']!=position.entry.fill_price):
            raise ValueError('Recovered position and canonical OPEN disagree')
        self.event(event,entry_state={'entry_principal_eth':position.quantity*position.entry.fill_price+position.entry.fee,
            'entry_fee_unrounded_eth':position.entry.fee,'entry_cost_source':'RECOVERED_CANONICAL_WORKER_FILL'})
        with self.room.store.transaction() as db:
            bag=db.execute('SELECT id FROM bags WHERE episode_id=?',(episode_id,)).fetchone()
            Store.emit(db,'BAG_ADOPTED_EXISTING_POSITION',bag[0],{'source_event':row['event_id'],
                'episode_id':episode_id,'entry_unchanged':True,'new_exit_policy':'COMMUNITY'},self.room.now())
            Store.put(db,'legacy_episode',None)
        marks=history.events(episode=position.episode_id,kinds=['MARK'],limit=1000)
        if marks:self.event(marks[-1]['event'])
        return True


class CommunityExecution:
    """Mixin over ProductPaperExecution or V4PaperExecution, selected only by explicit config."""
    bag_room=None
    bag_run_id=None
    legacy_episode=None

    def mark(self,tape,cutoff,clock):
        mark=super().mark(tape,cutoff,clock)
        if self.bag_room and self.bag_room.config.test_autoexit_enabled:
            from .activity import observe
            mark['activity']=observe(self,tape,cutoff,clock,mark,self.bag_room.config.autoexit_idle_seconds)
            self.last_mark=dict(mark)
        return mark

    def _bag(self):
        p=self.account.position
        bag=self.bag_room.active_for(f'{self.bag_run_id}:{p.episode_id}') if p and self.bag_room else None
        if bag and bag['status']=='CLOSED':
            from flytrade.product.history import RecoveryError
            raise RecoveryError('Closed bag still appears in paper account; reconcile canonical close before restarting')
        return bag

    def due_for_horizon(self,cutoff):
        p=self.account.position
        if not p:return False
        bag=self._bag()
        if not bag:
            # Existing pre-activation positions retain their recorded policy. New bags fail closed.
            return super().due_for_horizon(cutoff) if p.episode_id==self.legacy_episode else False
        intent=json.loads(bag['exit_intent']) if bag['exit_intent'] else None
        if not intent:return False
        self.horizon_ts=int(intent['requested_at'])+self.latency_s
        if int(cutoff)<self.horizon_ts:return False
        return True

    @property
    def neural_exit_reject_reason(self):
        return X.RejectReason.COMMUNITY_CONTROLS_EXIT if self._bag() else X.RejectReason.FIXED_HOLD

    @property
    def exit_close_reason(self):
        bag=self._bag()
        if not bag:return X.CloseReason.POLICY_CLOSE_FIXED_HOLD
        intent=json.loads(bag['exit_intent']) if bag['exit_intent'] else {}
        return X.CloseReason.AUTO_EXIT if intent.get('source')=='AUTO_EXIT' else X.CloseReason.COMMUNITY_EXIT

    def plan_horizon_exit(self,tape,cutoff,clock):
        bag=self._bag()
        if bag:
            if not bag['exit_intent']:raise PAPER.Unresolved('NO_COMMUNITY_EXIT','No signed-vote result requests a sale')
            intent=json.loads(bag['exit_intent'])
            self.horizon_ts=int(intent['requested_at'])+self.latency_s
            if cutoff<self.horizon_ts:raise PAPER.Unresolved('EXIT_LATENCY_PENDING')
            self.bag_room.execution_state(bag['id'],'SELLING')
        try:return super().plan_horizon_exit(tape,cutoff,clock)
        except PAPER.Unresolved as exc:
            if bag:self.bag_room.execution_state(bag['id'],'PENDING',exc.reason)
            raise

    def open_long(self,**kwargs):
        reserved=self.bag_room.vault_reserved() if self.bag_room else 0
        if reserved and self.account.position is None:
            try:
                plan=self.plan_buy(kwargs['tape'],kwargs['cutoff'],kwargs['clock'])
                spend=plan.quantity*plan.fill_price+plan.fee
                if spend+(self.gas_sell_wei+self.gas_approval_wei)/PAPER.WEI>self.account.cash-reserved/PAPER.WEI:
                    return self.reject('BUY',kwargs['tape'].token,kwargs['cutoff'],X.RejectReason.INSUFFICIENT_CASH)
            except PAPER.Unresolved:
                pass  # Original executor reports the precise route failure.
        return super().open_long(**kwargs)
