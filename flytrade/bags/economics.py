"""Integer bag economics. Votes and creator fees never enter allocations."""
from eth_abi import encode
from eth_utils import keccak
from .config import address


def uint(value):
    if type(value) is str and value.isascii() and value.isdecimal(): value=int(value)
    if type(value) is not int or not 0<=value<2**256: raise ValueError('Expected uint256 base units')
    return value


def bag_key(bag_id): return keccak(text=bag_id)


def claim_leaf(chain,vault,bag_id,wallet,amount):
    return keccak(keccak(encode(['uint256','address','bytes32','address','uint256'],
        [uint(chain),address(vault),bag_key(bag_id),address(wallet),uint(amount)])))


def tree(leaves):
    if not leaves:return '0x'+'00'*32,[]
    levels=[list(leaves)]
    while len(levels[-1])>1:
        old=levels[-1]
        levels.append([keccak(b''.join(sorted([old[i],old[min(i+1,len(old)-1)]]))) for i in range(0,len(old),2)])
    proofs=[]
    for index in range(len(leaves)):
        proof=[]
        for level in levels[:-1]:
            proof.append('0x'+level[min(index^1,len(level)-1)].hex());index//=2
        proofs.append(proof)
    return '0x'+levels[-1][0].hex(),proofs


def snapshot_tree(chain,token,block,balances):
    rows=sorted((address(w),uint(n)) for w,n in balances.items())
    return tree([keccak(keccak(encode(['uint256','address','uint256','address','uint256'],
        [chain,token,block,w,n]))) for w,n in rows])[0]


def allocate(chain,vault,bag_id,profit,balances):
    profit=uint(profit)
    rows=sorted((address(w),uint(n)) for w,n in balances.items())
    if len({w for w,n in rows})!=len(rows) or any(n==0 for w,n in rows):raise ValueError('Invalid snapshot balance set')
    total=sum(n for _,n in rows)
    if not total and profit:raise ValueError('No eligible balances; keep profit reserved')
    amounts=[profit*n//total for _,n in rows] if total else []
    root,proofs=tree([claim_leaf(chain,vault,bag_id,w,a) for (w,_),a in zip(rows,amounts)])
    return {'bag_id':bag_id,'bag_key':'0x'+bag_key(bag_id).hex(),'chain_id':chain,'vault':address(vault),
        'asset':'NATIVE_ETH','funded_amount':str(profit),'allocated_amount':str(sum(amounts)),
        'rounding_dust':str(profit-sum(amounts)),'eligible_balance_total':str(total),'root':root,
        'allocations':[{'wallet':w,'snapshot_balance':str(n),'amount':str(a),'proof':pr}
            for (w,n),a,pr in zip(rows,amounts,proofs)]}


def waterfall(*,spent,received,buy_gas,sell_gas,approval_gas=0,failed_gas=0):
    # spent already includes buy fees; received is AFTER sell fees. No double deduction.
    spent,received,buy_gas,sell_gas,approval_gas,failed_gas=map(uint,(spent,received,buy_gas,sell_gas,approval_gas,failed_gas))
    entry=spent+buy_gas
    exit_net=received-sell_gas-approval_gas-failed_gas
    pnl=exit_net-entry
    return {'asset':'NATIVE_ETH','entry_principal':str(entry),'trade_quote_spent':str(spent),
        'exit_quote_received':str(received),'buy_gas':str(buy_gas),'sell_gas':str(sell_gas),
        'approval_gas':str(approval_gas),'failed_gas':str(failed_gas),
        'net_exit_proceeds':str(exit_net),'net_realized_pnl':str(pnl),
        'principal_returned_to_fly':str(min(entry,max(0,exit_net))),
        'additional_bankroll_cost':str(max(0,-exit_net)),'holder_profit':str(max(0,pnl))}
