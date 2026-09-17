"""EIP-712 messages with exact origin, chain, bag, round and one-use challenge."""
import secrets
from eth_account import Account
from eth_account.messages import encode_typed_data
from .config import address

FIELDS = [('origin','string'),('wallet','address'),('action','string'),('bag_id','string'),('round_id','uint256'),
          ('choice','string'),('content','string'),('nonce','string'),('issued_at','uint256'),('expires_at','uint256'),('chain_id','uint256')]

def typed(config, wallet, action, bag_id, round_id, choice, content, now):
    return {'types': {'EIP712Domain':[{'name':'name','type':'string'},{'name':'version','type':'string'},{'name':'chainId','type':'uint256'}],
                      'BagAction':[{'name':n,'type':t} for n,t in FIELDS]},
            'primaryType':'BagAction','domain':{'name':'THE FLY BAG ROOM TEST HOLDERS' if config.integration else 'THE FLY BAG ROOM','version':'1','chainId':config.chain_id},
            'message':{'origin':config.origin,'wallet':wallet,'action':action,'bag_id':bag_id,'round_id':round_id,
                       'choice':choice,'content':content,'nonce':secrets.token_hex(24),'issued_at':int(now),
                       'expires_at':int(now)+120,'chain_id':config.chain_id}}

def verify(message, signature, rpc=None):
    if not isinstance(signature,str) or len(signature)>2048: raise ValueError('Invalid signature')
    encoded = encode_typed_data(full_message=message)
    recovered = None
    try: recovered = Account.recover_message(encoded,signature=signature)
    except Exception: pass
    wallet=address(message['message']['wallet'])
    if recovered and address(recovered)==wallet:return wallet
    if rpc is not None:
        # ERC-1271: configured node validates a contract wallet's signature; no signing key.
        from eth_utils import keccak
        try:
            if int(rpc.call('eth_chainId',[]),16)!=message['message']['chain_id']:raise ValueError()
            if rpc.call('eth_getCode',[wallet,'latest']) in ('0x','0x0'):raise ValueError()
            hashed=keccak(b'\x19'+encoded.version+encoded.header+encoded.body).hex()
            raw=bytes.fromhex(signature.removeprefix('0x'))
            calldata='0x1626ba7e'+hashed+f'{64:064x}'+f'{len(raw):064x}'+raw.hex().ljust(((len(raw)+31)//32)*64,'0')
            result=rpc.call('eth_call',[{'to':wallet,'data':calldata},'latest'])
            if not result.lower().startswith('0x1626ba7e'):raise ValueError()
            return wallet
        except Exception:pass
    raise ValueError('Invalid wallet signature')
