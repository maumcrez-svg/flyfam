"""One deterministic spectator projection. Accounting inputs are canonical.

This writer runs beside event production; HTTP readers never invoke it.
No RPC, neural, execution or filesystem-path endpoints belong here.
"""
from copy import deepcopy
import json
from pathlib import Path
import time
import zlib
from .history import canonical, unpack, RecoveryError

DEFAULT_RULES = Path(__file__).resolve().parents[2]/'product'/'spectacle_events.json'


def episode_key(event):
    return str(event.get('run_id','pons-live'))+':'+str(event['episode_id'])


def career_empty():
    return {'closed_positions':0,'wins':0,'losses':0,'neutral':0,
        'gross_reference_pnl_eth':0.0,'gross_fill_pnl_eth':0.0,'fees_eth':0.0,
        'slippage_eth':0.0,'net_pnl_eth':0.0,'closed_episode_net_pnl_eth':0.0,
        'account_reconciliation_delta_eth':0.0,'booked_realized_pnl_eth':None,
        'account_reconciliation_status':'NO_ACCOUNT_SNAPSHOT','current_streak':0,
        'longest_win_streak':0,'longest_loss_streak':0,'sniff_observations':0,
        'filtered_observations':0,'neural_presentations':0,'neural_not_selected':0,
        'pick_events':0,'execution_rejections':0,
        'best_return':None,'worst_return':None,'best_pnl':None,'worst_pnl':None,
        'paper_bankroll_eth':None,'migrations_after_buy':None,
        'migrations_after_rejection':None,'execution':'PAPER'}


