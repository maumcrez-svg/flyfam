"""Version 2 spectator evidence from completed canonical neural rounds.

No sampling, ranking model or trading calls. Scores are the runner's actual
selection scores, with its stable-ID tie break. No intra-round motion is inferred.
"""
import hashlib
import math
from .history import canonical

VERSION = 2


def number(value):
    return None if value is None or not math.isfinite(float(value)) else float(value)


def context_view(source):
    """Represent missing numeric telemetry as null, without mutating neural inputs."""
    unavailable=[]
    def clean(value,path):
        if isinstance(value,float) and not math.isfinite(value):
            unavailable.append(path)
            return None
        if isinstance(value,dict):
            return {key:clean(item,f'{path}.{key}' if path else str(key)) for key,item in value.items()}
        if isinstance(value,(list,tuple)):
            return [clean(item,f'{path}[{index}]') for index,item in enumerate(value)]
        return value
    result=clean(source,'')
    if unavailable:
        result['unavailable_numeric_fields']=sorted(unavailable)
    return result


def filtered_status(reasons):
    names = '|'.join(str(reason) for reason in reasons)
    if 'INACTIVE' in names or 'ACTIVITY' in names:
        return 'FILTERED_ACTIVITY'
    if 'HISTORY' in names or 'INSUFFICIENT_TAPE' in names or 'AGE' in names:
        return 'FILTERED_HISTORY'
    if 'ROUTE' in names or 'QUOTE_UNSUPPORTED' in names or 'COMPLETED' in names:
        return 'FILTERED_ROUTE'
    return 'FILTERED_DATA'


def round_identity(run_id, tick, cutoff):
    return f'{run_id}:{int(tick)}:{int(cutoff)}'


def admission_event(loop, considered, planned, cutoff, tick):
    round_id = round_identity(loop.run_id,tick,cutoff)
    planned_ids = {candidate.stable_id for candidate in planned}
    candidates = []
    for candidate in considered:
        context = candidate.context
        candidates.append({'chain_id':4663,'token':candidate.token,'curve':candidate.curve,
            'display_name':None,'display_symbol':None,
            'stable_id':candidate.stable_id,'round_id':round_id,
            'candidate_presentation_id':f'{round_id}:{candidate.stable_id}',
            'observation_ts':int(cutoff),'age_s':context.age_s,
            'launch_block':context.launch_block,'launch_ts':context.launched_at,
            'eligibility_status':'ADMITTED' if candidate.admitted else filtered_status(candidate.reasons),
            'reasons':list(candidate.reasons),'planned_for_measurement':candidate.stable_id in planned_ids,
            'neural_presented':False,'context':context_view(context.as_dict(loop.encoder.features))})
    return {'spectacle_feed_version':VERSION,'kind':'SNIFF_ROUND','ts':int(cutoff),
            'run_id':loop.run_id,'round_id':round_id,'tick':int(tick),
            'candidates':candidates,'considered':len(considered),
            'admitted':sum(c.admitted for c in considered),'planned':len(planned),
            'measurement_state':'AWAITING_RESULT' if planned else 'NO_ELIGIBLE_CANDIDATES'}


def round_event(loop, rnd, extra=None):
    round_id = round_identity(loop.run_id,rnd.round_index,rnd.cutoff_ts)
    definition = {'unit':'Hz','quantity':'baseline-centered approach minus avoidance firing rate',
                  'policy':loop.policy.as_dict(),'brain_digest':rnd.state_digest}
    definition_id = hashlib.sha256(canonical(definition)).hexdigest()
    ranks = {stable_id:rank for rank,(stable_id,_) in enumerate(
        sorted(rnd.scores.items(),key=lambda row:(-row[1],row[0])),1)}
    contexts = {row.get('token',row.get('symbol')):row for row in (extra or {}).get('context',[])}
    rows=[]
    for candidate in rnd.candidates:
        presented = candidate.presentation is not None
        # This fixed readout decoder is pure; this reads the existing aggregate.
        # It does not call the brain or the loop's execution decision handler.
        decision = loop.policy.decoder.decode(candidate.presentation) if presented else None
        valid = decision is not None and decision.status.value=='VALID'
        selected = rnd.selected is not None and rnd.selected.stable_id==candidate.stable_id
        context = context_view(contexts.get(candidate.symbol,{}))
        tape = loop.tapes.get(candidate.symbol)
        if not presented:
            status='ADMITTED'
        elif not valid:
            status='NEURAL_NO_RESPONSE'
        elif decision.action.value=='WAIT':
            status='NEURAL_WAIT'
        elif selected:
            status='SELECTED'
        else:
            status='NEURAL_REJECTED'
        rows.append({'chain_id':4663,'token':candidate.symbol,
            'curve':context.get('curve') or (tape.curve if tape else None),
            'display_name':None,'display_symbol':None,
            'stable_id':candidate.stable_id,'round_id':round_id,
            'candidate_presentation_id':f'{round_id}:{candidate.stable_id}',
            'episode_id':candidate.episode_id,'observation_ts':rnd.cutoff_ts,
            'age_s':context.get('age_s'),'launch_block':context.get('launch_block'),
            'launch_ts':context.get('launched_at'),'context':context,
            'eligibility_status':'ADMITTED','status':status,
            'neural_presented':presented,'raw_score':number(rnd.scores.get(candidate.stable_id)),
            'raw_readout':number(decision.valence_hz) if decision else None,
            'unit':'Hz','score_definition_id':definition_id,
            'decoder_status':decision.status.value if decision else 'NOT_PRESENTED',
            'decoder_action':decision.action.value if decision else None,
            'buy_threshold':number(decision.theta_hz) if decision else None,
            'crossed_buy_threshold':bool(valid and decision.valence_hz>decision.theta_hz),
            'rank':ranks.get(candidate.stable_id),'selected':selected,
            'k':candidate.k,'approach_hz':number(decision.approach_hz) if decision else None,
            'avoid_hz':number(decision.avoid_hz) if decision else None,
            'population_readout':candidate.presentation.as_dict() if presented else None})
    rows.sort(key=lambda row:(row['rank'] is None,row['rank'] or 0,row['stable_id']))
    return {'spectacle_feed_version':VERSION,'kind':'WATCHLIST','ts':int(rnd.cutoff_ts),
        'run_id':loop.run_id,'round_id':round_id,'tick':rnd.round_index,
        'context':'HELD' if loop.holding_tick else 'FLAT',
        'score_definition':definition,'score_definition_id':definition_id,
        'selection_rule':rnd.selection_rule,'candidates':rows,
        'measurement_state':'COMPLETE','measurement_progression':'FINAL_AGGREGATE_ONLY'}


