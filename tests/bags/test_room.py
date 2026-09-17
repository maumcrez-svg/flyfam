"""Critical Bag Room invariants. Synthetic ERC-20 evidence and test-only wallets."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import pytest
from eth_account import Account
from eth_account.messages import encode_typed_data
from flytrade.bags.config import Config
from flytrade.bags.store import Store,digest
from flytrade.bags.indexer import Indexer,TRANSFER,ZERO
from flytrade.bags.service import Room
from flytrade.bags.bridge import CommunityExecution
from flytrade.product.live import ProductPaperExecution

TOKEN='0x'+'12'*20
TRADED='0x'+'34'*20
W=[Account.from_key(i.to_bytes(32,'big')) for i in (1,2,3)]

class Node:
    def __init__(self):self.final=10;self.logs=[];self.reorg=False
    def block(self,n):
        n=self.final if n=='finalized' else n
        return {'number':hex(n),'hash':'0x'+f'{n+(100 if self.reorg else 0):064x}','timestamp':hex(100+n)}
    def call(self,method,params):
        if method=='eth_chainId':return hex(4663)
        if method=='eth_getLogs':
            q=params[0];return [l for l in self.logs if int(q['fromBlock'],16)<=int(l['blockNumber'],16)<=int(q['toBlock'],16)]
        raise AssertionError(method)
    def transfer(self,block,sender,recipient,n,index=0):
        self.logs.append({'address':TOKEN,'topics':[TRANSFER,'0x'+sender[2:].lower().zfill(64),'0x'+recipient[2:].lower().zfill(64)],
                          'data':'0x'+f'{n:064x}','blockNumber':hex(block),'blockHash':self.block(block)['hash'],'logIndex':hex(index),'transactionHash':'0x'+f'{block:064x}'})

@pytest.fixture
def setup(tmp_path):
    node=Node();node.transfer(2,ZERO,W[0].address,1);node.transfer(3,ZERO,W[1].address,10**30)
    t=[1000.0];config=Config(token=TOKEN,deployment_block=1,fixture=True)
    store=Store(tmp_path/'bags.sqlite');room=Room(store,config,indexer=Indexer(store,config,node),now=lambda:t[0])
    event={'kind':'OPEN','token':TRADED,'entry_block':11,'entry_ts':110,'quantity':100,'entry_fill_price':.0001,'fee_eth':.00001}
    bag=room.create('open:1','fixture:1',event);room.tick()
    return room,node,t,bag

def vote(room,bag,who,choice,round_=1,action='VOTE',content=''):
    msg=room.challenge({'wallet':who.address,'action':action,'bag_id':bag,'round_id':round_,'choice':choice,'content':content},who.address)
    signature=who.sign_message(encode_typed_data(full_message=msg)).signature.hex()
    result=room.submit(msg['message']['nonce'],signature,who.address)
    return result,msg,signature

def test_snapshot_fixed_weight_buy_after_and_sale_after(setup):
    room,node,t,bag=setup
    node.transfer(12,ZERO,W[2].address,500)
    node.transfer(13,W[0].address,W[2].address,1)
    node.final=15;room.indexer.sync()
    assert room.proof(bag,W[0].address)['eligible']
    assert not room.proof(bag,W[2].address)['eligible']
    snap=room.view()['bag']['snapshot'];assert snap['snapshot_block']==10
    assert snap['snapshot_hash']==digest(sorted([w.address.lower() for w in W[:2]]))
    vote(room,bag,W[0],'HOLD');vote(room,bag,W[1],'EXIT')
    r=room.view()['bag']['round'];assert (r['hold'],r['exit'])==(1,1)
    with pytest.raises(ValueError):vote(room,bag,W[2],'EXIT')
    t[0]+=31;room.tick();assert room.view()['bag']['status']=='EXIT_REQUESTED'

def test_replacement_replay_expiry_and_concurrent_finalization(setup):
    room,node,t,bag=setup
    _,m,sig=vote(room,bag,W[0],'EXIT')
    with pytest.raises(ValueError):room.submit(m['message']['nonce'],sig,'x')
    vote(room,bag,W[0],'HOLD')
    assert room.view()['bag']['round']['votes_cast']==1
    pending=room.challenge({'wallet':W[1].address,'action':'VOTE','bag_id':bag,'round_id':1,'choice':'EXIT'},'y')
    t[0]+=31
    with ThreadPoolExecutor(2) as pool:list(pool.map(lambda _:room.tick(),range(2)))
    assert room.view()['bag']['round']['number']==2
    sig=W[1].sign_message(encode_typed_data(full_message=pending)).signature.hex()
    with pytest.raises(ValueError):room.submit(pending['message']['nonce'],sig,'y')
    with room.store.read() as db:
        assert db.execute("SELECT count(*) FROM audit WHERE kind='COMMUNITY_HOLD'").fetchone()[0]==1
        assert db.execute("SELECT count(*) FROM audit WHERE kind='VOTE_REPLACED'").fetchone()[0]==1
    t[0]+=130
    with pytest.raises(ValueError):room.submit(pending['message']['nonce'],sig,'y')

def test_zero_votes_hold_and_no_repeat_round_results(setup):
    room,_,t,bag=setup;t[0]+=31;room.tick();room.tick()
    b=room.view()['bag'];assert b['status']=='OPEN';assert b['round']['number']==2
    assert b['rounds'][1]['result']['decision']=='NO_QUORUM_HOLD'

@pytest.mark.parametrize('pnl',[.003,-.002,0])
def test_vault_exact_once_and_losses_never_credit(setup,pnl):
    room,_,t,bag=setup
    event={'kind':'CLOSE','net_pnl_eth':pnl,'gross_pnl_eth':pnl+.0002,'fees_eth':.0002,'close_reason':'COMMUNITY_EXIT','settlement':'SETTLED_FROZEN'}
    room.close('fixture:1','close:1',event);room.close('fixture:1','close:1',event)
    assert room.vault_reserved()==int(max(pnl,0)*1e18)
    assert len(room.view()['history'])==1
    with room.store.read() as db:
        assert db.execute("SELECT count(*) FROM audit WHERE kind='BAG_CLOSED'").fetchone()[0]==1
        assert db.execute("SELECT count(*) FROM audit WHERE kind='VAULT_CREDIT'").fetchone()[0]==(1 if pnl>0 else 0)


def test_chat_authorization_and_plain_text(setup):
    room,_,_,bag=setup
    vote(room,bag,W[0],'',action='CHAT',content='<img src=x onerror=alert(1)>')
    assert room.view()['chat'][0]['message']=='<img src=x onerror=alert(1)>'
    assert room.view()['chat'][0]['holder'] is True
    with pytest.raises(ValueError):vote(room,bag,W[0],'',action='CHAT',content='spam')


def test_a_verified_non_holder_can_chat_but_cannot_vote(setup):
    """Owner decision, 2026-09-17: the room talks to everyone, it votes as holders.

    ``W[2]`` held nothing at the snapshot block, so it is not in ``eligible``.
    It may CHAT — with a signature, under the same rate limit, tagged as not a
    holder — and it may not VOTE. Nothing may be posted unsigned.
    """
    room,_,_,bag=setup
    assert not room.proof(bag,W[2].address)['eligible']
    result,_,_=vote(room,bag,W[2],'',action='CHAT',content='gm from outside the snapshot')
    assert result=={'accepted':True,'wallet':W[2].address.lower(),'action':'CHAT'}
    posted=room.view()['chat'][-1]
    assert posted['message']=='gm from outside the snapshot'
    assert posted['wallet']==W[2].address.lower()
    assert posted['holder'] is False
    # the same wallet, the same room, a vote: still refused by the snapshot
    with pytest.raises(ValueError,match='not eligible'):vote(room,bag,W[2],'HOLD')
    assert room.view()['bag']['round']['votes_cast']==0
    # and a chat challenge is still a signature: another signer is not accepted
    message=room.challenge({'wallet':W[2].address,'action':'CHAT','bag_id':bag,'round_id':0,'choice':'','content':'not mine'},'c')
    signature=W[1].sign_message(encode_typed_data(full_message=message)).signature.hex()
    with pytest.raises(ValueError):room.submit(message['message']['nonce'],signature,'c')
    # a holder's own message is still tagged CREW
    vote(room,bag,W[0],'',action='CHAT',content='crew here')
    assert room.view()['chat'][-1]['holder'] is True


def test_wrong_signer_domain_payload_and_finalized_reorg(setup):
    room,node,_,bag=setup
    m=room.challenge({'wallet':W[0].address,'action':'VOTE','bag_id':bag,'round_id':1,'choice':'HOLD'},'x')
    for variant,signer in [('wrong_signer',W[1]),('tamper',W[0])]:
        changed=deepcopy(m)
        if variant=='tamper':changed['message']['choice']='EXIT'
        sig=signer.sign_message(encode_typed_data(full_message=changed)).signature.hex()
        with pytest.raises(ValueError):room.submit(m['message']['nonce'],sig,'x')
    node.reorg=True
    with pytest.raises(ValueError,match='FINALIZED_REORG'):room.indexer.sync()


def test_index_ahead_rewinds_to_entry_and_explicit_exclusions(tmp_path):
    n=Node();n.final=20;n.transfer(2,ZERO,W[0].address,1);n.transfer(12,ZERO,W[1].address,1)
    config=Config(token=TOKEN,deployment_block=1,excluded=(W[0].address,),fixture=True)
    store=Store(tmp_path/'index.sqlite');ix=Indexer(store,config,n);ix.sync()
    proof,eligible=ix.materialize(11)
    assert proof['snapshot_block']==10;assert eligible==[]
    # The later holder is legitimate in the next snapshot; no automatic contract/pool filters.
    proof,eligible=ix.materialize(21);assert eligible==[W[1].address.lower()]


def test_dropping_one_address_from_the_exclusion_enfranchises_only_that_wallet(tmp_path):
    """2026-09-17: ops votes; the curve stays out. The list is exactly what is configured."""
    curve,ops,holder=(w.address for w in W)
    def snapshot(excluded,name):
        n=Node();n.final=20
        n.transfer(2,ZERO,curve,10**24,0);n.transfer(2,ZERO,ops,39*10**24,1);n.transfer(3,ZERO,holder,10**21)
        config=Config(token=TOKEN,deployment_block=1,excluded=excluded,fixture=True)
        store=Store(tmp_path/name);ix=Indexer(store,config,n);ix.sync()
        return ix.materialize(21)
    before=snapshot((curve,ops),'before.sqlite')
    after=snapshot((curve,),'after.sqlite')
    assert before[1]==[holder.lower()]
    assert after[1]==sorted([holder.lower(),ops.lower()])
    assert curve.lower() not in after[1]
    assert after[0]['eligible_wallet_count']==before[0]['eligible_wallet_count']+1
    assert after[0]['excluded_addresses']==[curve.lower()]


def test_community_ignores_old_horizon_and_has_one_stable_intent(setup):
    from types import SimpleNamespace
    room,_,t,bag=setup
    cls=type('TestCommunity',(CommunityExecution,ProductPaperExecution),{})
    x=cls();x.bag_room=room;x.bag_run_id='fixture';x.account.position=SimpleNamespace(episode_id=1)
    x.horizon_ts=1
    assert not x.due_for_horizon(2000)
    vote(room,bag,W[0],'EXIT');t[0]+=31;room.tick()
    assert x.due_for_horizon(2000)
    intent=json.loads(room.active_for('fixture:1')['exit_intent'])
    room.tick();assert json.loads(room.active_for('fixture:1')['exit_intent'])==intent
    assert x.horizon_ts==intent['requested_at']+x.latency_s
    assert x.exit_close_reason.value=='COMMUNITY_EXIT'


def test_contract_wallet_uses_erc1271_without_changing_eligibility(setup):
    from flytrade.bags.signatures import typed,verify
    room,_,t,bag=setup
    contract='0x'+'ab'*20
    message=typed(room.config,contract,'AUTH','',0,'','',t[0])
    sig=W[0].sign_message(encode_typed_data(full_message=message)).signature.hex()
    class ContractRpc:
        def call(self,method,params):
            if method=='eth_chainId':return hex(4663)
            if method=='eth_getCode':return '0x6001'
            assert method=='eth_call' and params[0]['to']==contract
            assert params[0]['data'].startswith('0x1626ba7e')
            return '0x1626ba7e'+'00'*28
    assert verify(message,sig,ContractRpc())==contract
    with pytest.raises(ValueError):verify(message,sig)


def test_closed_receipt_blocks_stale_account_from_second_exit(setup):
    from types import SimpleNamespace
    from flytrade.product.history import RecoveryError
    room,_,_,bag=setup
    room.close('fixture:1','closed',{'kind':'CLOSE','settlement':'SETTLED_FROZEN','net_pnl_eth':0,'fees_eth':.0001,'gross_pnl_eth':.0001,'close_reason':'COMMUNITY_EXIT'})
    x=type('Execution',(CommunityExecution,ProductPaperExecution),{})()
    x.bag_room=room;x.bag_run_id='fixture';x.account.position=SimpleNamespace(episode_id=1)
    with pytest.raises(RecoveryError):x.due_for_horizon(5000)


def test_vote_waiting_for_writer_lock_cannot_cross_round_deadline(setup):
    import threading,time
    room,_,t,bag=setup
    m=room.challenge({'wallet':W[0].address,'action':'VOTE','bag_id':bag,'round_id':1,'choice':'HOLD'},'lock-test')
    sig=W[0].sign_message(encode_typed_data(full_message=m)).signature.hex()
    outcome=[]
    def submit():
        try:room.submit(m['message']['nonce'],sig,'lock-test');outcome.append('accepted')
        except ValueError:outcome.append('rejected')
    with room.store.transaction():
        thread=threading.Thread(target=submit);thread.start();time.sleep(.15);t[0]+=31
    thread.join(3)
    assert outcome==['rejected']
    assert room.view()['bag']['round']['votes_cast']==0