class Projector:
    def __init__(self, history, rules=None):
        self.history=history
        self.db=history.db
        self.rules=rules or json.loads(DEFAULT_RULES.read_text())
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS episodes (
                id TEXT PRIMARY KEY, token TEXT, opened_seq INTEGER, closed_seq INTEGER,
                closed_ts INTEGER, net_return REAL, net_pnl REAL, peak_return REAL,
                giveback REAL, payload BLOB NOT NULL);
            CREATE INDEX IF NOT EXISTS episode_closed ON episodes(closed_ts,closed_seq);
            CREATE TABLE IF NOT EXISTS position_points (
                episode TEXT, seq INTEGER, ts INTEGER, net_return REAL, token_move REAL, payload BLOB NOT NULL,
                PRIMARY KEY(episode,seq));
            CREATE TABLE IF NOT EXISTS moments (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, event_key TEXT UNIQUE,
                source_seq INTEGER, episode TEXT, ts INTEGER, level INTEGER,
                kind TEXT, payload BLOB NOT NULL);
            CREATE INDEX IF NOT EXISTS moment_episode ON moments(episode,seq);
            CREATE TABLE IF NOT EXISTS projected_rounds (
                id TEXT PRIMARY KEY, presented INTEGER, not_selected INTEGER,
                payload BLOB NOT NULL);
        """)
        saved=history.state('presentation')
        self.state=saved['value'] if saved else {'seq':0,'version':2,'projection_schema':1,
            'rules_version':self.rules['version'],'phase':'SNIFFING','position_id':None,
            'last_pick':None,'watchlist':None,'sniff':None,'last_result_id':None,
            'last_feed_ts':None,'last_market_ts':None,'health':{},'career':career_empty()}
        if self.state.get('projection_schema')!=1:
            raise RecoveryError('Incompatible presentation projection schema')
        if self.state['rules_version']!=self.rules['version']:
            raise RecoveryError('Presentation rule change requires a versioned projection rebuild')

    def catch_up(self, *, limit=1000):
        rows=self.history.events(after=self.state['seq'],limit=limit)
        # A bounded batch publishes evidence-derived state and cursor atomically.
        # One durable commit per batch avoids an fsync for every historical tick.
        before=deepcopy(self.state)
        try:
            with self.db:
                for row in rows:
                    self.apply(row)
                    self.state['seq']=row['seq']
                if rows:
                    self.db.execute('INSERT OR REPLACE INTO state VALUES (?,?,?)',
                        ('presentation',self.state['seq'],zlib.compress(canonical(self.state))))
        except Exception:
            self.state=before
            raise
        return len(rows)

    def _episode(self, key):
        row=self.db.execute('SELECT payload FROM episodes WHERE id=?',(key,)).fetchone()
        return None if row is None else unpack(row[0])

    def _save_episode(self, episode):
        self.db.execute('INSERT OR REPLACE INTO episodes VALUES (?,?,?,?,?,?,?,?,?,?)',
            (episode['id'],episode['token'],episode.get('opened_seq'),episode.get('closed_seq'),
             episode.get('closed_ts'),episode.get('net_return'),episode.get('net_pnl_eth'),
             episode.get('peak_net_return'),episode.get('giveback_of_peak_profit'),
             zlib.compress(canonical(episode))))

    def _unavailable_mark(self, row, episode, event, *, source_kind):
        episode['last_mark']=event
        if episode.get('net_return') is not None:
            episode['last_observed_net_return']=episode['net_return']
        for field in ('net_return','net_pnl_eth','token_move',
                      'modeled_exit_value_eth','drawdown_from_peak_value',
                      'giveback_of_peak_profit'):
            episode[field]=None
        episode['mark_available']=False
        gap={'seq':row['seq'],'ts':event.get('cutoff_ts') or event.get('ts'),
             'net_return':None,'token_move':None,'available':False,
             'reason':event.get('reason'),'source_kind':source_kind}
        self.db.execute('INSERT OR IGNORE INTO position_points VALUES (?,?,?,?,?,?)',
            (episode['id'],row['seq'],gap['ts'],None,None,zlib.compress(canonical(gap))))

    def moment(self, row, kind, *, episode=None, level=1, **fields):
        event=row['event']
        key=str(row['seq'])+':'+kind
        data={'execution':event.get('execution',self.state.get('execution','PAPER')),'kind':kind,'source_seq':row['seq'],'episode_id':episode,
              'ts':event.get('cutoff_ts') or event.get('ts'),'level':level,**fields}
        self.db.execute('INSERT OR IGNORE INTO moments '
            '(event_key,source_seq,episode,ts,level,kind,payload) VALUES (?,?,?,?,?,?,?)',
            (key,row['seq'],episode,data['ts'],level,kind,zlib.compress(canonical(data))))

    def _round(self, row):
        event=row['event']
        key=event['round_id']
        rows=event['candidates']
        presented=sum(bool(c['neural_presented']) for c in rows)
        rejected=sum(bool(c['neural_presented'] and not c['selected']) for c in rows)
        prior=self.db.execute('SELECT presented,not_selected,payload FROM projected_rounds WHERE id=?',(key,)).fetchone()
        if prior and event.get('legacy') and not unpack(prior[2]).get('legacy'):
            return
        self.state['career']['neural_presentations']+=presented-(prior[0] if prior else 0)
        self.state['career']['neural_not_selected']+=rejected-(prior[1] if prior else 0)
        self.db.execute('INSERT OR REPLACE INTO projected_rounds VALUES (?,?,?,?)',
                        (key,presented,rejected,zlib.compress(canonical(event))))
        if event['context']=='FLAT':
            self.state['watchlist']=event
        # Historical metadata may be imported after its P1 public events.
        for candidate in rows:
            if candidate['selected']:
                ep_key=str(event['run_id'])+':'+str(candidate['episode_id'])
                episode=self._episode(ep_key)
                if episode and event['ts'] <= (episode.get('open') or {}).get('entry_ts',event['ts']):
                    episode['watchlist']=event
                    self._save_episode(episode)

    def apply(self, row):
        event=row['event']; kind=event['kind']; career=self.state['career']
        public=row['source'].startswith('p1:')
        if public and event.get('execution') in ('LIVE','PAPER'):
            self.state['execution']=event['execution'];career['execution']=event['execution']
        if kind=='SYSTEM_HEALTH':
            self.state['health']=event['health']
            return
        if kind=='WATCHLIST':
            self._round(row)
            return
        if kind=='SNIFF_ROUND':
            # Live projection stays bounded even though permanent admission evidence is complete.
            self.state['sniff']={**event,'candidates':event['candidates'][:30],
                                'candidates_in_history':len(event['candidates'])}
            return
        if kind=='OVERTAKE':
            self.moment(row,'OVERTAKE',token=event['token'],overtaken_token=event['overtaken_token'])
            return
        if not public:
            if kind=='ROUND' and row['source']=='internal':
                from .watchlist import legacy_round_event
                legacy=legacy_round_event(event)
                if legacy is not None:
                    self._round({**row,'event':legacy})
            return
        self.state['last_feed_ts']=event.get('ts',self.state['last_feed_ts'])
        cutoff=event.get('cutoff_ts')
        if cutoff is not None:
            self.state['last_market_ts']=max(cutoff,self.state['last_market_ts'] or cutoff)
        if kind=='SNIFF':
            career['sniff_observations']+=int(event.get('considered',0))
            career['filtered_observations']+=int(event.get('rejected',0))
            if not self.state['position_id']:
                self.state['phase']='SNIFFING'
            return
        if kind=='PICK':
            career['pick_events']+=1
            self.state['last_pick']={**event,'spectacle_seq':row['seq']}
            if event.get('rejection'):
                career['execution_rejections']+=1
                self.moment(row,'EXECUTION_REJECTED',token=event.get('token'),reason=event['rejection'])
                if not self.state['position_id']:
                    self.state['phase']='ENTRY_REJECTED'
            elif event.get('action')=='BUY' and not self.state['position_id']:
                self.state['phase']='PICK'
                self.moment(row,'PICK',level=2,token=event.get('token'),score=event.get('valence_hz'),unit='Hz')
            return
        if kind=='HEARTBEAT':
            # An unusable held token aborts its neural round, so old P1 workers
            # report the missing quote only in the heartbeat position snapshot.
            position=event.get('position') or {}
            mark=position.get('last_mark') or {}
            episode=self._episode(self.state['position_id']) if self.state['position_id'] else None
            if (episode and not episode.get('closed_seq')
                    and position.get('episode_id')==(episode.get('open') or {}).get('episode_id')
                    and position.get('token')==episode.get('token')
                    and mark.get('available') is False):
                self._unavailable_mark(row,episode,mark,source_kind='HEARTBEAT')
                self._save_episode(episode)
            self.state['health']={k:event.get(k) for k in ('head_block','cursor_block','cutoff_age_s',
                'throttled','errors','reorgs','pending_confirmation','brain_digest')}
            account=event.get('account') or {}
            self.state['paper_account']=account
            if account.get('execution')=='LIVE':
                career['live_bankroll_eth']=int(account.get('fly_bankroll_available_wei','0'))/1e18
                career['live_bankroll_wei']=account.get('fly_bankroll_available_wei')
            else:career['paper_bankroll_eth']=account.get('bankroll_equity_eth',account.get('equity_eth'))
            if event.get('launches_seen') is not None:
                career['launches_observed']=event['launches_seen']
            booked=account.get('realized_pnl_eth')
            career['booked_realized_pnl_eth']=booked
            career['account_snapshot_closed_positions']=account.get('trades')
            if booked is not None and account.get('trades')==career['closed_positions']:
                difference=booked-career['closed_episode_net_pnl_eth']
                career['account_reconciliation_delta_eth']=difference
                career['net_pnl_eth']=booked
                career['account_reconciliation_status']='MATCH' if abs(difference)<=1e-12 else 'SOURCE_PRECISION_DIFFERENCE'
            elif booked is not None:
                career['account_reconciliation_status']='INCOMPLETE_EPISODE_HISTORY'
            return
        if kind in ('RPC_ERROR','THROTTLED'):
            self.state['health']['last_operational_event']=event
            self.moment(row,kind,level=0,reason=event.get('reason') or event.get('code'))
            return
        if kind not in ('OPEN','MARK','CLOSE','CREDIT') or event.get('episode_id') is None:
            return
        key=episode_key(event)
        episode=self._episode(key)
        if kind=='OPEN':
            if episode and episode.get('open'):
                return
            watchlist=self.state['watchlist']
            if watchlist and not any(c['episode_id']==event['episode_id'] and c['selected'] for c in watchlist['candidates']):
                watchlist=None
            episode={'id':key,'token':event.get('token'),'open':event,'opened_seq':row['seq'],
                'watchlist':watchlist,'sniff':self.state.get('sniff'),
                'pick':self.state['last_pick'] if self.state['last_pick'] and self.state['last_pick'].get('episode_id')==event['episode_id'] else None,
                'execution':event.get('execution','PAPER'),'rules_version':self.rules['version'],'alerts':[],
                'net_return':None,'net_pnl_eth':None,'peak_net_return':None,'trough_net_return':None,
                'peak_token_move':None,'trough_token_move':None,'last_mark':None,
                'credit':None,'close':None,'replay_complete':True}
            self.state['position_id']=key; self.state['phase']='POSITION_OPEN'
            self.moment(row,'OPEN',episode=key,level=2,token=episode['token'],size_eth=event.get('size_eth'))
        elif episode is None:
            episode={'id':key,'token':event.get('token'),'open':None,'watchlist':None,
                'execution':event.get('execution','PAPER'),'rules_version':self.rules['version'],'alerts':[],
                'replay_complete':False,'incomplete_reason':'OPEN evidence unavailable',
                'peak_net_return':None,'trough_net_return':None,'peak_token_move':None,
                'trough_token_move':None,'credit':None,'close':None}
        if kind=='MARK':
            if episode.get('closed_seq'):
                return
            episode['last_mark']=event
            if event.get('available') and episode.get('open'):
                size=episode['open'].get('size_eth')
                net=event.get('unrealised_eth')
                ratio=net/size if net is not None and size else None
                self._point(row,episode,ratio,net,event.get('marginal_price'),event.get('mark_value_eth'))
                episode['mark_available']=True
                self._alerts(row,episode)
            else:
                self._unavailable_mark(row,episode,event,source_kind='MARK')
            self.state['phase']='POSITION'
        elif kind=='CLOSE':
            if episode.get('closed_seq'):
                return
            episode['close']=event; episode['closed_seq']=row['seq']
            episode['closed_ts']=event.get('exit_ts') or event.get('ts')
            self._point(row,episode,event.get('return_on_notional'),event.get('net_pnl_eth'),
                        event.get('exit_reference_price'),None)
            self._close_career(row,episode)
            episode['career_at_close']=deepcopy(career)
            self.state['position_id']=None; self.state['last_result_id']=key; self.state['phase']='RESULT'
            self.moment(row,'CLOSE',episode=key,level=2,token=episode['token'],
                net_return=episode.get('net_return'),net_pnl_eth=event.get('net_pnl_eth'))
        elif kind=='CREDIT':
            episode['credit']=event
            episode['credit_seq']=row['seq']
            self.state['phase']='CONSEQUENCE'
            self.moment(row,'CREDIT',episode=key,level=2,token=episode['token'],
                        label=event.get('label'),memory='FROZEN' if event.get('applied') is False else 'UNKNOWN',applied=event.get('applied'))
        self._save_episode(episode)

    def _point(self,row,episode,ratio,net,price,value):
        event=row['event']; opened=episode.get('open') or {}
        ref=opened.get('entry_reference_price')
        move=price/ref-1 if price is not None and ref else None
        episode['net_return']=ratio; episode['net_pnl_eth']=net
        cost=(episode.get('last_mark') or {}).get('cost_eth')
        if value is None and net is not None and cost is not None:
            value=cost+net
        episode['token_move']=move; episode['modeled_exit_value_eth']=value
        for name,observation,fn in (('peak_net_return',ratio,max),('trough_net_return',ratio,min),
                ('peak_token_move',move,max),('trough_token_move',move,min)):
            if observation is not None:
                old=episode.get(name)
                episode[name]=observation if old is None else fn(old,observation)
        peak=episode.get('peak_net_return')
        if peak is not None and peak>0 and ratio is not None:
            episode['giveback_of_peak_profit']=(peak-ratio)/peak
        cost=(episode.get('last_mark') or {}).get('cost_eth')
        size=opened.get('size_eth')
        peak_value=cost+peak*size if cost is not None and peak is not None and size else None
        episode['drawdown_from_peak_value']=(value/peak_value-1 if value is not None and peak_value else None)
        point={'seq':row['seq'],'ts':event.get('exit_ts') or event.get('cutoff_ts') or event.get('ts'),
               'net_return':ratio,'net_pnl_eth':net,'reference_price':price,'token_move':move,
               'modeled_exit_value_eth':value,'source_kind':event['kind']}
        self.db.execute('INSERT OR IGNORE INTO position_points VALUES (?,?,?,?,?,?)',
            (episode['id'],row['seq'],point['ts'],ratio,move,zlib.compress(canonical(point))))

    def _alerts(self,row,episode):
        ratio=episode.get('net_return')
        if ratio is None:
            return
        seen=set(episode['alerts'])
        for thresholds,direction in ((self.rules['positive_net_return'],'UP'),(self.rules['negative_net_return'],'DOWN')):
            crossed=[v for v in thresholds if (ratio>=v if direction=='UP' else ratio<=v)
                     and f'{direction}:{v}' not in seen]
            if crossed:
                threshold=crossed[-1]
                self.moment(row,'RETURN_'+direction,episode=episode['id'],token=episode['token'],threshold=threshold,net_return=ratio)
                seen.update(f'{direction}:{v}' for v in crossed)
        peak=episode.get('peak_net_return') or 0
        if peak>=self.rules['meaningful_positive_peak']:
            if episode.get('giveback_of_peak_profit',0)>=self.rules['giveback_fraction'] and 'GIVEBACK' not in seen:
                self.moment(row,'GIVEBACK',episode=episode['id'],token=episode['token'],peak=peak,net_return=ratio)
                seen.add('GIVEBACK')
            if abs(ratio)<=self.rules['breakeven_band'] and 'BREAKEVEN' not in seen:
                self.moment(row,'BREAKEVEN',episode=episode['id'],token=episode['token'],peak=peak,net_return=ratio)
                seen.add('BREAKEVEN')
        episode['alerts']=sorted(seen)

    def _close_career(self,row,episode):
        event=row['event']; career=self.state['career']; net=event.get('net_pnl_eth')
        if net is None:
            raise RecoveryError('CLOSE has no canonical net paper result')
        previous_count=career['closed_positions']; career['closed_positions']+=1
        career['account_reconciliation_status']='AWAITING_ACCOUNT_SNAPSHOT'
        sign=1 if net>0 else -1 if net<0 else 0
        career['wins' if sign>0 else 'losses' if sign<0 else 'neutral']+=1
        old=career['current_streak']
        career['current_streak']=(old+sign if old*sign>0 else sign) if sign else 0
        career['longest_win_streak']=max(career['longest_win_streak'],career['current_streak'])
        career['longest_loss_streak']=max(career['longest_loss_streak'],-career['current_streak'])
        for dest,source in (('gross_reference_pnl_eth','gross_reference_pnl_eth'),('gross_fill_pnl_eth','gross_pnl_eth'),
                ('fees_eth','fees_eth'),('slippage_eth','slippage_eth'),('closed_episode_net_pnl_eth','net_pnl_eth')):
            value=event.get(source)
            if value is not None:
                career[dest]+=value
        career['net_pnl_eth']=career['closed_episode_net_pnl_eth']+career['account_reconciliation_delta_eth']
        career['total_costs_eth']=career['fees_eth']+career['slippage_eth']
        for name,value,better in (('best_return',episode.get('net_return'),lambda a,b:a>b),
                ('worst_return',episode.get('net_return'),lambda a,b:a<b),
                ('best_pnl',net,lambda a,b:a>b),('worst_pnl',net,lambda a,b:a<b)):
            old=career[name]
            if value is not None and (old is None or better(value,old['value'])):
                career[name]={'episode_id':episode['id'],'token':episode['token'],'value':value,'source_seq':row['seq']}
                if previous_count and name in ('best_return','worst_return'):
                    self.moment(row,'RECORD_'+name.upper(),episode=episode['id'],level=2,token=episode['token'],value=value)
