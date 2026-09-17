"""Public deterministic TEST identities; never transaction signers or production keys."""
import json
from eth_account import Account
from eth_account.messages import encode_typed_data


def accounts():return [Account.from_key(i.to_bytes(32,'big')) for i in (1,2,3)]
def wallets():return [w.address for w in accounts()]


def sign_challenge(room,body):
    if not room.config.integration:raise ValueError('Test signer is disabled')
    nonce=body.get('nonce')
    if not isinstance(nonce,str) or len(nonce)!=48:raise ValueError('Expected existing challenge nonce')
    with room.store.read() as db:
        row=db.execute('SELECT typed,used,expires FROM challenges WHERE nonce=?',(nonce,)).fetchone()
    if not row or row['used'] or room.now()>=row['expires']:raise ValueError('Test challenge unavailable')
    typed=json.loads(row['typed']);m=typed['message']
    if m['origin']!=room.config.origin or m['chain_id']!=4663 or typed['domain']['name']!='THE FLY BAG ROOM TEST HOLDERS':raise ValueError('Test domain mismatch')
    signer=next((w for w in accounts() if w.address.lower()==m['wallet']),None)
    if signer is None:raise ValueError('Unknown TEST wallet')
    return {'signature':'0x'+signer.sign_message(encode_typed_data(full_message=typed)).signature.hex(),'holder_source':'FIXTURE'}
