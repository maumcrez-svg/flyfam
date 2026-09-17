"""Explicit PAPER/test-holder fallback. Never a vote or a neural decision."""
import json
from decimal import Decimal, InvalidOperation
from .store import Store

# The mark publishes a marginal liquidation price, never an exit fill, so the
# gross return is quantity*(marginal_price - entry_fill_price) over the paper
# entry principal: the same quantity the close books as gross_pnl_wei over
# entry_principal_wei, up to the position's own curve impact at liquidation
# (+0.22 to +0.58 percentage points on bags 1-12 of 2026-09-16).
GROSS_RETURN='quantity*(mark marginal_price - entry_fill_price) / paper entry principal'
NET_RETURN='canonical net liquidation PnL / paper entry notional'


def policy_for(config):
    gross=config.autoexit_return_basis=='GROSS'
    return {'version':2,'scope':'REAL_PONS_PAPER_TEST_HOLDERS',
        'empty_rounds':config.autoexit_empty_rounds,'profit_bps':config.autoexit_profit_bps,
        'loss_bps':config.autoexit_loss_bps,'idle_seconds':config.autoexit_idle_seconds,
        'mark_max_age':config.autoexit_mark_max_age,
        'min_hold_seconds':config.autoexit_min_hold_seconds,
        'max_hold_seconds':config.autoexit_max_hold_seconds,
        'return_basis':'GROSS' if gross else 'NET',
        'return_definition':GROSS_RETURN if gross else NET_RETURN}


def number(value):
    if value is None or isinstance(value,bool):return None
    try:
        result=Decimal(str(value))
        return result if result.is_finite() else None
    except (InvalidOperation,ValueError):return None


def principal_of(entry):
    """The paper entry principal, as the close reports it in entry_principal_wei."""
    value=number(entry.get('entry_principal_eth'))
    if value is not None:return value
    quantity=number(entry.get('quantity'));fill=number(entry.get('entry_fill_price'))
    if quantity is None or fill is None:return None
    fee=number(entry.get('entry_fee_unrounded_eth'))
    if fee is None:fee=number(entry.get('fee_eth')) or Decimal(0)
    return quantity*fill+fee


def hold_anchor(db,bag,now,window):
    """Max-hold clock: the entry, or the last finalized community HOLD if later.

    Only rounds finalized inside the window can move the anchor, so the walk is
    bounded by window/round_seconds rows of the (bag_id,number) primary key.
    """
    anchor=Decimal(str(bag['opened_at']));floor=Decimal(str(now))-window
    for row in db.execute("SELECT closes_at,result FROM rounds WHERE bag_id=? AND status='CLOSED' ORDER BY number DESC LIMIT 4096",(bag['id'],)):
        closes=number(row[0])
        if closes is None or closes<floor or closes<=anchor:break
        if (json.loads(row[1]) or {}).get('decision')=='COMMUNITY_HOLD':return closes
    return anchor


def inactive(mark,policy,ts,age):
    """Fresh evidence of at least idle_seconds without a market trade."""
    activity=mark.get('activity') or {}
    observed=number(activity.get('observed_through_ts'));window=policy['idle_seconds']
    if (activity.get('available') is not True or activity.get('idle') is not True
            or observed is None or observed!=ts or age<window):return False
    if activity.get('window_seconds')==window:return True
    # Evidence gathered over a shorter window still proves a longer silence when
    # it carries the last observed trade itself; a shorter silence never does.
    last=number(activity.get('last_trade_ts'))
    return last is not None and observed-last>=window


def projection(db,bag,policy,now):
    """One bounded server projection, shared by the round engine and viewer."""
    empty=0
    for row in db.execute("SELECT result FROM rounds WHERE bag_id=? AND status='CLOSED' ORDER BY number DESC LIMIT ?",(bag['id'],policy['empty_rounds'])):
        if (json.loads(row[0]) or {}).get('decision')!='NO_QUORUM_HOLD':break
        empty+=1
    pending=db.execute("SELECT 1 FROM votes v JOIN rounds r ON r.bag_id=v.bag_id AND r.number=v.round WHERE v.bag_id=? AND r.status='OPEN' LIMIT 1",(bag['id'],)).fetchone() is not None
    status='VOTE_PENDING' if pending else 'ARMED' if empty>=policy['empty_rounds'] else 'COMMUNITY'
    # A policy recorded before the gross rule keeps the exact behaviour it was given.
    basis='GROSS' if policy.get('return_basis')=='GROSS' else 'NET'
    min_hold=Decimal(str(policy.get('min_hold_seconds') or 0));max_hold=number(policy.get('max_hold_seconds'))
    age=Decimal(str(now))-Decimal(str(bag['opened_at']))
    held=None if max_hold is None else Decimal(str(now))-hold_anchor(db,bag,now,max_hold)
    result={'policy':policy,'status':status,'empty_rounds':empty,'trigger':None,'return_basis':basis,
            'net_return':None,'gross_return':None,'age_seconds':float(age),
            'held_seconds':None if held is None else float(held),'observation_status':'UNAVAILABLE'}
    if bag['status']!='OPEN':
        result['status']='CLOSED' if bag['status']=='CLOSED' else 'EXIT_PENDING'
    mark=json.loads(bag['market']) if bag['market'] else {}
    entry=json.loads(bag['entry'])
    ts=number(mark.get('cutoff_ts')); published=number(mark.get('ts'))
    if (mark.get('available') is not True or mark.get('token')!=bag['token']
            or mark.get('execution')!='PAPER' or ts is None or published is None
            or not 0<=Decimal(str(now))-ts<=policy['mark_max_age']
            or not 0<=Decimal(str(now))-published<=policy['mark_max_age']):
        return result
    pnl=number(mark.get('unrealised_eth'));size=number(entry.get('size_eth'))
    if pnl is not None and size is not None and size>0:result['net_return']=float(pnl/size)
    price=number(mark.get('marginal_price'));fill=number(entry.get('entry_fill_price'))
    quantity=number(entry.get('quantity'));principal=principal_of(entry)
    gross=None
    if None not in (price,fill,quantity,principal) and principal>0:
        gross=quantity*(price-fill)
        result['gross_return']=float(gross/principal)
    amount,base=(gross,principal) if basis=='GROSS' else (pnl,size)
    if amount is None or base is None or base<=0:return result
    result['observation_status']='FRESH'
    # The round trip's costs are paid at the entry, so nothing arms before min_hold.
    if result['status']!='ARMED' or age<min_hold:return result
    if amount*10000>=base*policy['profit_bps']:result['trigger']='AUTO_EXIT_TAKE_PROFIT'
    elif amount*10000<=-base*policy['loss_bps']:result['trigger']='AUTO_EXIT_STOP_LOSS'
    elif inactive(mark,policy,ts,age):result['trigger']='AUTO_EXIT_INACTIVE'
    elif held is not None and held>=max_hold:result['trigger']='AUTO_EXIT_MAX_HOLD'
    return result


def stored_policy(db,bag_id):
    return Store.get(db,'autoexit-policy:'+bag_id)
