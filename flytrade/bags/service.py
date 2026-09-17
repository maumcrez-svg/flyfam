"""Transactional Bag Room application. Persist first; HTTP only projects committed state."""
import json
import time
from decimal import Decimal, ROUND_HALF_EVEN
from .config import address
from .store import Store, canonical, digest
from .signatures import typed, verify


def money(eth):
    # Existing PAPER account is float ETH. Declare this conversion rather than invent wei precision.
    return int((Decimal(str(eth))*10**18).to_integral_value(rounding=ROUND_HALF_EVEN))

class Room:
    def __init__(self, store, config, *, indexer=None, signature_rpc=None, now=time.time):
        self.store,self.config,self.indexer,self.now=store,config,indexer,now
        self.signature_rpc=signature_rpc
        with store.transaction() as db:
            policy={'chain_id':config.chain_id,'round_seconds':config.round_seconds,'profit_fraction_bps':config.profit_fraction_bps,'fixture':config.fixture,**({'sources':config.sources} if config.integration else {})}
            saved=Store.get(db,'room_policy')
            if saved and saved!=policy:
                if db.execute("SELECT 1 FROM bags WHERE status!='CLOSED'").fetchone():raise ValueError('Finish the active bag before changing its room policy')
                Store.emit(db,'ROOM_POLICY_CHANGED',None,{'previous':saved,'current':policy},self.now())
            Store.put(db,'room_policy',policy)

    def prepare_entry(self, decision_id):
        """Pin balances before signing/publishing an entry. Retry preserves cutoff."""
        with self.store.read() as db:
            old=db.execute('SELECT evidence FROM entry_snapshots WHERE decision_id=?',(decision_id,)).fetchone()
        if old:return json.loads(old[0])
        if self.indexer is None:raise ValueError('Entry requires a finalized holder index')
        final=self.indexer.finalized();block=int(final['number'],16)
        result=self.indexer.materialize(block+1,cutoff={'block':block,'hash':final['hash']})
        if result is None:raise ValueError('Holder index must catch up before entry')
        evidence,holders=result
        with self.store.transaction() as db:
            db.execute('INSERT OR IGNORE INTO entry_snapshots VALUES (?,?,?)',(decision_id,canonical(evidence),self.now()))
            return json.loads(db.execute('SELECT evidence FROM entry_snapshots WHERE decision_id=?',(decision_id,)).fetchone()[0])

    def create(self, event_id, episode_id, event):
        if not self.config.configured: raise ValueError('Project token not configured')
        if event.get('kind')!='OPEN' or event.get('entry_block') is None: raise ValueError('Bag requires canonical OPEN evidence')
        if self.config.integration and (event.get('execution')!='PAPER' or event.get('mode')!='LIVE_PAPER' or event.get('venue')!='PONS' or event.get('run_id')!='pons-live' or event.get('bag_position_source')!='REAL_WORKER'):
            raise ValueError('Integration bags require the canonical main Pons PAPER worker OPEN')
        with self.store.transaction() as db:
            old=db.execute('SELECT id FROM bags WHERE source_event=?',(event_id,)).fetchone()
            if old:return old[0]
            bag_id='bag-'+digest([self.config.chain_id,episode_id,event_id])[:24]
            number=db.execute('SELECT coalesce(max(number),0)+1 FROM bags').fetchone()[0]
            db.execute('INSERT INTO bags(id,number,source_event,episode_id,token,opened_at,entry_block,status,entry) VALUES (?,?,?,?,?,?,?,?,?)',
                       (bag_id,number,event_id,str(episode_id),address(event['token']),int(event['entry_ts']),int(event['entry_block']),'SNAPSHOT_PENDING',canonical(event)))
            prepared=db.execute('SELECT evidence FROM entry_snapshots WHERE decision_id=?',(event.get('decision_id',''),)).fetchone()
            if event.get('execution')=='LIVE' and not prepared:raise ValueError('LIVE entry has no precommitted economic snapshot')
            if prepared:
                snapshot=json.loads(prepared[0])
                if snapshot['snapshot_block']>=int(event['entry_block']):raise ValueError('Snapshot must predate entry')
                db.executemany('INSERT INTO eligible VALUES (?,?)',((bag_id,w) for w in snapshot['snapshot_balances']))
                db.execute("UPDATE bags SET status='OPEN',snapshot=? WHERE id=?",(canonical(snapshot),bag_id))
            Store.emit(db,'BAG_CREATED',bag_id,{'number':number,'episode_id':str(episode_id),'entry':event,'fixture':self.config.fixture,**self.config.sources},self.now())
            if prepared:
                Store.emit(db,'BAG_ELIGIBILITY_LOCKED',bag_id,snapshot,self.now())
                self._open_round(db,bag_id,1,self.now())
            return bag_id

    def _bag(self,db,bag_id):
        row=db.execute('SELECT * FROM bags WHERE id=?',(bag_id,)).fetchone()
        if not row:raise ValueError('Unknown bag')
        return row

    def _holder(self,db,bag_id,wallet):
        """Was this wallet in the bag's locked eligibility snapshot?"""
        return bool(db.execute('SELECT 1 FROM eligible WHERE bag_id=? AND wallet=?',(bag_id,wallet)).fetchone())

    def _eligible(self,db,bag_id,wallet):
        if not self._holder(db,bag_id,wallet):
            raise ValueError('Wallet was not eligible at this bag snapshot')

    def _round(self,db,bag_id,number,now):
        bag=self._bag(db,bag_id)
        row=db.execute('SELECT * FROM rounds WHERE bag_id=? AND number=?',(bag_id,number)).fetchone()
        if bag['status']!='OPEN' or not row or row['status']!='OPEN' or now>=row['closes_at']:
            raise ValueError('Voting round is closed')
        return row

    def lock_snapshot(self,bag_id):
        with self.store.read() as db:
            bag=self._bag(db,bag_id)
            if bag['status']!='SNAPSHOT_PENDING':return
        snapshot=self.indexer.materialize(bag['entry_block'])
        if snapshot is None:return
        evidence,holders=snapshot
        with self.store.transaction() as db:
            if self._bag(db,bag_id)['status']!='SNAPSHOT_PENDING':return
            db.executemany('INSERT INTO eligible VALUES (?,?)',((bag_id,w) for w in holders))
            db.execute("UPDATE bags SET status='OPEN',snapshot=? WHERE id=?",(canonical(evidence),bag_id))
            Store.emit(db,'BAG_ELIGIBILITY_LOCKED',bag_id,evidence,self.now())
            self._open_round(db,bag_id,1,self.now())

    def _open_round(self,db,bag_id,number,now):
        db.execute('INSERT INTO rounds VALUES (?,?,?,?,?,NULL)',(bag_id,number,now,now+self.config.round_seconds,'OPEN'))
        Store.emit(db,'VOTE_ROUND_OPENED',bag_id,{'round_id':number,'closes_at':now+self.config.round_seconds},now)

    def challenge(self,body,client):
        wallet=address(body.get('wallet'))
        action=body.get('action')
        bag_id=body.get('bag_id','')
        number=body.get('round_id',0)
        choice=body.get('choice','')
        content=body.get('content','')
        if action not in ('AUTH','VOTE','CHAT','CLAIM') or not isinstance(bag_id,str) or len(bag_id)>80:raise ValueError('Invalid action')
        if type(number) is not int or not 0<=number<2**31:raise ValueError('Invalid round')
        if not isinstance(content,str) or len(content)>400 or any(ord(c)<32 and c not in '\n\t' for c in content):raise ValueError('Message must contain at most 400 plain-text characters')
        if action=='VOTE' and choice not in ('HOLD','EXIT'):raise ValueError('Invalid vote choice')
        if action=='CHAT' and not content.strip():raise ValueError('Empty message')
        if action=='CLAIM' and (number or choice or content):raise ValueError('Claim binds only the canonical bag and wallet')
        if action!='VOTE' and choice:raise ValueError('Choice is only valid for a signed vote')
        now=self.now()
        with self.store.transaction() as db:
            Store.rate(db,'challenge-ip:'+client,now,60)
            Store.rate(db,'challenge-wallet:'+wallet,now,20)
            if action!='AUTH':
                # Owner decision, 2026-09-17: CHAT is open to any wallet that
                # verifies a signature, holder or not. VOTE and CLAIM remain
                # holder-only against the bag's immutable snapshot, and there
                # is still no unsigned or anonymous post of any kind.
                if action!='CHAT':self._eligible(db,bag_id,wallet)
                if action=='CLAIM':
                    from .payout import claim_job
                    claim_job(db,bag_id,wallet,now)
                elif self._bag(db,bag_id)['status']=='CLOSED':raise ValueError('Bag is archived')
            if action=='VOTE':self._round(db,bag_id,number,now)
            message=typed(self.config,wallet,action,bag_id,number,choice,content.strip(),now)
            db.execute('DELETE FROM challenges WHERE expires<?',(now-300,))
            db.execute('INSERT INTO challenges(nonce,wallet,expires,typed) VALUES (?,?,?,?)',(message['message']['nonce'],wallet,message['message']['expires_at'],canonical(message)))
        return message

    def submit(self,nonce,signature,client):
        if not isinstance(nonce,str) or len(nonce)!=48:raise ValueError('Invalid nonce')
        with self.store.read() as db:
            row=db.execute('SELECT * FROM challenges WHERE nonce=?',(nonce,)).fetchone()
        if not row or row['used'] or self.now()>=row['expires']:raise ValueError('Challenge expired or already used')
        message=json.loads(row['typed'])
        wallet=verify(message,signature,self.signature_rpc)
        m=message['message'];now=self.now();bag_id=m['bag_id'];number=m['round_id']
        with self.store.transaction() as db:
            now=self.now()  # Recheck time after acquiring the write lock, not before waiting for it.
            Store.rate(db,'submit-ip:'+client,now,90)
            used=db.execute('UPDATE challenges SET used=1 WHERE nonce=? AND used=0 AND expires>?',(nonce,now)).rowcount
            if used!=1:raise ValueError('Challenge expired or already used')
            evidence={'typed_data':message,'signature':signature,'market':None}
            if m['action']=='AUTH':
                Store.emit(db,'WALLET_AUTHENTICATED',None,{'wallet':wallet,'evidence':evidence},now)
                return {'wallet':wallet,'authenticated':True}
            holder=self._holder(db,bag_id,wallet)
            if m['action']!='CHAT' and not holder:
                raise ValueError('Wallet was not eligible at this bag snapshot')
            bag=self._bag(db,bag_id)
            if m['action']=='CLAIM':
                from .payout import claim_job
                return claim_job(db,bag_id,wallet,now,create=True,evidence=evidence)
            if bag['status']=='CLOSED':raise ValueError('Bag is archived')
            evidence['market']=json.loads(bag['market']) if bag['market'] else None
            if m['action']=='VOTE':
                self._round(db,bag_id,number,now)
                previous=db.execute('SELECT choice FROM votes WHERE bag_id=? AND round=? AND wallet=?',(bag_id,number,wallet)).fetchone()
                Store.rate(db,'vote:'+wallet,now,12)
                seq=Store.emit(db,'VOTE_REPLACED' if previous else 'VOTE_CAST',bag_id,
                               {'round_id':number,'wallet':wallet,'choice':m['choice'],'previous':previous[0] if previous else None,'weight':1,'evidence':evidence},now)
                db.execute('INSERT INTO votes VALUES (?,?,?,?,?,?) ON CONFLICT(bag_id,round,wallet) DO UPDATE SET choice=excluded.choice,event_seq=excluded.event_seq,ts=excluded.ts',
                           (bag_id,number,wallet,m['choice'],seq,now))
            else:
                Store.rate(db,'chat:'+wallet,now,1,3)
                cur=db.execute('INSERT INTO chat(bag_id,wallet,ts,message,holder) VALUES (?,?,?,?,?)',(bag_id,wallet,now,m['content'],int(holder)))
                Store.emit(db,'CHAT_MESSAGE',bag_id,{'message_id':cur.lastrowid,'wallet':wallet,'holder':holder,'message':m['content'],'evidence':evidence},now)
        return {'accepted':True,'wallet':wallet,'action':m['action']}

    def tick(self):
        with self.store.read() as db:
            pending=db.execute("SELECT id FROM bags WHERE status='SNAPSHOT_PENDING'").fetchone()
        if pending and self.indexer:self.lock_snapshot(pending[0])
        now=self.now()
        with self.store.transaction() as db:
            for row in db.execute("SELECT r.* FROM rounds r JOIN bags b ON b.id=r.bag_id WHERE r.status='OPEN' AND b.status='OPEN' AND r.closes_at<=?",(now,)).fetchall():
                counts={r[0]:r[1] for r in db.execute('SELECT choice,count(*) FROM votes WHERE bag_id=? AND round=? GROUP BY choice',(row['bag_id'],row['number']))}
                hold,exit_=counts.get('HOLD',0),counts.get('EXIT',0)
                result='NO_QUORUM_HOLD' if hold+exit_==0 else ('COMMUNITY_HOLD' if hold>exit_ else 'COMMUNITY_EXIT')
                payload={'round_id':row['number'],'hold':hold,'exit':exit_,'votes_cast':hold+exit_,'decision':result,'scheduled_close':row['closes_at']}
                db.execute("UPDATE rounds SET status='CLOSED',result=? WHERE bag_id=? AND number=?",(canonical(payload),row['bag_id'],row['number']))
                Store.emit(db,'VOTE_ROUND_CLOSED',row['bag_id'],payload,now)
                Store.emit(db,result,row['bag_id'],payload,now)
                if result=='COMMUNITY_EXIT':
                    intent={'id':row['bag_id']+':exit','round_id':row['number'],'requested_at':int(now),'status':'REQUESTED'}
                    db.execute("UPDATE bags SET status='EXIT_REQUESTED',exit_intent=? WHERE id=?",(canonical(intent),row['bag_id']))
                    Store.emit(db,'EXIT_REQUESTED',row['bag_id'],intent,now)
                else:self._open_round(db,row['bag_id'],row['number']+1,now)
            if self.config.test_autoexit_enabled:
                for bag in db.execute("SELECT * FROM bags WHERE status='OPEN'").fetchall():
                    self._tick_auto_exit(db,bag,now)
            Store.put(db,'room_heartbeat',{'ts':now,'status':'READY' if self.config.configured else 'TOKEN_NOT_CONFIGURED'})

    def _tick_auto_exit(self,db,bag,now):
        from .autoexit import policy_for,stored_policy,projection
        entry=json.loads(bag['entry'])
        if not (self.config.integration and entry.get('execution')=='PAPER'
                and entry.get('holder_source')=='FIXTURE' and entry.get('bag_position_source')=='REAL_WORKER'):
            return
        policy=stored_policy(db,bag['id'])
        if policy is None:
            policy=policy_for(self.config)
            Store.put(db,'autoexit-policy:'+bag['id'],policy)
            Store.emit(db,'AUTO_EXIT_POLICY_ENABLED',bag['id'],policy,now)
        # Existing bags retain the exact policy they were given, including after restart.
        state=projection(db,bag,policy,now)
        previous=Store.get(db,'autoexit-control:'+bag['id'])
        control=state['status']
        if previous!=control:
            Store.put(db,'autoexit-control:'+bag['id'],control)
            Store.emit(db,'AUTO_EXIT_CONTROL_CHANGED',bag['id'],
                       {'previous':previous,'control':control,'empty_rounds':state['empty_rounds']},now)
        reason=state['trigger']
        if not reason:return
        intent={'id':bag['id']+':exit','round_id':None,'requested_at':int(now),
                'status':'REQUESTED','source':'AUTO_EXIT','reason':reason,
                'policy':policy,'trigger_net_return':state['net_return'],
                'trigger_gross_return':state['gross_return'],'trigger_basis':state['return_basis'],
                'trigger_age_seconds':state['age_seconds'],'trigger_held_seconds':state['held_seconds'],
                'market':json.loads(bag['market'])}
        db.execute("UPDATE bags SET status='EXIT_REQUESTED',exit_intent=? WHERE id=? AND status='OPEN' AND exit_intent IS NULL",
                   (canonical(intent),bag['id']))
        # Cancel an unfinished empty round instead of fabricating a voted result.
        db.execute("UPDATE rounds SET status='CANCELLED',result=? WHERE bag_id=? AND status='OPEN'",
                   (canonical({'decision':reason,'source':'AUTO_EXIT'}),bag['id']))
        Store.emit(db,'AUTO_EXIT_TRIGGERED',bag['id'],intent,now)
        Store.emit(db,'EXIT_REQUESTED',bag['id'],intent,now)

    def execution_state(self,bag_id,status,detail=None):
        with self.store.transaction() as db:
            bag=self._bag(db,bag_id)
            if bag['status']=='CLOSED':return
            intent=json.loads(bag['exit_intent']) if bag['exit_intent'] else None
            if intent is None:raise ValueError('No community exit intent')
            if intent['status']==status and intent.get('detail')==detail:return
            intent.update(status=status,detail=detail)
            db.execute('UPDATE bags SET status=?,exit_intent=? WHERE id=?',('EXIT_PENDING',canonical(intent),bag_id))
            Store.emit(db,'EXIT_EXECUTION_STARTED' if status=='SELLING' else 'EXIT_FAILED',bag_id,intent,self.now())

    def market(self,episode_id,mark):
        with self.store.transaction() as db:
            db.execute("UPDATE bags SET market=? WHERE episode_id=? AND status!='CLOSED'",(canonical(mark),str(episode_id)))

    def close(self,episode_id,event_id,event):
        if event.get('kind')!='CLOSE' or event.get('settlement')!='SETTLED_FROZEN':raise ValueError('Close needs canonical frozen settlement')
        with self.store.transaction() as db:
            bag=db.execute('SELECT * FROM bags WHERE episode_id=?',(str(episode_id),)).fetchone()
            if not bag or bag['status']=='CLOSED':return
            pnl=money(event['net_pnl_eth']);credit=max(0,pnl)*self.config.profit_fraction_bps//10000
            entry=json.loads(bag['entry']);principal=money(entry['entry_principal_eth'] if entry.get('entry_principal_eth') is not None else entry['quantity']*entry['entry_fill_price']+(entry.get('fee_eth') or 0))
            result={'entry_principal_wei':str(principal),**self.config.sources,'execution':'PAPER','claimable':False,'close':event,'source_event':event_id,'net_pnl_wei':str(pnl),'vault_credit_wei':str(credit),
                    'principal_returned_wei':str(min(principal,max(0,principal+pnl))),
                    'exit_proceeds_wei':str(max(0,principal+pnl)),'costs_wei':str(money(event['fees_eth'])),
                    'gross_pnl_wei':str(money(event['gross_pnl_eth'])),
                    'accounting':'PAPER; integer display rounded from canonical float ETH account','closed_at':self.now(),
                    'exit_source':(json.loads(bag['exit_intent']).get('source','COMMUNITY') if bag['exit_intent'] else 'EXECUTOR'),
                    'auto_exit_reason':(json.loads(bag['exit_intent']).get('reason') if bag['exit_intent'] else None)}
            db.execute("UPDATE bags SET status='CLOSED',result=? WHERE id=?",(canonical(result),bag['id']))
            db.execute("UPDATE rounds SET status='CANCELLED',result=? WHERE bag_id=? AND status='OPEN'",(canonical({'decision':'EXECUTOR_CLOSED'}),bag['id']))
            Store.emit(db,'EXIT_CONFIRMED',bag['id'],{'source_event':event_id,'close_reason':event['close_reason']},self.now())
            Store.emit(db,'BAG_CLOSED',bag['id'],result,self.now())
            if self.config.integration and event.get('close_reason')=='COMMUNITY_EXIT' and event.get('run_id')=='pons-live':
                holds=db.execute("SELECT seq FROM audit WHERE bag_id=? AND kind='COMMUNITY_HOLD'",(bag['id'],)).fetchall()
                exits=db.execute("SELECT seq FROM audit WHERE bag_id=? AND kind='COMMUNITY_EXIT'",(bag['id'],)).fetchall()
                if holds and len(exits)==1 and bag['exit_intent']:
                    proof={'bag_id':bag['id'],'episode_id':str(episode_id),'token':bag['token'],
                        'entry_source_event':bag['source_event'],'close_source_event':event_id,
                        'hold_event_seq':holds[-1][0],'exit_event_seq':exits[0][0],
                        'entry_block':bag['entry_block'],'exit_block':event.get('exit_block'),
                        'exit_intent':json.loads(bag['exit_intent']),'net_pnl_wei':str(pnl),
                        'source':'CANONICAL_REAL_PONS_PAPER_WORKER','verified_at':self.now(),**self.config.sources}
                    Store.put(db,'phase_a_bridge_proof',proof)
                    Store.emit(db,'REAL_PAPER_BRIDGE_VERIFIED',bag['id'],proof,self.now())
            if credit:
                db.execute('INSERT INTO vault VALUES (?,?,?,?)',(bag['id'],str(credit),event_id,self.now()))
                Store.emit(db,'BAG_PROFIT_REALIZED',bag['id'],{'net_pnl_wei':str(pnl),'source_event':event_id},self.now())
                Store.emit(db,'VAULT_CREDIT',bag['id'],{'amount_wei':str(credit),'execution':'PAPER','claimable':False,'source_event':event_id},self.now())

    def active_for(self,episode_id):
        with self.store.read() as db:
            row=db.execute('SELECT * FROM bags WHERE episode_id=?',(str(episode_id),)).fetchone()
            return dict(row) if row else None

    def vault_reserved(self):
        with self.store.read() as db:return sum(int(r[0]) for r in db.execute('SELECT amount_wei FROM vault'))

    def view(self,bag_id=None,wallet=None,*,after=0,before=None):
        if wallet:wallet=address(wallet)
        now=self.now()
        with self.store.read() as db:
            bag=(self._bag(db,bag_id) if bag_id else db.execute("SELECT * FROM bags ORDER BY (status!='CLOSED') DESC,number DESC LIMIT 1").fetchone())
            data={'configured':self.config.configured,'fixture':self.config.fixture,'chain_id':self.config.chain_id,'project_token':self.config.token or None,**self.config.sources,'test_holders':self.config.integration,
                  'bridge_verified':bool(Store.get(db,'phase_a_bridge_proof')) if self.config.integration else None,
                  'bag_configured':self.config.configured and (bool(Store.get(db,'phase_a_bridge_proof')) if self.config.integration else True),
                  'server_time':now,'heartbeat':Store.get(db,'room_heartbeat'),'holder_index':{'cursor':Store.get(db,'fixture_holder_cursor' if self.config.integration else 'holder_cursor'),'health':Store.get(db,'index_health')},'seq':db.execute('SELECT coalesce(max(seq),0) FROM audit').fetchone()[0],
                  'vault':{'balance_wei':str(sum(int(r[0]) for r in db.execute('SELECT amount_wei FROM vault'))),'execution':'PAPER','claimable':False},
                  'bag':None,'history':[],'leaderboard':[],'events':[],'chat':[]}
            history=db.execute('SELECT id,number,token,status,result,episode_id FROM bags WHERE status=\'CLOSED\' AND number<? ORDER BY number DESC LIMIT 20',(before if before is not None else 2**63-1,)).fetchall()
            data['history']=[{**dict(r),'result':json.loads(r['result'])} for r in history]
            rows=db.execute('SELECT wallet,count(*) AS votes_cast,count(DISTINCT bag_id) AS bags_participated,sum(choice=\'HOLD\') AS hold_votes,sum(choice=\'EXIT\') AS exit_votes FROM votes GROUP BY wallet ORDER BY bags_participated DESC,votes_cast DESC,wallet LIMIT 30').fetchall()
            latest=db.execute('SELECT coalesce(max(number),0) FROM bags').fetchone()[0]
            for r in rows:
                numbers=[v[0] for v in db.execute('SELECT DISTINCT b.number FROM votes v JOIN bags b ON b.id=v.bag_id WHERE v.wallet=? ORDER BY b.number DESC',(r['wallet'],))]
                streak=0
                for n in numbers:
                    if n!=latest-streak:break
                    streak+=1
                data['leaderboard'].append({**dict(r),'participation_streak':streak})
            if bag:
                b=dict(bag)
                for key in ('entry','snapshot','result','market','exit_intent'):b[key]=json.loads(b[key]) if b[key] else None
                if b.get('snapshot'):b['snapshot'].pop('snapshot_balances',None)
                b['eligible']=bool(wallet and db.execute('SELECT 1 FROM eligible WHERE bag_id=? AND wallet=?',(b['id'],wallet)).fetchone())
                rounds=[]
                for r in db.execute('SELECT * FROM rounds WHERE bag_id=? ORDER BY number DESC LIMIT 100',(b['id'],)):
                    rd=dict(r);rd['result']=json.loads(rd['result']) if rd['result'] else None
                    counts={v[0]:v[1] for v in db.execute('SELECT choice,count(*) FROM votes WHERE bag_id=? AND round=? GROUP BY choice',(b['id'],r['number']))}
                    rd.update(hold=counts.get('HOLD',0),exit=counts.get('EXIT',0));rd['votes_cast']=rd['hold']+rd['exit']
                    rd['participation_pct']=100*rd['votes_cast']/max(1,(b['snapshot'] or {}).get('eligible_wallet_count',0))
                    own=db.execute('SELECT choice FROM votes WHERE bag_id=? AND round=? AND wallet=?',(b['id'],r['number'],wallet or '')).fetchone()
                    rd['my_vote']=own[0] if own else None;rounds.append(rd)
                b['round']=rounds[0] if rounds else None;b['rounds']=rounds
                b['round_count']=db.execute('SELECT count(*) FROM rounds WHERE bag_id=?',(b['id'],)).fetchone()[0]
                b['chat_count']=db.execute('SELECT count(*) FROM chat WHERE bag_id=?',(b['id'],)).fetchone()[0]
                from .autoexit import stored_policy,projection
                policy=stored_policy(db,b['id'])
                b['auto_exit']=projection(db,bag,policy,now) if policy else None
                data['bag']=b
                data['chat']=[{**dict(r),'holder':bool(r['holder'])} for r in reversed(db.execute('SELECT * FROM chat WHERE bag_id=? ORDER BY id DESC LIMIT 40',(b['id'],)).fetchall())]
            # Bounded light live event projection. Signed evidence remains in the audit endpoint.
            for r in db.execute('SELECT seq,kind,bag_id,ts,payload FROM audit WHERE seq>? ORDER BY seq LIMIT 100',(after,)):
                p=json.loads(r['payload']);p.pop('evidence',None);p.pop('entry',None);p.pop('close',None);p.pop('snapshot_balances',None)
                data['events'].append({**dict(r),'payload':p})
            data['next_after']=data['events'][-1]['seq'] if data['events'] else after
            return data

    def audit(self,bag_id,after=0):
        with self.store.read() as db:
            self._bag(db,bag_id)
            return {'events':[dict(r) for r in db.execute('SELECT * FROM audit WHERE bag_id=? AND seq>? ORDER BY seq LIMIT 50',(bag_id,after))]}

    def proof(self,bag_id,wallet):
        wallet=address(wallet)
        with self.store.read() as db:
            b=self._bag(db,bag_id)
            snapshot=json.loads(b['snapshot']) if b['snapshot'] else None
            balances=snapshot.pop('snapshot_balances',{}) if snapshot else {}
            return {'snapshot_balance':balances.get(wallet),'bag_id':bag_id,'wallet':wallet,'eligible':bool(db.execute('SELECT 1 FROM eligible WHERE bag_id=? AND wallet=?',(bag_id,wallet)).fetchone()),
                    'snapshot':snapshot}
