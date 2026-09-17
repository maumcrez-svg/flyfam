from dataclasses import dataclass, field
import os
import re


def address(value):
    if not isinstance(value, str) or not re.fullmatch(r'0x[0-9a-fA-F]{40}', value):
        raise ValueError('Invalid wallet or token address')
    return value.lower()


@dataclass(frozen=True)
class Config:
    token: str = ''
    deployment_block: int | None = None
    excluded: tuple = ()
    chain_id: int = 4663
    decimals: int | None = None
    origin: str = 'http://localhost:8797'
    round_seconds: int = 30
    fixture: bool = False
    holder_source: str = 'REAL_HOLDERS'
    fixture_holders_file: str = ''
    profit_fraction_bps: int = 10000
    test_autoexit_enabled: bool = False
    autoexit_empty_rounds: int = 2
    autoexit_profit_bps: int = 2000
    autoexit_loss_bps: int = 2000
    autoexit_idle_seconds: int = 600
    autoexit_mark_max_age: int = 90
    autoexit_return_basis: str = 'GROSS'
    autoexit_min_hold_seconds: int = 600
    autoexit_max_hold_seconds: int = 3600

    def __post_init__(self):
        if self.holder_source not in ('REAL_HOLDERS','FIXTURE'):raise ValueError('Invalid holder source')
        if self.integration and self.token:raise ValueError('Test holders must not impersonate a project token')
        if self.test_autoexit_enabled and not self.integration:raise ValueError('Autoexit is authorized only for real PAPER / test holders')
        if not 1<=self.autoexit_empty_rounds<=100:raise ValueError('Invalid autoexit empty-round count')
        if not all(0<v<=10000 for v in (self.autoexit_profit_bps,self.autoexit_loss_bps)):raise ValueError('Invalid autoexit return limits')
        if not 30<=self.autoexit_idle_seconds<=3600 or not 1<=self.autoexit_mark_max_age<=90:raise ValueError('Invalid autoexit observation window')
        if self.autoexit_return_basis not in ('GROSS','NET'):raise ValueError('Invalid autoexit return basis')
        if not 0<=self.autoexit_min_hold_seconds<=86400:raise ValueError('Invalid autoexit minimum hold')
        if not 300<=self.autoexit_max_hold_seconds<=86400 or self.autoexit_max_hold_seconds<=self.autoexit_min_hold_seconds:
            raise ValueError('Invalid autoexit maximum hold')
        if self.token: object.__setattr__(self, 'token', address(self.token))
        object.__setattr__(self, 'excluded', tuple(sorted({address(a) for a in self.excluded})))
        if self.decimals is not None and not 0<=self.decimals<=255:raise ValueError('Invalid project-token decimals')
        if self.chain_id != 4663: raise ValueError('Bag Room is configured for chain 4663')
        if self.deployment_block is not None and self.deployment_block < 0: raise ValueError('Invalid deployment block')
        if not 5<=self.round_seconds<=600: raise ValueError('Round duration must be 5-600 seconds')
        if not 0 <= self.profit_fraction_bps <= 10000: raise ValueError('Invalid vault fraction')
        if not self.origin.startswith(('http://127.0.0.1:', 'http://localhost:', 'https://')) or self.origin.endswith('/'):
            raise ValueError('Use an exact HTTPS origin (loopback HTTP allowed)')

    @property
    def configured(self): return bool(self.fixture_holders_file) if self.integration else bool(self.token and self.deployment_block is not None)

    @property
    def integration(self): return self.holder_source=='FIXTURE' and not self.fixture

    @property
    def sources(self):
        return {'worker':'REAL_PONS_PAPER' if self.integration else None,
                'bag_position_source':'FIXTURE' if self.fixture else 'REAL_WORKER',
                'holder_source':'FIXTURE' if self.fixture or self.integration else 'REAL_HOLDERS'}

    @classmethod
    def environment(cls, **overrides):
        block = os.getenv('PROJECT_TOKEN_DEPLOYMENT_BLOCK', '')
        decimals = os.getenv('PROJECT_TOKEN_DECIMALS', '')
        return cls(holder_source=os.getenv('HOLDER_SOURCE','REAL_HOLDERS'),
                   fixture_holders_file=os.getenv('FIXTURE_HOLDERS_FILE',''),token=os.getenv('PROJECT_TOKEN_ADDRESS', ''),decimals=int(decimals) if decimals else None,
                   deployment_block=int(block) if block else None,
                   excluded=tuple(x.strip() for x in os.getenv('ELIGIBILITY_EXCLUDED_ADDRESSES', '').split(',') if x.strip()),
                   origin=os.getenv('BAG_ROOM_ORIGIN', 'http://localhost:8797'),
                   round_seconds=int(os.getenv('BAG_ROUND_SECONDS','30')),
                   test_autoexit_enabled=os.getenv('BAG_TEST_AUTOEXIT_ENABLED','NO')=='YES',
                   autoexit_empty_rounds=int(os.getenv('BAG_AUTOEXIT_EMPTY_ROUNDS','2')),
                   autoexit_profit_bps=int(os.getenv('BAG_AUTOEXIT_PROFIT_BPS','2000')),
                   autoexit_loss_bps=int(os.getenv('BAG_AUTOEXIT_LOSS_BPS','2000')),
                   autoexit_idle_seconds=int(os.getenv('BAG_AUTOEXIT_IDLE_SECONDS','600')),
                   autoexit_mark_max_age=int(os.getenv('BAG_AUTOEXIT_MARK_MAX_AGE','90')),
                   autoexit_return_basis=os.getenv('BAG_AUTOEXIT_RETURN_BASIS','GROSS'),
                   autoexit_min_hold_seconds=int(os.getenv('BAG_AUTOEXIT_MIN_HOLD_SECONDS','600')),
                   autoexit_max_hold_seconds=int(os.getenv('BAG_AUTOEXIT_MAX_HOLD_SECONDS','3600')),
                   profit_fraction_bps=int(os.getenv('BAG_PROFIT_TO_VAULT_BPS','10000')), **overrides)
