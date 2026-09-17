"""Bounded read-only views of the single product projection."""
from copy import deepcopy
import time
from .history import unpack


class Views:
    def __init__(self, history, *, now=None, stale_after=90):
        self.history=history; self.db=history.db
        self.now=now or time.time; self.stale_after=int(stale_after)

    def state(self):
        row=self.history.state('presentation')
        return None if row is None else row['value']

    def health(self):
        state=self.state() or {}
        now=int(self.now())
        feed=state.get('last_feed_ts'); market=state.get('last_market_ts')
        feed_age=None if feed is None else max(0,now-feed)
        market_age=None if market is None else max(0,now-market)
        status=('OFFLINE' if feed is None else 'STALE' if market is None
                or feed_age>self.stale_after or market_age>self.stale_after else 'LIVE')
        return {**state.get('health',{}),'status':status,'feed_age_s':feed_age,
            'last_feed_ts':feed,'last_market_ts':market,
            'market_age_s':market_age,'market_fresh':market_age is not None and market_age<=self.stale_after,
            'heartbeat_recent':feed_age is not None and feed_age<=self.stale_after,
            'worker_running':None,'projected_seq':state.get('seq',0),
            'canonical_seq':self.history.seq,'execution':state.get('execution','PAPER')}

    def live(self):
        state=self.state()
        if state is None:
            return {'spectacle_feed_version':2,'seq':0,'mode':'LIVE','health':self.health(),
                    'phase':'OFFLINE','position':None,'watchlist':None,'sniff':None}
        return {'spectacle_feed_version':2,'seq':state['seq'],'mode':'LIVE','execution':state.get('execution','PAPER'),
            'health':self.health(),'phase':state['phase'],'position':self.position(),
            'watchlist':self.watchlist(),'sniff':state.get('sniff'),
            'last_pick':state.get('last_pick'),'last_result_id':state.get('last_result_id'),
            'paper_account':state.get('paper_account')}

    def watchlist(self):
        state=self.state() or {}; watchlist=state.get('watchlist'); sniff=state.get('sniff')
        if watchlist and sniff and watchlist['round_id']!=sniff['round_id'] and not state.get('position_id'):
            return {'measurement_state':sniff['measurement_state'],'round_id':sniff['round_id'],
                    'candidates':[],'previous_completed_round':watchlist['round_id']}
        return watchlist

    def career(self):
        state=self.state()
        if state is None:
            return None
        records=self.missed_records()
        return {**state['career'],'biggest_miss':records.get('BIGGEST_MISS'),
                'biggest_avoided_disaster':records.get('BEST_SAVE')}

    def position(self):
        state=self.state() or {}; key=state.get('position_id')
        if key is None:
            return None
        row=self.db.execute('SELECT payload FROM episodes WHERE id=?',(key,)).fetchone()
        if row is None:
            return None
        episode=unpack(row[0]); opened=episode.get('open') or {}; now=int(self.now())
        horizon=opened.get('horizon_ts'); entry=opened.get('entry_ts')
        return {**episode,'elapsed_s':max(0,now-entry) if entry is not None else None,
            'seconds_remaining':max(0,horizon-now) if horizon is not None else None,
            'policy_horizon_elapsed':horizon is not None and now>=horizon,
            'exit_policy':'COMMUNITY' if opened.get('exit_policy')=='COMMUNITY' else 'FIXED_HOLD_900_SECONDS','return_basis':'canonical net PnL / paper notional',
            **self.chart_points(key)}

    def points(self,key,*,after=0,limit=200,through=None):
        limit=min(1000,max(1,int(limit)))
        clause='episode=? AND seq>?'; args=[key,int(after)]
        if through is not None:
            clause+=' AND seq<=?'; args.append(int(through))
        rows=self.db.execute('SELECT seq,payload FROM position_points WHERE '+clause+' ORDER BY seq LIMIT ?',[*args,limit+1]).fetchall()
        return {'items':[unpack(row['payload']) for row in rows[:limit]],
                'next_cursor':rows[limit-1]['seq'] if len(rows)>limit else None}

    def chart_points(self,key,*,through=None,limit=200):
        """Bounded observed envelope, including the latest point and each bucket's extrema.

        No invented prices: omitted observations break the drawn line. The raw
        /points endpoint remains paginated and lossless. All queries respect the
        replay cursor before selecting extrema, so future outcomes cannot leak.
        """
        limit=min(1000,max(4,int(limit)))
        page=self.points(key,limit=limit,through=through)
        if page['next_cursor'] is None:
            return {'points':page['items'],'points_complete':True,'points_next_cursor':None}
        clause='episode=?'; args=[key]
        if through is not None:
            clause+=' AND seq<=?'; args.append(int(through))
        count=self.db.execute('SELECT count(*) FROM position_points WHERE '+clause,args).fetchone()[0]
        buckets=max(1,limit//4); width=(count+buckets-1)//buckets
        rows=self.db.execute("""
            WITH numbered AS (
                SELECT seq,net_return,row_number() OVER (ORDER BY seq) AS n
                FROM position_points WHERE """+clause+"""
            ), bucketed AS (
                SELECT *, (n-1)/? AS bucket FROM numbered
            ), ranked AS (
                SELECT *,
                    row_number() OVER (PARTITION BY bucket ORDER BY seq) AS first,
                    row_number() OVER (PARTITION BY bucket ORDER BY seq DESC) AS last,
                    row_number() OVER (PARTITION BY bucket ORDER BY net_return IS NULL,net_return,seq) AS low,
                    row_number() OVER (PARTITION BY bucket ORDER BY net_return IS NULL,net_return DESC,seq) AS high
                FROM bucketed
            ) SELECT seq,n FROM ranked WHERE first=1 OR last=1 OR low=1 OR high=1 ORDER BY seq
            """,[*args,width]).fetchall()
        points=[]; previous=None
        for row in rows:
            point=unpack(self.db.execute('SELECT payload FROM position_points WHERE episode=? AND seq=?',
                (key,row['seq'])).fetchone()[0])
            if previous is not None and row['n']!=previous+1:
                point['break_before']=True
            points.append(point); previous=row['n']
        return {'points':points,'points_complete':False,'points_next_cursor':None,
                'points_selection':'OBSERVED_BUCKET_EXTREMA_WITH_EXPLICIT_GAPS'}

    def episode(self,key,*,through=None):
        row=self.db.execute('SELECT payload FROM episodes WHERE id=?',(key,)).fetchone()
        if row is None:
            return None
        episode=unpack(row[0])
        if through is not None:
            through=int(through)
            if episode.get('opened_seq') is not None and episode['opened_seq']>through:
                return None
            if (episode.get('closed_seq') or 2**63)>through:
                for field in ('close','closed_seq','closed_ts','career_at_close'):
                    episode.pop(field,None)
            if (episode.get('credit_seq') or 2**63)>through:
                episode['credit']=None
                episode.pop('credit_seq',None)
            # Snapshot metrics must not expose the final result during replay.
            for field in ('net_return','net_pnl_eth','token_move','modeled_exit_value_eth',
                          'peak_net_return','trough_net_return','peak_token_move','trough_token_move',
                          'giveback_of_peak_profit','drawdown_from_peak_value','last_mark','alerts',
                          'mark_available','last_observed_net_return'):
                episode.pop(field,None)
        episode.update(self.chart_points(key,through=through))
        if through is not None:
            latest=self.db.execute('SELECT payload FROM position_points WHERE episode=? AND seq<=? ORDER BY seq DESC LIMIT 1',(key,through)).fetchone()
            if latest:
                last=unpack(latest[0])
                for field in ('net_return','net_pnl_eth','token_move','modeled_exit_value_eth'):
                    episode[field]=last.get(field)
            extrema=self.db.execute('SELECT max(net_return),min(net_return),max(token_move),min(token_move) '
                'FROM position_points WHERE episode=? AND seq<=?',(key,through)).fetchone()
            for field,value in zip(('peak_net_return','trough_net_return','peak_token_move','trough_token_move'),extrema):
                episode[field]=value
        episode['mode']='REPLAY'
        episode['story']=self.story(episode=key,through=through,limit=100)['items']
        return episode

    def story(self,*,after=None,limit=50,episode=None,through=None):
        limit=min(200,max(1,int(limit))); clauses=['seq>?']; args=[int(after or 0)]
        if episode is not None:
            clauses.append('episode=?'); args.append(episode)
        if through is not None:
            clauses.append('source_seq<=?'); args.append(int(through))
        latest=after is None and episode is None
        rows=self.db.execute('SELECT seq,payload FROM moments WHERE '+' AND '.join(clauses)+
                             (' ORDER BY seq DESC LIMIT ?' if latest else ' ORDER BY seq LIMIT ?'),[*args,limit+1]).fetchall()
        if latest:
            more=len(rows)>limit
            rows=list(reversed(rows[:limit]))
            return {'items':[{**unpack(row['payload']),'story_seq':row['seq']} for row in rows],
                'next_cursor':None,'has_earlier':more,'cursor':rows[-1]['seq'] if rows else 0}

        return {'items':[{**unpack(row['payload']),'story_seq':row['seq']} for row in rows[:limit]],
                'next_cursor':rows[limit-1]['seq'] if len(rows)>limit else None,
                'cursor':rows[min(limit,len(rows))-1]['seq'] if rows else int(after or 0)}

    def episodes(self,*,before=None,limit=20):
        limit=min(50,max(1,int(limit)))
        clauses=['closed_seq IS NOT NULL']; args=[]
        if before is not None:
            clauses.append('closed_seq<?'); args.append(int(before))
        rows=self.db.execute('SELECT * FROM episodes WHERE '+' AND '.join(clauses)+
                             ' ORDER BY closed_seq DESC LIMIT ?',[*args,limit+1]).fetchall()
        return {'items':[{'id':row['id'],'token':row['token'],'closed_ts':row['closed_ts'],
                'net_return':row['net_return'],'net_pnl_eth':row['net_pnl'],'mode':'REPLAY'} for row in rows[:limit]],
                'next_cursor':rows[limit-1]['closed_seq'] if len(rows)>limit else None}

    def highlights(self):
        today=int(self.now())//86400*86400
        output=[]
        # Each category is a declared server query, with earliest evidence on ties.
        for category,order in (('LATEST','closed_seq DESC'),('BEST_TRADE','net_return DESC,closed_seq'),
                ('WORST_TRADE','net_return,closed_seq'),('LARGEST_PEAK','peak_return DESC,closed_seq'),
                ('LARGEST_GIVEBACK','giveback DESC,closed_seq')):
            row=self.db.execute('SELECT id,token,net_return,net_pnl,closed_ts FROM episodes '
                'WHERE closed_ts>=? AND closed_ts<? ORDER BY '+order+' LIMIT 1',(today,today+86400)).fetchone()
            if row:
                output.append({'category':category,**dict(row),'mode':'REPLAY','day_timezone':'UTC'})
        for category,item in self.missed_records(today=True).items():
            output.append({'category':category,**item,'mode':'REPLAY'})
        return {'items':output,'day_start_ts':today,'timezone':'UTC'}

    def away(self,after):
        after=max(0,int(after)); state=self.state() or {}
        rows=self.db.execute('SELECT net_pnl,net_return,id,token,peak_return FROM episodes WHERE closed_seq>? ORDER BY closed_seq',(after,))
        wins=losses=neutral=closed=0; net=0.0; biggest=None
        for row in rows:
            closed+=1; value=row['net_pnl']
            if value is None:
                continue
            wins+=value>0; losses+=value<0; neutral+=value==0; net+=value
            if row['peak_return'] is not None and (biggest is None or row['peak_return']>biggest['peak_return']):
                biggest={'episode_id':row['id'],'token':row['token'],'peak_return':row['peak_return']}
        opened=self.db.execute('SELECT count(*) FROM episodes WHERE opened_seq>?',(after,)).fetchone()[0]
        return {'after':after,'through':state.get('seq',0),'opened_positions':opened,'closed_positions':closed,
                'wins':wins,'losses':losses,'neutral':neutral,'net_paper_pnl_eth':net,
                'biggest_peak':biggest,'current_phase':state.get('phase','OFFLINE'),'execution':'PAPER'}

    def _has_followups(self):
        return self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='followup_targets'").fetchone() is not None

    def missed(self,*,category=None,before=None,limit=20):
        if category not in (None,'FLY_REJECTED','FILTERED_OUT'):
            raise ValueError('Unknown follow-up category')
        if not self._has_followups():
            return {'items':[],'next_cursor':None,'coverage':'NO_TARGETS_YET'}
        through=(self.state() or {}).get('seq',0)
        limit=min(50,max(1,int(limit)));clauses=['source_seq<=?'];args=[through]
        if category:
            clauses.append('category=?');args.append(category)
        if before is not None:
            clauses.append('seq<?');args.append(int(before))
        rows=self.db.execute('SELECT * FROM followup_targets WHERE '+' AND '.join(clauses)+
            ' ORDER BY seq DESC LIMIT ?',[*args,limit+1]).fetchall()
        items=[]
        for row in rows[:limit]:
            target=unpack(row['payload'])
            windows=[]
            for window in self.db.execute('SELECT * FROM followup_windows WHERE target=? ORDER BY window',(row['id'],)):
                completed=window['result_seq'] is not None and window['result_seq']<=through
                windows.append({'window_seconds':window['window'],'due_ts':window['due_ts'],
                    'status':window['status'] if completed else 'PENDING',
                    'result':unpack(window['payload']) if completed else None,
                    'source_seq':window['result_seq'] if completed else None})
            items.append({**target,'target_seq':row['seq'],'windows':windows})
        return {'items':items,'next_cursor':rows[limit-1]['seq'] if len(rows)>limit else None,
                'coverage':'RECORDED_CANDIDATE_EVIDENCE','windows_seconds':[300,900,1800]}

    def missed_records(self,*,today=False):
        if not self._has_followups():
            return {}
        through=(self.state() or {}).get('seq',0);start=int(self.now())//86400*86400
        output={}
        rules=(('BIGGEST_MISS','FLY_REJECTED',900,'modeled_net_return','>', 'DESC'),
               ('BEST_SAVE','FLY_REJECTED',900,'modeled_net_return','<', 'ASC'),
               ('FILTER_MISS','FILTERED_OUT',1800,'price_move','>', 'DESC'))
        for name,category,window,metric,comparison,order in rules:
            clauses=['t.category=?','w.window=?',"w.status='COMPLETE'",'w.result_seq<=?',f'w.{metric}{comparison}0']
            args=[category,window,through]
            if today:
                clauses.extend(['w.due_ts>=?','w.due_ts<?']);args.extend([start,start+86400])
            row=self.db.execute('SELECT t.payload AS target,w.payload AS result,w.result_seq FROM followup_targets t '
                'JOIN followup_windows w ON w.target=t.id WHERE '+' AND '.join(clauses)+
                f' ORDER BY w.{metric} {order},w.due_ts,t.seq LIMIT 1',args).fetchone()
            if row:
                target=unpack(row['target']); result=unpack(row['result'])
                output[name]={'target_id':target['id'],'token':target['token'],'category':category,
                    'window_seconds':window,'metric':metric,'value':result[metric],
                    'source_seq':row['result_seq'],'seen_ts':target['seen_ts'],
                    'result':result,'reason':target['reasons']}
        # Price-only records remain explicitly separate from executable returns.
        for name,comparison,order in (('LARGEST_REJECTED_PRICE_MOVE','>','DESC'),('LARGEST_REJECTED_PRICE_COLLAPSE','<','ASC')):
            clauses=["t.category='FLY_REJECTED'",'w.window=900',"w.status='COMPLETE'",'w.result_seq<=?',f'w.price_move{comparison}0']
            args=[through]
            if today:
                clauses.extend(['w.due_ts>=?','w.due_ts<?']);args.extend([start,start+86400])
            row=self.db.execute('SELECT t.id,t.token,t.seen_ts,w.payload,w.result_seq FROM followup_targets t '
                'JOIN followup_windows w ON w.target=t.id WHERE '+' AND '.join(clauses)+
                f' ORDER BY w.price_move {order},w.due_ts,t.seq LIMIT 1',args).fetchone()
            if row:
                result=unpack(row['payload'])
                output[name]={'target_id':row['id'],'token':row['token'],'category':'FLY_REJECTED',
                    'window_seconds':900,'metric':'price_move','value':result['price_move'],
                    'source_seq':row['result_seq'],'seen_ts':row['seen_ts'],'result':result,
                    'copy_rule':'PRICE MOVE AFTER REJECTION; never claim an executable return'}
        return output
