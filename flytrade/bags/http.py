"""Same-origin signed actions. No endpoint can execute a trade or finalize a round."""
import json
from urllib.parse import parse_qs
from .store import Store
from .payout import ClaimExpired


def handle(handler, path, query='', *, post=False):
    room=getattr(handler.server,'bag_room',None)
    if not (path.startswith(('/api/bags','/api/test-holders','/api/claims')) or path=='/api/vault/summary'):return False
    if path.startswith('/api/test-holders') and (not room or not room.config.integration):
        handler._json(404,{'error':'Test-holder controls are disabled'});return True
    if not room:
        handler._json(200 if not post else 503,{'configured':False,'bag':None,'error':'Bag Room is not configured'})
        return True
    try:
        q=parse_qs(query)
        if any(len(v)!=1 for v in q.values()):raise ValueError('Repeated query parameter')
        def integer(key,default=0):
            n=int(q.get(key,[default])[0])
            if not 0<=n<2**63:raise ValueError('Invalid cursor')
            return n
        if post:
            if handler.command!='POST':handler._json(405,{'error':'Unsupported method'});return True
            if handler.headers.get('Origin')!=room.config.origin:
                handler._json(403,{'error':'Origin is not authorized'});return True
            if handler.headers.get('Content-Type','').split(';')[0]!='application/json':raise ValueError('JSON body required')
            size=int(handler.headers.get('Content-Length','0'))
            if not 0<size<=8192:raise ValueError('Invalid request size')
            handler.connection.settimeout(5)
            with room.store.transaction() as db:Store.rate(db,'http:'+handler.client_address[0],room.now(),120)
            body=json.loads(handler.rfile.read(size))
            if not isinstance(body,dict):raise ValueError('Expected object')
            if path.startswith('/api/claims/'):
                bag_id=path.removeprefix('/api/claims/')
                if '/' in bag_id or not bag_id or len(bag_id)>80:raise ValueError('Invalid claim bag')
                if 'nonce' not in body:
                    result={'typed_data':room.challenge({'wallet':body.get('wallet'),'action':'CLAIM','bag_id':bag_id},handler.client_address[0])}
                else:
                    with room.store.read() as db:r=db.execute('SELECT typed FROM challenges WHERE nonce=?',(body.get('nonce'),)).fetchone()
                    if not r:raise ValueError('Unknown claim nonce')
                    m=json.loads(r[0])['message']
                    if m['action']!='CLAIM' or m['bag_id']!=bag_id:raise ValueError('Claim signature belongs to another action/bag')
                    result=room.submit(body.get('nonce'),body.get('signature'),handler.client_address[0])
            elif path=='/api/test-holders/sign':
                from .test_holders import sign_challenge
                result=sign_challenge(room,body)
            elif path=='/api/bags/challenge':result=room.challenge(body,handler.client_address[0])
            elif path=='/api/bags/action':result=room.submit(body.get('nonce'),body.get('signature'),handler.client_address[0])
            else:handler._json(404,{'error':'Unknown signed action'});return True
        elif path=='/api/test-holders/wallets':
            from .test_holders import wallets
            result={'holder_source':'FIXTURE','wallets':wallets(),'worker':'REAL_PONS_PAPER'}
        elif path=='/api/bags/bridge':
            with room.store.read() as db:result={'enabled':room.config.configured,**room.config.sources,'proof':Store.get(db,'phase_a_bridge_proof')}
        elif path=='/api/bags':
            result=room.view(q.get('id',[None])[0],q.get('wallet',[None])[0],after=integer('after'),before=integer('before',2**63-1))
        elif path=='/api/vault/summary':
            from .payout_views import summary
            result=summary(room)
        elif path.startswith('/api/claims/'):
            from .claims import claims
            parts=path.removeprefix('/api/claims/').split('/')
            if len(parts)==1:result=claims(room,parts[0],before=integer('before',2**63-1))
            elif len(parts)==2:result=claims(room,parts[1],bag_id=parts[0])
            else:raise ValueError('Invalid claims route')
        elif path=='/api/bags/claims':
            from .claims import claims
            result=claims(room,q.get('wallet',[''])[0],bag_id=q.get('id',[None])[0],before=integer('before',2**63-1))
        elif path=='/api/bags/money':
            with room.store.read() as db:result=Store.get(db,'live_bankroll',{'execution':'PAPER','available':False})
        elif path=='/api/bags/proof':result=room.proof(q.get('id',[''])[0],q.get('wallet',[''])[0])
        elif path=='/api/bags/audit':result=room.audit(q.get('id',[''])[0],integer('after'))
        else:handler._json(404,{'error':'Unknown Bag Room endpoint'});return True
        handler._json(200,result)
    except ClaimExpired:
        handler._json(409,{'status':'EXPIRED','error':'Claim window expired'})
    except (ValueError,TypeError,KeyError):
        handler._json(400,{'error':'Action rejected: check eligibility, signature, round, expiry and rate limit.'})
    except (BrokenPipeError,ConnectionResetError):pass
    except Exception:
        handler._json(503,{'error':'Bag Room temporarily unavailable'})
    return True
