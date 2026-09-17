"""Systematic first-observation follow-ups. No trades and no neural calls.

Every recorded filtered launch and every presented non-selected launch gets
5/15/30-minute windows, separately by category. Quotes use isolated canonical
paper quote primitives; they never touch the live account or reserve delta.
"""
import hashlib
import zlib
from .history import canonical, unpack
from ..pons import paper as PAPER
from ..pons.curve import QuoteError

WINDOWS=(300,900,1800)
COVERAGE_GRACE_SECONDS=300


def observe_window(target,window,*,tape,clock,fixed,confirmed_block):
    seen=int(target['seen_ts']); due=seen+window
    result={'price_move':None,'modeled_net_return':None,'modeled_net_wei':None,
            'price_available':False,'modeled_available':False,'reason':None,
            'window_seconds':window,'seen_ts':seen,'observation_ts':due,
            'execution':'HYPOTHETICAL_PAPER','method':'canonical curve quotes; isolated own impact'}
    if tape is None:
        return {**result,'reason':'CANONICAL_TAPE_UNAVAILABLE'}
    legacy_launch=(target.get('context') or {}).get('launched_at')
    if target.get('legacy') and (legacy_launch is None or
            due>int(legacy_launch)+int(fixed['track_seconds'])):
        return {**result,'reason':'LEGACY_OBSERVATION_WINDOW_NOT_COVERED'}
    if tape.inconsistent:
        return {**result,'reason':'INCONSISTENT_CANONICAL_STATE'}
    if tape.coverage_end_ts is None or tape.coverage_end_ts<due:
        return {**result,'retry':True,'reason':'AWAITING_CANONICAL_COVERAGE'}
    try:
        at=clock.block_at_or_after(due)
        if not at or confirmed_block is None or at['block_number']>confirmed_block:
            return {**result,'retry':True,'reason':'AWAITING_CONFIRMATION'}
    except (ValueError,KeyError):
        return {**result,'reason':'CANONICAL_CLOCK_UNAVAILABLE'}
    if tape.completed_by(due):
        return {**result,'reason':'ROUTE_COMPLETED_DATA_UNAVAILABLE'}
    state=tape.state_at(due)
    baseline=(target.get('context') or {}).get('marginal_price')
    if state is not None and state.token_reserve>0 and baseline and baseline>0:
        price=state.quote_reserve/state.token_reserve
        result.update(price_move=price/baseline-1,price_available=True,
                      baseline_price=baseline,observed_price=price,
                      price_evidence={'asof_ts':due,'coverage_confirmed_block':at['block_number'],'state':state.as_dict()})
    else:
        result['price_reason']='BASELINE_OR_WINDOW_PRICE_UNAVAILABLE'
    # This instance only prices two hypothetical legs. No account is opened.
    model=PAPER.PonsPaperExecution(size_wei=int(fixed['paper_size_wei']),
        latency_s=int(fixed['latency_seconds']),horizon_s=int(fixed['horizon_seconds']),
        gas_buy_wei=int(fixed['gas_wei']['buy']),gas_sell_wei=int(fixed['gas_wei']['sell']),
        gas_approval_wei=int(fixed['gas_wei']['approval']))
    try:
        entry=model.plan_buy(tape,seen,clock)
        model.own_delta[tape.curve]={'quote':entry.quote.net_into_curve,'tokens':entry.quote.tokens_out}
        exit=model.plan_sell(tape,due,entry.quantity,clock,tokens_wei=entry.quote.tokens_out)
        if max(entry.block_number,exit.block_number)>confirmed_block:
            return {**result,'retry':True,'reason':'AWAITING_CONFIRMATION'}
        cost=entry.quote.spent+model.gas_buy_wei
        value=exit.quote.quote_out-model.gas_sell_wei-model.gas_approval_wei
        net=value-cost
        result.update(modeled_available=True,modeled_net_return=net/model.size_wei,
            modeled_net_wei=str(net),entry_cost_wei=str(cost),exit_value_wei=str(value),
            paper_size_wei=str(model.size_wei),entry_ts=entry.block_timestamp,exit_ts=exit.block_timestamp,
            holding_seconds=exit.block_timestamp-entry.block_timestamp,
            quote_evidence={'entry_block':entry.block_number,'exit_block':exit.block_number,
                'tokens_wei':str(entry.quote.tokens_out),'entry_state':entry.state.as_dict(),
                'exit_state':exit.state.as_dict(),'entry_fees_wei':str(entry.quote.spent-entry.quote.net_into_curve),
                'exit_fees_wei':str(exit.quote.fee_base+exit.quote.fee_creator),
                'gas_wei':str(model.gas_buy_wei+model.gas_sell_wei+model.gas_approval_wei)})
    except (PAPER.Unresolved,QuoteError) as exc:
        result['modeled_reason']=getattr(exc,'reason',getattr(exc,'code','QUOTE_UNAVAILABLE'))
    return result


