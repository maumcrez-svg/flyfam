"""Evidence for inactivity: covered curve trades or swaps of the verified V4 pool."""
from flytrade.pons import context_v2, paper
from flytrade.pons.rpc import RpcError, keccak256_hex

# Uniswap v4-core IPoolManager.Swap; verified Pons PoolManager uses this ABI.
SWAP=keccak256_hex(b'Swap(bytes32,address,int128,int128,uint160,uint128,int24,uint24)')


def observe(execution,tape,cutoff,clock,mark,window):
    missing={'available':False,'idle':None,'window_seconds':window}
    if not mark.get('available'):return missing
    if mark.get('route')!='PONS_V4':
        if tape.completed_by(cutoff) or tape.coverage_end_ts is None or tape.coverage_end_ts<cutoff:return missing
        facts=context_v2.recent_activity(tape,cutoff,window_s=window)
        since=facts['since_last_trade_s']
        if since is None:return missing
        return {'available':True,'source':'CANONICAL_CURVE_TRADES','observed_through_ts':int(cutoff),
            'window_seconds':window,'last_trade_ts':int(cutoff-since),
            'trades_in_window':facts['trades_in_window'],'idle':since>=window and facts['trades_in_window']==0}
    router=execution.v4;quote=router.last_quote
    if not quote or quote['token']!=tape.token:return missing
    end=quote['block_number'];stamp=quote['block_timestamp'];reads=[]
    hint=clock.block_at_or_after(stamp-window)
    if not hint:return missing
    start=max(int(quote['proof']['graduation']['blockNumber'],16),int(hint['block_number'])-32)
    if start>end or end-start>10000:return missing
    try:
        first=router._header(start,reads)
        if int(first['timestamp'],16)>stamp-window:return missing
        events=router._logs(quote['proof']['pool_manager'],start,end,[SWAP,quote['pool_id']],reads)
        for event in events:
            if (event.get('removed') or event.get('address','').lower()!=quote['proof']['pool_manager'].lower()
                    or event.get('topics',[])[:2]!=[SWAP,quote['pool_id']]
                    or not start<=int(event['blockNumber'],16)<=end):return missing
        last=router._header(end,reads)
        again=router._header(start,reads)
        if last['hash'].lower()!=quote['block_hash'].lower() or again['hash']!=first['hash']:return missing
        # Wider start is conservative; a boundary swap may delay the idle trigger.
        return {'available':True,'source':'VERIFIED_V4_SWAP_LOGS','observed_through_ts':stamp,
            'window_seconds':window,'from_block':start,'to_block':end,
            'from_block_hash':first['hash'],'to_block_hash':last['hash'],
            'covered_from_ts':int(first['timestamp'],16),'observed_swaps':len(events),'idle':not events}
    except (RpcError,paper.Unresolved,KeyError,ValueError):return missing