def overtake(previous, current):
    if not previous or previous.get('context')!='FLAT' or current.get('context')!='FLAT':
        return None
    if (previous['score_definition_id']!=current['score_definition_id']
            or previous['round_id']==current['round_id'] or previous['ts']>=current['ts']):
        return None
    def comparable(event):
        return {row['token']:row for row in event['candidates']
                if row['neural_presented'] and row['raw_score'] is not None and row['rank'] is not None}
    old,new=comparable(previous),comparable(current)
    if not old or not new:
        return None
    before=min(old,key=lambda token:old[token]['rank'])
    after=min(new,key=lambda token:new[token]['rank'])
    if before==after or before not in new or after not in old:
        return None
    if not (old[before]['raw_score']>old[after]['raw_score']
            and new[after]['raw_score']>new[before]['raw_score']):
        return None
    return {'spectacle_feed_version':VERSION,'kind':'OVERTAKE','ts':current['ts'],
        'run_id':current['run_id'],'round_id':current['round_id'],
        'previous_round_id':previous['round_id'],'token':after,'overtaken_token':before,
        'score_definition_id':current['score_definition_id'],
        'previous_scores':{token:old[token]['raw_score'] for token in (before,after)},
        'current_scores':{token:new[token]['raw_score'] for token in (before,after)},'unit':'Hz'}


def publish_round(history, event):
    previous=history.state('watchlist')
    previous=None if previous is None else previous['value']
    history.append('watchlist:'+event['round_id'],event)
    crossing=overtake(previous,event)
    if crossing:
        history.append('overtake:'+event['round_id'],crossing)
    if event['context']=='FLAT':
        history.save_state('watchlist',event)
    return event


def legacy_round_event(event):
    """Use recorded P1 scores; never manufacture missing population telemetry."""
    if not event.get('readout') or event.get('round_index') is None:
        return None
    run_id=event.get('run_id','pons-live')
    round_id=round_identity(run_id,event['round_index'],event['cutoff_ts'])
    contexts={row.get('token'):row for row in event.get('context',[])}
    scores={int(k):float(v) for k,v in event.get('scores',{}).items()}
    ordered=sorted(scores,key=lambda key:(-scores[key],key))
    selected=event.get('selected_stable_id')
    rows=[]
    for candidate in event['candidates']:
        stable_id=candidate['stable_id']; context=contexts.get(candidate['symbol'],{})
        value=scores.get(stable_id)
        ambiguous=value is not None and any(other!=stable_id and abs(scores[other]-value)<=1e-6 for other in scores)
        rank=(1 if stable_id==selected else None if ambiguous or value is None else ordered.index(stable_id)+1)
        rows.append({'chain_id':event.get('chain_id',4663),'token':candidate['symbol'],
            'curve':context.get('curve'),'stable_id':stable_id,'episode_id':candidate['episode_id'],
            'round_id':round_id,'candidate_presentation_id':f'{round_id}:{stable_id}',
            'observation_ts':event['cutoff_ts'],'context':context,'unit':'Hz',
            'raw_score':value,'raw_readout':None,'recorded_decimal_places':6,
            'rank':rank,'rank_ambiguous_from_recorded_precision':ambiguous and stable_id!=selected,
            'selected':stable_id==selected,'neural_presented':candidate.get('status')=='OK',
            'status':'SELECTED' if stable_id==selected else 'PRESENTED',
            'decoder_status':'UNRECORDED','decoder_action':None,'population_readout':None,
            'k':candidate.get('k'),'legacy':True})
    rows.sort(key=lambda row:(not row['selected'],row['rank'] is None,row['rank'] or 0,row['stable_id']))
    definition={'unit':'Hz','quantity':'baseline-centered approach minus avoidance firing rate',
                'policy':event['readout'],'brain_digest':event.get('state_digest')}
    return {'spectacle_feed_version':2,'kind':'WATCHLIST','ts':event['cutoff_ts'],
        'run_id':run_id,'round_id':round_id,'tick':event['round_index'],
        'context':'HELD' if event.get('mark') else 'FLAT','candidates':rows,
        'score_definition':definition,'score_definition_id':hashlib.sha256(canonical(definition)).hexdigest(),
        'selection_rule':event.get('selection_rule'),'measurement_state':'COMPLETE',
        'measurement_progression':'FINAL_AGGREGATE_ONLY','legacy':True,
        'missing_evidence':['unrounded scores','per-candidate population readouts','per-candidate decoder status']}
