"""Public wallet-connection configuration. Never exposes trading RPC or signer env."""
import os
import re

CONNECT_ORIGINS=(
 'https://relay.walletconnect.com','wss://relay.walletconnect.com',
 'https://relay.walletconnect.org','wss://relay.walletconnect.org',
 'https://rpc.walletconnect.org','https://verify.walletconnect.com',
 'https://verify.walletconnect.org','https://pulse.walletconnect.org',
 'https://rpc.mainnet.chain.robinhood.com',
)

def public_config(*,test_holders=False):
    project=os.getenv('WALLETCONNECT_PROJECT_ID','').strip()
    enabled=not test_holders and bool(re.fullmatch(r'[a-fA-F0-9]{32}',project))
    return {'chain_id':4663,'walletconnect_enabled':enabled,
            'walletconnect_project_id':project if enabled else None,
            'wallet_rpc':'https://rpc.mainnet.chain.robinhood.com',
            'explorer':'https://robinhoodchain.blockscout.com'}
