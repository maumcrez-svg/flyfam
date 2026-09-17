"""Bounded contract tests: real-source shape, fixture membership, same PAPER executor.
All chain observations in this test are synthetic; runtime/browser proof is separate.
"""
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from flytrade.bags.config import Config
from flytrade.bags.holder_source import FixtureHolders,build_source
from flytrade.bags.bridge import WorkerBridge,CommunityExecution
from flytrade.bags.service import Room,money
from flytrade.bags.store import Store,digest
from flytrade.bags.test_holders import accounts,sign_challenge
from flytrade.product.history import ProductHistory
from flytrade.product.live import ProductPaperExecution
from .test_room import Node,vote


def setup(tmp_path):
    w=accounts();fixture=tmp_path/'holders.json'
    fixture.write_text(json.dumps({'holder_source':'FIXTURE','fixture_id':'test','chain_id':4663,
        'balances':{w[0].address:'1',w[1].address:'1000000'}}))
    config=Config(holder_source='FIXTURE',fixture_holders_file=str(fixture))
    store=Store(tmp_path/'bags.sqlite');t=[1000.0];node=Node()
    room=Room(store,config,indexer=build_source(store,config,node),now=lambda:t[0]);bridge=WorkerBridge(room,'pons-live','frozen')
    event={'kind':'OPEN','run_id':'pons-live','mode':'LIVE_PAPER','execution':'PAPER','venue':'PONS','seq':17,'episode_id':22,
        'token':'0x'+'34'*20,'entry_block':11,'entry_ts':110,'quantity':100,'entry_fill_price':.0001,'fee_eth':.00001}
    return room,bridge,node,t,event,w


def test_same_position_votes_then_close_and_readiness_only_after_proof(tmp_path):
    room,bridge,node,t,opened,w=setup(tmp_path)
    assert room.config.configured and room.config.token==''
    bridge.event(opened);bridge.event(opened);room.tick()
    b=room.view()['bag'];assert b['episode_id']=='pons-live:22' and b['entry']['canonical_event_hash']==digest(opened)
    assert b['token']==opened['token'] and b['entry']['quantity']==opened['quantity']
    assert b['snapshot']['token'] is None and b['snapshot']['snapshot_block']==10
    assert b['snapshot']['holder_source']=='FIXTURE' and not room.view()['bag_configured']
    with pytest.raises(ValueError):vote(room,b['id'],w[2],'EXIT')
    x=type('TestExecution',(CommunityExecution,ProductPaperExecution),{})();x.bag_room=room;x.bag_run_id='pons-live';x.account.position=SimpleNamespace(episode_id=22)
    x.horizon_ts=1;assert not x.due_for_horizon(3000)
    vote(room,b['id'],w[0],'HOLD');vote(room,b['id'],w[1],'HOLD');t[0]+=31;room.tick()
    assert not x.due_for_horizon(3000)
    # A reopened Room reads exactly the durable snapshot/round, with no new holder set.
    restored=Room(Store(room.store.path),room.config,now=lambda:t[0]);assert restored.view()['bag']['round']['number']==2
    vote(restored,b['id'],w[0],'EXIT',round_=2);vote(restored,b['id'],w[1],'EXIT',round_=2);t[0]+=31;restored.tick()
    assert x.due_for_horizon(3000) and x.exit_close_reason.value=='COMMUNITY_EXIT'
    assert not room.view()['bag_configured']
    mark={**opened,'kind':'MARK','seq':18,'unrealised_eth':.003};bridge.event(mark)
    assert room.view()['bag']['market']['unrealised_eth']==.003
    close={**opened,'kind':'CLOSE','seq':19,'settlement':'SETTLED_FROZEN','close_reason':'COMMUNITY_EXIT',
        'net_pnl_eth':.003,'fees_eth':.0002,'gross_pnl_eth':.0032,'exit_block':20}
    bridge.event(close);bridge.event(close)
    view=room.view();assert view['bag_configured'] and view['bag']['status']=='CLOSED'
    assert view['bag']['result']['net_pnl_wei']==str(money(close['net_pnl_eth']))
    assert view['bag']['result']['claimable'] is False and len(view['history'])==1
    with room.store.read() as db:
        proof=Store.get(db,'phase_a_bridge_proof');assert proof['entry_source_event']=='p1:pons-live:17' and proof['close_source_event']=='p1:pons-live:19'
        assert db.execute("SELECT count(*) FROM audit WHERE kind='EXIT_REQUESTED'").fetchone()[0]==1
    with pytest.raises(ValueError):bridge.event({**opened,'execution':'LIVE'})
    with pytest.raises(ValueError):bridge.event({**opened,'run_id':'bag-demo'})


def test_adoption_uses_exact_restored_fill_and_does_not_cancel_pending_exit(tmp_path):
    room,bridge,node,t,event,w=setup(tmp_path);history=ProductHistory(tmp_path/'history.sqlite')
    history.ingest_p1(event)
    fill=SimpleNamespace(bar_index=11,ts=110,fill_price=.0001,fee=.000010123456)
    position=SimpleNamespace(episode_id=22,symbol=event['token'],quantity=100,entry=fill)
    assert not bridge.adopt(position,history,pending={'episode_id':22}) and room.view()['bag'] is None
    position.quantity=99
    with pytest.raises(ValueError):bridge.adopt(position,history)
    position.quantity=100;assert bridge.adopt(position,history);assert bridge.adopt(position,history)
    bag=room.view()['bag'];assert bag['entry']['entry_principal_eth']==100*.0001+fill.fee
    assert bag['entry']['canonical_event_hash']==digest(event)
    assert bag['entry']['fee_eth']==event['fee_eth'] # original evidence is not rewritten
    history.close()


def test_test_signer_only_signs_existing_bound_challenges_and_disabled_after_activation(tmp_path):
    room,bridge,node,t,event,w=setup(tmp_path)
    msg=room.challenge({'wallet':w[0].address,'action':'AUTH'},'test')
    sig=sign_challenge(room,{'nonce':msg['message']['nonce']})
    assert room.submit(msg['message']['nonce'],sig['signature'],'test')['authenticated']
    with pytest.raises(ValueError):sign_challenge(room,{'nonce':msg['message']['nonce']})
    with pytest.raises(ValueError):sign_challenge(room,{'typed':msg})
    with pytest.raises(ValueError):Config(holder_source='FIXTURE',fixture_holders_file='x',token='0x'+'12'*20)
    assert not Config().configured
    from dataclasses import replace
    room.config=replace(room.config,holder_source='REAL_HOLDERS')
    with pytest.raises(ValueError):sign_challenge(room,{'nonce':'f'*48})


@pytest.mark.parametrize('legacy_cursor',[False,True])
def test_token_activation_backfills_deployment_not_fixture_header(tmp_path,legacy_cursor):
    from .test_room import TOKEN,ZERO
    room,bridge,node,t,event,w=setup(tmp_path)
    room.indexer.sync()
    with room.store.transaction() as db:
        assert Store.get(db,'fixture_holder_cursor')['block']==10
        assert Store.get(db,'holder_cursor') is None
        if legacy_cursor:Store.put(db,'holder_cursor',Store.get(db,'fixture_holder_cursor'))
    node.transfer(2,ZERO,w[0].address,99)
    node.transfer(3,ZERO,w[2].address,250)
    production=Config(token=TOKEN,deployment_block=1)
    index=build_source(room.store,production,node);index.sync()
    evidence,holders=index.materialize(11)
    assert evidence['snapshot_balances']=={w[0].address.lower():'99',w[2].address.lower():'250'}
    assert w[1].address.lower() not in holders
    assert evidence['token']==TOKEN
