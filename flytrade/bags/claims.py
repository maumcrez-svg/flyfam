"""Read-only, paginated claim projections. No signer, transaction sender or RPC."""
import json
from .config import address
from .store import Store
from .live_pons import calldata
from .economics import bag_key

def claims(room,wallet,*,bag_id=None,before=2**63-1):
    wallet=address(wallet)
    with room.store.read() as db:
        sql="""SELECT b.number,b.id,d.evidence AS distribution,d.status,d.deadline,d.funding_tx,
          a.evidence AS allocation,c.tx_hash AS claimed_tx FROM bag_allocations a
          JOIN bags b ON b.id=a.bag_id JOIN bag_distributions d ON d.bag_id=a.bag_id
          LEFT JOIN holder_claims c ON c.bag_id=a.bag_id AND c.wallet=a.wallet
          WHERE a.wallet=? AND b.number<?"""
        args=[wallet,int(before)]
        if bag_id is not None:sql+=' AND b.id=?';args.append(bag_id)
        rows=db.execute(sql+' ORDER BY b.number DESC LIMIT 50',args).fetchall()
        fresh=bool(Store.get(db,'vault_log_complete',False)) and 0<=room.now()-Store.get(db,'vault_verified_at',0)<60
        output=[]
        for row in rows:
            e=json.loads(row['distribution']);a=json.loads(row['allocation'])
            if e.get('mode')=='PAYOUT_WALLET':
                from .payout_views import claim_view
                output.append(claim_view(db,room,row,e,a,wallet));continue
            status=row['status']
            if status=='OPEN' and row['deadline'] and room.now()>=row['deadline']:status='EXPIRED'
            claimable=bool(fresh and status=='OPEN' and not row['claimed_tx'] and int(a['amount'])>0)
            tx={'to':e['vault'],'value':'0x0','chainId':hex(e['chain_id']),
                'data':calldata('claim(bytes32,address,uint256,bytes32[])',['bytes32','address','uint256','bytes32[]'],
                    [bag_key(row['id']),wallet,int(a['amount']),[bytes.fromhex(x[2:]) for x in a['proof']]])}
            output.append({'bag_id':row['id'],'number':row['number'],'wallet':wallet,'status':status,
                'allocation':a,'eligible_balance_total':e['eligible_balance_total'],'claimable':claimable,
                'claimed_transaction':row['claimed_tx'],'deadline':row['deadline'],'vault':e['vault'],
                'funding_transaction':row['funding_tx'],'fixture':e['fixture'],'asset':e['asset'],
                'transaction':tx if claimable else None,'projection_fresh':fresh})
    return {'wallet':wallet,'claims':output,'next_before':rows[-1]['number'] if len(rows)==50 else None}
