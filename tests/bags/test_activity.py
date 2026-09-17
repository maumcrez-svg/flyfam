"""Canonical activity windows, including post-migration pool scope."""
from types import SimpleNamespace as NS
import pytest
from flytrade.bags.activity import observe, SWAP
from flytrade.pons.paper import Unresolved


def test_curve_coverage_and_trade_window(monkeypatch):
    tape=NS(coverage_end_ts=1000,completed_by=lambda _:False)
    monkeypatch.setattr('flytrade.bags.activity.context_v2.recent_activity',
                        lambda *a,**kw:{'since_last_trade_s':130,'trades_in_window':0})
    result=observe(None,tape,1000,None,{'available':True},120)
    assert result['idle'] and result['last_trade_ts']==870
    tape.coverage_end_ts=999
    assert not observe(None,tape,1000,None,{'available':True},120)['available']
    tape.coverage_end_ts=1000;tape.completed_by=lambda _:True
    assert not observe(None,tape,1000,None,{'available':True},120)['available']


@pytest.mark.parametrize('case',['quiet','busy','rpc_error','reorg','missing_window','removed','wrong_pool'])
def test_v4_window_is_verified_and_unavailability_never_counts_as_quiet(case):
    token='0x'+'12'*20;manager='0x'+'34'*20;pool='0x'+'56'*32
    quote={'token':token,'block_number':2000,'block_timestamp':1000,'block_hash':'head',
           'pool_id':pool,'proof':{'pool_manager':manager,'graduation':{'blockNumber':'0x1'}}}
    class Router:
        last_quote=quote
        def _header(self,n,reads):
            if case=='rpc_error':raise Unresolved('RPC_UNAVAILABLE')
            return {'number':hex(n),'timestamp':hex(1000 if n==2000 else 881 if case=='missing_window' else 875),
                    'hash':'changed' if case=='reorg' else 'head' if n==2000 else 'first'}
        def _logs(self,address,start,end,topics,reads):
            assert address==manager and topics==[SWAP,pool]
            return [] if case not in ('busy','removed','wrong_pool') else [
                {'address':manager,'blockNumber':hex(1950),'removed':case=='removed',
                 'topics':[SWAP,'wrong' if case=='wrong_pool' else pool]}]
    result=observe(NS(v4=Router()),NS(token=token),990,NS(block_at_or_after=lambda _:{'block_number':1000}),
                   {'available':True,'route':'PONS_V4'},120)
    if case=='quiet':assert result['available'] and result['idle']
    elif case=='busy':assert result['available'] and not result['idle']
    else:assert not result['available'] and result['idle'] is None
