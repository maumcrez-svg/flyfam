"""Read-only payout projections. No signer, no RPC and no financial computation in JS."""
import json
from decimal import Decimal
from .payout import MODE,public_job,liabilities
from .store import Store


def claim_view(db,room,row,e,a,wallet):
    job=db.execute("SELECT * FROM payout_jobs WHERE bag_id=? AND wallet=? AND kind='CLAIM'",(row['id'],wallet)).fetchone()
    state=public_job(job) if job else None
    expired=bool(row['deadline'] and room.now()>=row['deadline'])
    status=state['status'] if state else 'EXPIRED' if expired else row['status']
    paid=bool(state and state['status']=='CONFIRMED')
    distribution=db.execute('SELECT paid,sweep_tx FROM bag_distributions WHERE bag_id=?',(row['id'],)).fetchone()
    reconciliation=Store.get(db,'payout_reconciliation',{})
    fresh=0<=room.now()-reconciliation.get('checked_at',0)<60
    return {'mode':MODE,'bag_id':row['id'],'number':row['number'],'wallet':wallet,'recipient':wallet,
        'status':status,'allocation':a,'eligible_balance_total':e['eligible_balance_total'],
        'economic_share_percent':str((Decimal(a['snapshot_balance'])*100/Decimal(e['eligible_balance_total'])).quantize(Decimal('.0001'))),
        'claimable':bool(not job and row['status']=='OPEN' and not expired and int(a['amount'])>0 and fresh and reconciliation.get('status')=='SOLVENT'),
        'claimed_transaction':state['transaction_hash'] if paid else None,
        'transaction_hash':state['transaction_hash'] if state else None,'payment':state,
        'deadline':row['deadline'],'payout_wallet':e['wallet'],'vault':None,'asset':e['asset'],'fixture':e['fixture'],
        'funding_transaction':row['funding_tx'],'funded_amount':e['funded_amount'],'allocated_amount':e['allocated_amount'],
        'paid_amount':distribution['paid'],'unclaimed_amount':str(int(e['funded_amount'])-int(distribution['paid'])) if row['status']!='SWEPT' else '0',
        'sweep_transaction':distribution['sweep_tx'],'snapshot_root':e['snapshot_root'],'projection_fresh':fresh,
        'transaction':None,'gas_paid_by_holder':False}


def summary(room):
    with room.store.read() as db:
        config=Store.get(db,'payout_config',{});recon=Store.get(db,'payout_reconciliation')
        funded=paid=swept=allocated=dust=0
        for r in db.execute("SELECT evidence,status,paid,funding_tx FROM bag_distributions WHERE json_extract(evidence,'$.mode')=?",(MODE,)):
            e=json.loads(r['evidence']);allocated+=int(e['allocated_amount']);dust+=int(e['rounding_dust'])
            if r['funding_tx']:
                amount=int(e['funded_amount']);funded+=amount;paid+=int(r['paid'])
                if r['status']=='SWEPT':swept+=amount-int(r['paid'])
        rows=db.execute("SELECT d.*,b.number,b.snapshot FROM bag_distributions d JOIN bags b ON b.id=d.bag_id WHERE json_extract(d.evidence,'$.mode')=? ORDER BY b.number DESC LIMIT 20",(MODE,)).fetchall()
        distributions=[]
        for r in rows:
            e=json.loads(r['evidence']);snapshot=json.loads(r['snapshot'])
            distributions.append({'bag_id':r['bag_id'],'number':r['number'],'status':'EXPIRED' if r['status']=='OPEN' and r['deadline'] and room.now()>=r['deadline'] else r['status'],
                'realized_holder_profit':e['funded_amount'],'funded':e['funded_amount'] if r['funding_tx'] else '0',
                'allocated':e['allocated_amount'],'paid':r['paid'],'unclaimed':str(int(e['funded_amount'])-int(r['paid'])) if r['funding_tx'] and r['status']!='SWEPT' else '0',
                'rounding_dust':e['rounding_dust'],'snapshot_block':snapshot['snapshot_block'],'snapshot_root':e['snapshot_root'],
                'deadline':r['deadline'],'funding_transaction':r['funding_tx'],'sweep_transaction':r['sweep_tx'],
                'payout_wallet':e['wallet'],'fixture':e['fixture']})
        return {'mode':MODE,'configured':bool(config),'payout_wallet':config.get('wallet'),'fly_wallet':config.get('fly_wallet'),
            'chain_id':4663,'asset':'NATIVE_ETH','fixture':config.get('fixture',False),'funded':str(funded),
            'allocated':str(allocated),'paid':str(paid),'unclaimed':str(liabilities(db)),'returned_to_fly':str(swept),
            'rounding_dust':str(dust),'reconciliation':recon,'gas_sponsor':config.get('gas_sponsor'),
            'distributions':distributions,'claims_require_signature':True,'holder_pays_gas':False}