class Followups:
    def __init__(self,history,fixed):
        self.history=history;self.db=history.db;self.fixed=fixed
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS followup_targets (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE,token TEXT,curve TEXT,
                category TEXT,seen_ts INTEGER,source_seq INTEGER,payload BLOB NOT NULL);
            CREATE TABLE IF NOT EXISTS followup_windows (
                target TEXT,window INTEGER,due_ts INTEGER,status TEXT,
                result_seq INTEGER,price_move REAL,modeled_net_return REAL,payload BLOB,
                PRIMARY KEY(target,window));
            CREATE INDEX IF NOT EXISTS followup_due ON followup_windows(status,due_ts);
            CREATE INDEX IF NOT EXISTS followup_category ON followup_targets(category,seq);
        """)
        saved=history.state('followup_cursor')
        self.cursor=saved['value']['seq'] if saved else 0

    def _track(self,row,candidate,category,chosen=None):
        event=row['event']; context=candidate.get('context') or {}
        identity={'run_id':event.get('run_id','pons-live'),'chain_id':candidate.get('chain_id',4663),
            'token':candidate['token'],'curve':candidate.get('curve'),'category':category}
        key=hashlib.sha256(canonical(identity)).hexdigest()[:32]
        prior=self.db.execute('SELECT payload FROM followup_targets WHERE id=?',(key,)).fetchone()
        seen=int(candidate.get('observation_ts') or event['ts'])
        if prior:
            old=unpack(prior['payload'])
            # Upgrade the same observation if its full V2 record followed the
            # compatibility journal row. Never move its window to a later round.
            if not (old.get('legacy') and not event.get('legacy') and old['seen_ts']==seen
                    and old.get('source_round_id')==event.get('round_id')):
                return

        target={**identity,'id':key,'seen_ts':seen,'source_seq':row['seq'],
            'source_round_id':event.get('round_id'),'presentation_id':candidate.get('candidate_presentation_id'),
            'reasons':candidate.get('reasons') or [candidate.get('status','NOT_SELECTED')],
            'raw_score':candidate.get('raw_score'),'score_unit':candidate.get('unit'),
            'rank':candidate.get('rank'),'chosen_instead':chosen,'context':context,
            'method':'FIRST_RECORDED_OBSERVATION_PER_LAUNCH_AND_CATEGORY',
            'legacy':event.get('legacy',False)}
        if prior:
            target['source_seq']=old['source_seq']
            target['precision_upgrade_seq']=row['seq']
            self.db.execute('UPDATE followup_targets SET payload=? WHERE id=?',
                (zlib.compress(canonical(target)),key))
            return
        self.db.execute('INSERT INTO followup_targets(id,token,curve,category,seen_ts,source_seq,payload) VALUES (?,?,?,?,?,?,?)',
            (key,target['token'],target['curve'],category,seen,row['seq'],zlib.compress(canonical(target))))
        self.db.executemany('INSERT INTO followup_windows(target,window,due_ts,status) VALUES (?,?,?,?)',
            [(key,window,seen+window,'PENDING') for window in WINDOWS])

    def ingest(self,*,limit=1000):
        rows=self.history.events(after=self.cursor,limit=limit)
        previous=self.cursor
        try:
            with self.db:
                for row in rows:
                    event=row['event']
                    if event['kind']=='ROUND' and row['source']=='internal':
                        from .watchlist import legacy_round_event
                        legacy=legacy_round_event(event)
                        if legacy:
                            event=legacy;row={**row,'event':event}
                    if event['kind']=='SNIFF_ROUND':
                        for candidate in event['candidates']:
                            if candidate['eligibility_status'].startswith('FILTERED_'):
                                self._track(row,candidate,'FILTERED_OUT')
                    elif event['kind']=='WATCHLIST' and event['context']=='FLAT':
                        chosen=next((c['token'] for c in event['candidates'] if c['selected']),None)
                        for candidate in event['candidates']:
                            if candidate['neural_presented'] and not candidate['selected']:
                                self._track(row,candidate,'FLY_REJECTED',chosen)
                    self.cursor=row['seq']
                if rows:
                    self.db.execute('INSERT OR REPLACE INTO state VALUES (?,?,?)',
                        ('followup_cursor',self.cursor,zlib.compress(canonical({'seq':self.cursor}))))
        except Exception:
            self.cursor=previous
            raise
        return len(rows)

    def observation_pins(self,cutoff):
        return {row['curve']:row['until_ts']+COVERAGE_GRACE_SECONDS for row in
            self.db.execute("SELECT t.curve,max(w.due_ts) AS until_ts FROM followup_targets t "
                "JOIN followup_windows w ON w.target=t.id WHERE w.status='PENDING' "
                "AND t.curve IS NOT NULL AND w.due_ts>=? GROUP BY t.curve",
                (int(cutoff)-COVERAGE_GRACE_SECONDS,))}

    def resolve(self,*,cutoff,tapes,clock,confirmed_block,limit=128):
        rows=self.db.execute('SELECT w.target,w.window,t.payload FROM followup_windows w JOIN followup_targets t ON t.id=w.target '
            'WHERE w.status=? AND w.due_ts<=? ORDER BY w.due_ts,t.seq,w.window LIMIT ?',('PENDING',int(cutoff),int(limit))).fetchall()
        completed=0
        for row in rows:
            target=unpack(row['payload'])
            result=observe_window(target,row['window'],tape=tapes.get(target['token']),clock=clock,
                                  fixed=self.fixed,confirmed_block=confirmed_block)
            if result.get('retry'):
                if cutoff <= target['seen_ts']+row['window']+COVERAGE_GRACE_SECONDS:
                    continue
                result.pop('retry')
                result.update(reason='CANONICAL_COVERAGE_DEADLINE_EXCEEDED',
                    price_move=None,modeled_net_return=None,modeled_net_wei=None,
                    price_available=False,modeled_available=False)

            event={'kind':'FOLLOWUP','spectacle_feed_version':2,'ts':int(cutoff),
                   'target_id':target['id'],'token':target['token'],'curve':target['curve'],
                   'category':target['category'],'source_seq':target['source_seq'],
                   'seen_ts':target['seen_ts'],'result':result,'run_id':target['run_id']}
            with self.db:
                seq=self.history._append('followup:'+target['id']+':'+str(row['window']),event,
                    source='spectacle-v2',source_seq=None)
                self.db.execute('UPDATE followup_windows SET status=?,result_seq=?,price_move=?,modeled_net_return=?,payload=? WHERE target=? AND window=?',
                    ('COMPLETE',seq,result['price_move'],result['modeled_net_return'],zlib.compress(canonical(result)),row['target'],row['window']))
            completed+=1
        pending=self.db.execute("SELECT min(t.seen_ts) FROM followup_targets t JOIN followup_windows w ON w.target=t.id WHERE w.status='PENDING'").fetchone()[0]
        unconsumed=self.db.execute("SELECT min(ts) FROM events WHERE seq>? AND kind IN ('SNIFF_ROUND','WATCHLIST','ROUND')",(self.cursor,)).fetchone()[0]
        edge=min(int(cutoff),pending if pending is not None else int(cutoff),unconsumed if unconsumed is not None else int(cutoff))
        self.history.save_state('retention_watermark',{'canonical_seq':self.history.seq,
            'raw_consumed_through_ts':edge,'followup_source_cursor':self.cursor,
            'fixed_windows_seconds':list(WINDOWS)})
        return completed
