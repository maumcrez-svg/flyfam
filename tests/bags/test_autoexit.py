"""Synthetic PAPER states only; the public worker proof is recorded separately."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import SimpleNamespace
import json
import pytest
from flytrade.bags.bridge import CommunityExecution
from flytrade.bags.config import Config
from flytrade.bags.service import Room
from flytrade.bags.store import Store
from flytrade.product.live import ProductPaperExecution, FeedJournal
from .test_real_paper_bridge import setup
from .test_room import vote


# The v1 numbers. The cases below test trigger mechanics, not the v2 thresholds,
# so they keep the rule they were written against: NET basis, +-5%, no hold window.
LEGACY=dict(autoexit_return_basis='NET',autoexit_profit_bps=500,autoexit_loss_bps=500,
            autoexit_idle_seconds=120,autoexit_min_hold_seconds=0,autoexit_max_hold_seconds=86400)


def opened(tmp_path,enabled=True,entry_ts=110,**config):
    room,bridge,node,t,event,w=setup(tmp_path)
    room.config=replace(room.config,test_autoexit_enabled=enabled,**config)
    event['size_eth']=.01;event['entry_ts']=entry_ts
    bridge.event(event);room.tick()
    return room,bridge,t,event,w


def price(gross):
    """100 tokens filled at .0001 with a .00001 fee: principal .01001 ETH."""
    return .0001+gross*.01001/100


def mark(bridge,t,event,pnl=-.0003,gross=0.,**changes):
    value={**event,'kind':'MARK','seq':18,'available':True,'ts':t[0],'cutoff_ts':t[0],
           'unrealised_eth':pnl,'cost_eth':.01002,'mark_value_eth':.01002+pnl,
           'marginal_price':price(gross)}
    value.update(changes);bridge.event(value)


def arm(room,t):
    for _ in range(2):t[0]+=31;room.tick()


def advance(room,bridge,t,event,age,*,entry_ts=1000,gross=0.,step=31):
    """Run the round clock and the mark forward the way the live worker does."""
    while t[0]<entry_ts+age:
        t[0]=min(entry_ts+age,t[0]+step)
        mark(bridge,t,event,gross=gross);room.tick()


@pytest.mark.parametrize('pnl,reason',[(.0005,'AUTO_EXIT_TAKE_PROFIT'),(-.0005,'AUTO_EXIT_STOP_LOSS')])
def test_two_empty_rounds_then_one_canonical_exit_and_restart(tmp_path,pnl,reason):
    room,bridge,t,event,_=opened(tmp_path,**LEGACY)
    mark(bridge,t,event,pnl)
    t[0]+=31;room.tick();assert room.view()['bag']['status']=='OPEN'
    t[0]+=31
    with ThreadPoolExecutor(2) as pool:list(pool.map(lambda _:room.tick(),range(2)))
    b=room.view()['bag'];assert b['status']=='EXIT_REQUESTED'
    assert b['exit_intent']['source']=='AUTO_EXIT' and b['exit_intent']['reason']==reason
    assert b['round']['status']=='CANCELLED'
    restored=Room(Store(room.store.path),room.config,now=lambda:t[0]);restored.tick()
    assert restored.view()['bag']['exit_intent']==b['exit_intent']
    with room.store.read() as db:
        assert db.execute("SELECT count(*) FROM audit WHERE kind='EXIT_REQUESTED'").fetchone()[0]==1
        assert db.execute("SELECT count(*) FROM audit WHERE kind='COMMUNITY_EXIT'").fetchone()[0]==0
    x=type('AutoPaper',(CommunityExecution,ProductPaperExecution),{})()
    x.bag_room=restored;x.bag_run_id='pons-live';x.account.position=SimpleNamespace(episode_id=22)
    assert not x.due_for_horizon(int(t[0]))
    assert x.due_for_horizon(int(t[0])+x.latency_s)
    assert x.exit_close_reason.value=='AUTO_EXIT'
    close={**event,'kind':'CLOSE','seq':19,'settlement':'SETTLED_FROZEN','close_reason':'AUTO_EXIT',
           'net_pnl_eth':pnl,'fees_eth':.0002,'gross_pnl_eth':pnl+.0002}
    bridge.event(close);bridge.event(close)
    result=room.view()['bag']['result']
    assert result['auto_exit_reason']==reason and result['exit_source']=='AUTO_EXIT'
    assert len(room.view()['history'])==1


@pytest.mark.parametrize('change',[
    {'cutoff_ts':1},{'ts':1},{'cutoff_ts':9999999},{'available':False},
    {'unrealised_eth':None},{'token':'0x'+'ab'*20},{'activity':{'idle':True}},
])
def test_bad_marks_never_trigger(tmp_path,change):
    room,bridge,t,event,_=opened(tmp_path,**LEGACY);arm(room,t)
    mark(bridge,t,event,**change);room.tick()
    assert room.view()['bag']['status']=='OPEN'


def test_inactivity_needs_fresh_evidence_and_actual_two_minute_window(tmp_path):
    room,bridge,t,event,_=opened(tmp_path,**LEGACY);arm(room,t)
    # An unchanged price alone never proves inactivity.
    mark(bridge,t,event);room.tick();assert room.view()['bag']['status']=='OPEN'
    evidence={'available':True,'idle':True,'window_seconds':120,'observed_through_ts':t[0]}
    mark(bridge,t,event,activity={**evidence,'observed_through_ts':t[0]-30})
    room.tick();assert room.view()['bag']['status']=='OPEN'
    mark(bridge,t,event,activity=evidence);room.tick()
    assert room.view()['bag']['exit_intent']['reason']=='AUTO_EXIT_INACTIVE'


def test_pending_valid_vote_pauses_then_hold_resets_empty_rounds(tmp_path):
    room,bridge,t,event,w=opened(tmp_path,**LEGACY);arm(room,t)
    b=room.view()['bag'];assert b['auto_exit']['status']=='ARMED'
    vote(room,b['id'],w[0],'HOLD',round_=3)
    mark(bridge,t,event,.001);room.tick()
    assert room.view()['bag']['auto_exit']['status']=='VOTE_PENDING'
    t[0]+=31;room.tick()
    b=room.view()['bag'];assert b['status']=='OPEN' and b['auto_exit']['status']=='COMMUNITY'
    assert b['auto_exit']['empty_rounds']==0
    t[0]+=31;mark(bridge,t,event,.001);room.tick()
    assert room.view()['bag']['status']=='OPEN'
    t[0]+=31;mark(bridge,t,event,.001);room.tick()
    assert room.view()['bag']['status']=='EXIT_REQUESTED'


def test_community_exit_wins_without_auto_event(tmp_path):
    room,bridge,t,event,w=opened(tmp_path,**LEGACY);arm(room,t)
    b=room.view()['bag'];vote(room,b['id'],w[0],'EXIT',round_=3)
    mark(bridge,t,event,.001);t[0]+=31;room.tick()
    b=room.view()['bag'];assert b['exit_intent'].get('source') is None
    with room.store.read() as db:
        assert db.execute("SELECT count(*) FROM audit WHERE kind='AUTO_EXIT_TRIGGERED'").fetchone()[0]==0


def test_disabled_or_real_holders_never_activate(tmp_path):
    room,bridge,t,event,_=opened(tmp_path,enabled=False,**LEGACY)
    mark(bridge,t,event,.001);arm(room,t)
    assert room.view()['bag']['status']=='OPEN' and room.view()['bag']['auto_exit'] is None
    with pytest.raises(ValueError,match='only for real PAPER'):
        Config(test_autoexit_enabled=True)
    with pytest.raises(ValueError,match='only for real PAPER'):
        Config(fixture=True,test_autoexit_enabled=True)


def test_activation_adopts_existing_empty_rounds_without_rewriting_history(tmp_path):
    room,bridge,t,event,_=opened(tmp_path,enabled=False,**LEGACY);arm(room,t)
    with room.store.read() as db:old=[tuple(r) for r in db.execute('SELECT * FROM audit')]
    room.config=replace(room.config,test_autoexit_enabled=True)
    mark(bridge,t,event,-.001);room.tick()
    assert room.view()['bag']['exit_intent']['reason']=='AUTO_EXIT_STOP_LOSS'
    with room.store.read() as db:assert [tuple(r) for r in db.execute('SELECT * FROM audit WHERE seq<=?',(old[-1][0],))]==old


def test_feed_preserves_activity_evidence():
    captured=[]
    journal=object.__new__(FeedJournal)
    journal.loop=SimpleNamespace(global_tick=1,x=SimpleNamespace(account=SimpleNamespace(position=SimpleNamespace(symbol='token',episode_id=1))))
    journal.feed=SimpleNamespace(emit=lambda kind,**data:captured.append(data))
    evidence={'available':True,'idle':True,'window_seconds':120,'observed_through_ts':100}
    journal._emit_mark({'available':True,'activity':evidence},100)
    assert captured[0]['activity']==evidence


# ---------------------------------------------------------------- autoexit v2
# Regression cases from the live bags of 2026-09-16, whose round-trip costs of
# 2.5-8.6% of notional put every bag below a -5% NET stop the moment it opened.

@pytest.mark.parametrize('gross,age,why',[
    (.0438,64,'bag 6: gross +4.38%, costs 8.63%, sold by the NET rule at 64s'),
    (-.0022,67,'bag 10: gross -0.22%, sold by the NET rule at 67s'),
    (-.0022,700,'bag 10 again, past the minimum hold: still inside the band'),
    (-.25,300,'a real -25% collapse, but before the minimum hold'),
    (.25,300,'a real +25% move, but before the minimum hold'),
])
def test_v2_holds_the_bags_the_net_rule_sold(tmp_path,gross,age,why):
    room,bridge,t,event,_=opened(tmp_path,entry_ts=1000);arm(room,t)
    t[0]=1000+age;mark(bridge,t,event,gross=gross);room.tick()
    b=room.view()['bag']
    assert b['status']=='OPEN',why
    assert b['auto_exit']['trigger'] is None and b['auto_exit']['observation_status']=='FRESH'
    assert abs(b['auto_exit']['gross_return']-gross)<1e-12


@pytest.mark.parametrize('gross,reason',[(-.25,'AUTO_EXIT_STOP_LOSS'),(.25,'AUTO_EXIT_TAKE_PROFIT')])
def test_v2_wide_gross_bands_fire_after_the_minimum_hold(tmp_path,gross,reason):
    room,bridge,t,event,_=opened(tmp_path,entry_ts=1000);arm(room,t)
    t[0]=1700;mark(bridge,t,event,gross=gross);room.tick()
    b=room.view()['bag']
    assert b['status']=='EXIT_REQUESTED' and b['exit_intent']['reason']==reason
    assert b['exit_intent']['trigger_basis']=='GROSS'
    assert abs(b['exit_intent']['trigger_gross_return']-gross)<1e-12


def test_v2_gross_decides_and_net_only_reports(tmp_path):
    # Bag 12's trigger mark: net -8.02% of principal, gross +0.46%.
    room,bridge,t,event,_=opened(tmp_path,entry_ts=1000);arm(room,t)
    t[0]=1700;mark(bridge,t,event,-.000802,gross=.0046);room.tick()
    auto=room.view()['bag']['auto_exit']
    assert room.view()['bag']['status']=='OPEN' and auto['trigger'] is None
    assert abs(auto['net_return']+.0802)<1e-9 and abs(auto['gross_return']-.0046)<1e-12


def test_net_basis_explicitly_configured_keeps_the_original_rule(tmp_path):
    room,bridge,t,event,_=opened(tmp_path,entry_ts=1000,**LEGACY);arm(room,t)
    t[0]=1700;mark(bridge,t,event,-.000802,gross=.0046);room.tick()
    b=room.view()['bag']
    assert b['exit_intent']['reason']=='AUTO_EXIT_STOP_LOSS'
    assert b['exit_intent']['trigger_basis']=='NET'


def test_a_policy_recorded_before_the_gross_rule_is_never_rewritten(tmp_path):
    room,bridge,t,event,_=opened(tmp_path,entry_ts=1000)
    with room.store.transaction() as db:
        bag_id=db.execute('SELECT id FROM bags').fetchone()[0]
        Store.put(db,'autoexit-policy:'+bag_id,{'version':1,'scope':'REAL_PONS_PAPER_TEST_HOLDERS',
            'empty_rounds':2,'profit_bps':500,'loss_bps':500,'idle_seconds':120,'mark_max_age':90,
            'return_basis':'canonical net liquidation PnL / paper entry notional'})
    arm(room,t)
    t[0]=1100;mark(bridge,t,event,-.0005,gross=0.);room.tick()
    b=room.view()['bag']
    assert b['auto_exit']['policy']['version']==1 and b['auto_exit']['held_seconds'] is None
    assert b['exit_intent']['reason']=='AUTO_EXIT_STOP_LOSS' and b['exit_intent']['trigger_basis']=='NET'


def test_v2_max_hold_closes_a_bag_nobody_ever_voted_on(tmp_path):
    room,bridge,t,event,_=opened(tmp_path,entry_ts=1000)
    advance(room,bridge,t,event,3599)
    b=room.view()['bag']
    assert b['status']=='OPEN' and b['auto_exit']['status']=='ARMED'
    assert b['auto_exit']['held_seconds']==3599
    advance(room,bridge,t,event,3600)
    b=room.view()['bag']
    assert b['status']=='EXIT_REQUESTED' and b['exit_intent']['reason']=='AUTO_EXIT_MAX_HOLD'
    assert b['exit_intent']['trigger_held_seconds']>=3600


def test_v2_a_finalized_hold_restarts_the_max_hold_clock(tmp_path):
    room,bridge,t,event,w=opened(tmp_path,entry_ts=1000)
    advance(room,bridge,t,event,3000)
    b=room.view()['bag']
    assert b['status']=='OPEN' and b['auto_exit']['held_seconds']>=3000
    vote(room,b['id'],w[0],'HOLD',round_=b['round']['number'])
    advance(room,bridge,t,event,3040)
    auto=room.view()['bag']['auto_exit']
    assert auto['empty_rounds']==0 and auto['held_seconds']<120
    anchor=t[0]-auto['held_seconds']
    advance(room,bridge,t,event,3600)
    assert room.view()['bag']['status']=='OPEN'   # 3600s open, ~600s since the HOLD
    advance(room,bridge,t,event,anchor+3631-1000)
    b=room.view()['bag']
    assert b['exit_intent']['reason']=='AUTO_EXIT_MAX_HOLD'
    assert b['exit_intent']['trigger_held_seconds']>=3600


def test_v2_a_pending_vote_pauses_even_the_maximum_hold(tmp_path):
    room,bridge,t,event,w=opened(tmp_path,entry_ts=1000)
    advance(room,bridge,t,event,3580)
    b=room.view()['bag']
    while b['round']['closes_at']<=1000+3600:  # a round that is still open at the deadline
        t[0]+=16;mark(bridge,t,event);room.tick();b=room.view()['bag']
    assert b['status']=='OPEN' and t[0]<1000+3600
    vote(room,b['id'],w[0],'HOLD',round_=b['round']['number'])
    t[0]=1000+3600;mark(bridge,t,event);room.tick()
    auto=room.view()['bag']['auto_exit']
    assert room.view()['bag']['status']=='OPEN' and auto['status']=='VOTE_PENDING'
    assert auto['held_seconds']>=3600 and auto['trigger'] is None


def test_v2_inactivity_accepts_a_longer_measured_silence(tmp_path):
    room,bridge,t,event,_=opened(tmp_path,entry_ts=1000);arm(room,t)
    t[0]=1700
    # A 120s window that reports its own last trade proves the 600s silence.
    short={'available':True,'idle':True,'window_seconds':120,'observed_through_ts':t[0],
           'last_trade_ts':t[0]-599}
    mark(bridge,t,event,activity=short);room.tick()
    assert room.view()['bag']['status']=='OPEN'
    mark(bridge,t,event,activity={**short,'last_trade_ts':t[0]-600});room.tick()
    assert room.view()['bag']['exit_intent']['reason']=='AUTO_EXIT_INACTIVE'


def test_v2_policy_is_published_for_the_browser(tmp_path):
    room,bridge,t,event,_=opened(tmp_path,entry_ts=1000);arm(room,t)
    t[0]=1700;mark(bridge,t,event);room.tick()
    policy=room.view()['bag']['auto_exit']['policy']
    assert policy['version']==2 and policy['return_basis']=='GROSS'
    assert policy['profit_bps']==2000 and policy['loss_bps']==2000
    assert policy['idle_seconds']==600 and policy['min_hold_seconds']==600
    assert policy['max_hold_seconds']==3600 and policy['empty_rounds']==2


def test_hold_window_configuration_is_bounded():
    base=dict(holder_source='FIXTURE',fixture_holders_file='holders.json')
    for bad in ({'autoexit_min_hold_seconds':-1},{'autoexit_min_hold_seconds':86401},
                {'autoexit_max_hold_seconds':299},{'autoexit_max_hold_seconds':86401},
                {'autoexit_max_hold_seconds':600},{'autoexit_return_basis':'gross'}):
        with pytest.raises(ValueError):Config(**base,**bad)
    assert Config(**base).autoexit_max_hold_seconds==3600
