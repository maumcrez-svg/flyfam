"""Verified Pons curve -> V4 paper exits. Read-only, exact input, no signing.

The registered quoter checks that the complete input was consumed. Its output
already includes pool/hook fees. Only the declared paper gas is subtracted again.
Quotes are pinned to a real block; a pending exit survives confirmation/restart.
"""

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import time

from ..pons import abi, paper as PAPER
from ..pons.rpc import RpcError, keccak256_hex
from .history import canonical, RecoveryError
from .live import ProductPaperExecution

VERSION = 'pons-v4-paper-exit-1'
REGISTRY = Path(__file__).resolve().parents[2] / 'product' / 'pons_v4_exit.json'
ZERO = abi.ZERO_ADDRESS
INITIALIZE = keccak256_hex(b'Initialize(bytes32,address,address,uint24,int24,address,uint160,int24)')
FACTORY_TOPICS = {e.name: e.topic0 for e in abi.V2_FACTORY_EVENTS}


def word(value):
    return int(value).to_bytes(32, 'big', signed=int(value) < 0)


def selector(signature):
    return keccak256_hex(signature.encode())[:10]


def words(raw, count):
    try:
        data = bytes.fromhex(raw[2:]) if isinstance(raw, str) and raw.startswith('0x') else b''
    except ValueError:
        data = b''
    if len(data) != 32 * count:
        raise PAPER.Unresolved('V4_INVALID_RESPONSE', 'Unexpected ABI result shape')
    return [data[i:i + 32] for i in range(0, len(data), 32)]


def address_word(raw):
    return abi._decode_word('address', raw)


def pool_key(log):
    if log.get('topics', [None])[0] != INITIALIZE or len(log['topics']) != 4:
        raise PAPER.Unresolved('V4_INVALID_INITIALIZE')
    values = words(log['data'], 5)
    key = {'currency0': address_word(words(log['topics'][2], 1)[0]),
           'currency1': address_word(words(log['topics'][3], 1)[0]),
           'fee': abi._decode_word('uint24', values[0]),
           'tickSpacing': abi._decode_word('int24', values[1]),
           'hooks': address_word(values[2])}
    if not (int(key['currency0'], 16) < int(key['currency1'], 16)
            and 0 < key['tickSpacing'] <= 32767
            and (key['fee'] <= 1_000_000 or key['fee'] == 0x800000)):
        raise PAPER.Unresolved('V4_INVALID_POOL_KEY')
    if pool_id(key) != log['topics'][1].lower():
        raise PAPER.Unresolved('V4_POOL_ID_MISMATCH')
    return key


def key_bytes(key):
    return b''.join(word(v) for v in (int(key['currency0'], 16),
        int(key['currency1'], 16), key['fee'], key['tickSpacing'], int(key['hooks'], 16)))


def pool_id(key):
    return keccak256_hex(key_bytes(key))


def quote_calldata(key, token, amount):
    if token not in (key['currency0'], key['currency1']) or not 0 < int(amount) < 2**127:
        raise PAPER.Unresolved('V4_INVALID_INPUT_AMOUNT_OR_TOKEN')
    data = word(32) + key_bytes(key) + word(token == key['currency0']) + word(amount) + word(256) + word(0)
    return selector('quoteExactInputSingle(((address,address,uint24,int24,address),bool,uint128,bytes))') + data.hex()


def resolve_proof(launch, graduation, initializes, *, token, curve, registry):
    for event in (launch, graduation):
        if event.get('removed') or event['address'].lower() != registry['factory']['address']:
            raise PAPER.Unresolved('V4_FACTORY_PROVENANCE_MISMATCH')
    a, b = (abi.decode_log(e, abi.V2_FACTORY_BY_TOPIC) for e in (launch, graduation))
    if (a.get('error') or b.get('error') or a['event'] != 'TokenLaunched'
            or b['event'] != 'PoolGraduated' or a['args']['token'] != token
            or b['args']['token'] != token or a['args']['curve'] != curve
            or a['args']['pairToken'] != ZERO):
        raise PAPER.Unresolved('V4_FACTORY_PROVENANCE_MISMATCH')
    order = lambda e: (int(e['blockNumber'], 16), int(e['logIndex'], 16))
    if order(launch) >= order(graduation):
        raise PAPER.Unresolved('V4_LAUNCH_ORDER_MISMATCH')
    matches = []
    for event in initializes:
        if event.get('removed') or event['address'].lower() != registry['manager']['address']:
            continue
        if any(event.get(k) != graduation.get(k) for k in
               ('transactionHash', 'transactionIndex', 'blockHash', 'blockNumber')):
            continue
        key = pool_key(event)
        if (key['currency0'], key['currency1']) != (ZERO, token):
            continue
        if key['hooks'] != registry['hook']['address'] or order(event) >= order(graduation):
            raise PAPER.Unresolved('V4_HOOK_OR_INITIALIZE_ORDER_MISMATCH')
        matches.append((event, key))
    if len(matches) != 1:
        raise PAPER.Unresolved('V4_INITIALIZE_MISSING_OR_AMBIGUOUS')
    event, key = matches[0]
    return {'version': VERSION, 'token': token, 'curve': curve,
            'pool_manager': registry['manager']['address'], 'pool_id': pool_id(key),
            'pool_key': key, 'launch': launch, 'graduation': graduation, 'initialize': event}


@dataclass(frozen=True)
class V4FillPlan:
    evidence: dict
    quantity: float
    gas_wei: int
    requested_ts: int

    @property
    def block_number(self): return self.evidence['block_number']
    @property
    def block_timestamp(self): return self.evidence['block_timestamp']
    @property
    def reference_price(self): return self.evidence['reference_price']
    @property
    def fill_price(self): return int(self.evidence['amount_out_wei']) / PAPER.WEI / self.quantity
    @property
    def fee(self): return self.gas_wei / PAPER.WEI
    @property
    def delay_s(self): return self.block_timestamp - self.requested_ts


class V4ExitRouter:
    """One-position bounded cache, permanent quote/provenance evidence in SQLite."""

    def __init__(self, rpc, history, store, *, registry=None, now=None):
        self.rpc, self.history, self.store = rpc, history, store
        self.registry = registry or json.loads(REGISTRY.read_text())
        self.now = now or time.time
        self.verified = False
        self.proof = None
        self.last_quote = None

    def _call(self, method, params, reads):
        # Use the non-retrying client: an EVM revert or missing state must not
        # trap the continuous collector in its transient-network retry loop.
        value = self.rpc.call(method, params)
        reads.append({'method': method, 'params': params, 'result': value})
        return value

    def _header(self, tag, reads):
        h = self._call('eth_getBlockByNumber', [hex(tag) if isinstance(tag, int) else tag, False], reads)
        if not h or not h.get('hash') or not h.get('number') or not h.get('timestamp'):
            raise PAPER.Unresolved('V4_BLOCK_UNAVAILABLE')
        return h

    def _verify(self, header, reads):
        if self.verified:
            return
        if int(self._call('eth_chainId', [], reads), 16) != 4663:
            raise PAPER.Unresolved('V4_WRONG_CHAIN')
        for name in ('factory', 'manager', 'hook', 'quoter'):
            item = self.registry[name]
            code = self._call('eth_getCode', [item['address'], header['number']], reads)
            if keccak256_hex(bytes.fromhex(code[2:])) != item['runtime_keccak256']:
                raise PAPER.Unresolved('V4_DEPLOYMENT_CODE_MISMATCH', name)
        for name in ('factory', 'quoter'):
            raw = self._call('eth_call', [{'to': self.registry[name]['address'],
                'data': selector('poolManager()')}, header['number']], reads)
            if address_word(words(raw, 1)[0]) != self.registry['manager']['address']:
                raise PAPER.Unresolved('V4_MANAGER_MISMATCH')
        self.verified = True

    def _logs(self, address, start, end, topics, reads):
        value = self._call('eth_getLogs', [{'address': address, 'fromBlock': hex(start),
            'toBlock': hex(end), 'topics': topics}], reads)
        if not isinstance(value, list) or len(value) > 100:
            raise PAPER.Unresolved('V4_LOG_RESPONSE_UNBOUNDED')
        return value

    def _resolve(self, tape, header, reads):
        if self.proof and self.proof['token'] == tape.token and self.proof['curve'] == tape.curve:
            return self.proof
        saved = self.history.state('v4-route')
        if saved and saved['value']['token'] == tape.token and saved['value']['curve'] == tape.curve:
            p = saved['value']
            self.proof = resolve_proof(p['launch'], p['graduation'], [p['initialize']],
                token=tape.token, curve=tape.curve, registry=self.registry)
            return self.proof
        factory = self.registry['factory']['address']; topic_token = '0x' + tape.token[2:].zfill(64)
        launches = self._logs(factory, tape.launch_block, tape.launch_block,
            [FACTORY_TOPICS['TokenLaunched'], topic_token], reads)
        if len(launches) != 1:
            raise PAPER.Unresolved('V4_LAUNCH_MISSING_OR_AMBIGUOUS')
        scan = self.history.state('v4-discovery')
        scan = scan['value'] if scan else {}
        start = int(scan.get('next_block', tape.launch_block)) if scan.get('token') == tape.token else tape.launch_block
        tip = int(header['number'], 16)
        graduations = []
        for _ in range(4):
            if start > tip: break
            end = min(start + 49_999, tip)
            graduations += self._logs(factory, start, end,
                [FACTORY_TOPICS['PoolGraduated'], topic_token], reads)
            if graduations: break
            start = end + 1
        if not graduations:
            # Overlap the finality window on the next scan. Even at the tip a
            # missing graduation remains retryable; no unavailable price is 0.
            self.history.save_state('v4-discovery', {'token': tape.token,
                'next_block': max(tape.launch_block, start - 1200)})
            raise PAPER.Unresolved('V4_ROUTE_PENDING', 'No verified graduation in the scanned range')
        if len(graduations) != 1:
            raise PAPER.Unresolved('V4_GRADUATION_AMBIGUOUS')
        graduation = graduations[0]; block = int(graduation['blockNumber'], 16)
        initializes = self._logs(self.registry['manager']['address'], block, block,
            [INITIALIZE, None, '0x' + ZERO[2:].zfill(64), topic_token], reads)
        proof = resolve_proof(launches[0], graduation, initializes, token=tape.token,
            curve=tape.curve, registry=self.registry)
        self.history.append('v4-route:' + tape.token + ':' + graduation['blockHash'],
            {'kind': 'V4_ROUTE', 'ts': int(self.now()), 'proof': proof, 'reads': reads.copy()})
        self.history.save_state('v4-route', proof)
        self.proof = proof
        return proof

    def _validate_proof(self, proof, reads):
        for name in ('launch', 'graduation'):
            event = proof[name]
            h = self._header(int(event['blockNumber'], 16), reads)
            if h['hash'].lower() != event['blockHash'].lower():
                self.proof = None
                self.history.save_state('v4-route', {'token': '', 'curve': ''})
                self.history.save_state('v4-discovery', {'token': ''})
                raise PAPER.Unresolved('V4_PROVENANCE_REORG')

    def validate_quote(self, quote, *, token, amount, minimum_ts):
        if (quote.get('version') != VERSION or quote.get('token') != token
                or int(quote.get('amount_in_wei', 0)) != int(amount)
                or quote.get('block_timestamp', 0) < int(minimum_ts)):
            raise RecoveryError('Pending V4 quote is incompatible with its paper position')
        expected = 'v4-quote:' + sha256(canonical({k:v for k,v in quote.items() if k != 'evidence_id'})).hexdigest()
        if quote.get('evidence_id') != expected or quote.get('registry_digest') != sha256(canonical(self.registry)).hexdigest():
            raise RecoveryError('Pending V4 quote evidence checksum/configuration mismatch')
        proof = quote['proof']; reads = []
        resolve_proof(proof['launch'], proof['graduation'], [proof['initialize']],
            token=token, curve=quote['curve'], registry=self.registry)
        self._validate_proof(proof, reads)
        h = self._header(quote['block_number'], reads)
        if h['hash'].lower() != quote['block_hash'].lower():
            raise PAPER.Unresolved('V4_QUOTE_REORG')
        return True

    def quote(self, tape, amount, *, minimum_ts):
        reads = []
        try:
            head = self._header('latest', reads)
            stamp, block = int(head['timestamp'], 16), int(head['number'], 16)
            if stamp < int(minimum_ts) or not -5 <= self.now() - stamp <= 90:
                raise PAPER.Unresolved('V4_STALE_MARKET')
            self._verify(head, reads)
            proof = self._resolve(tape, head, reads)
            self._validate_proof(proof, reads)
            if int(proof['graduation']['blockNumber'], 16) > block:
                raise PAPER.Unresolved('V4_ROUTE_PENDING')
            key = proof['pool_key']
            data = quote_calldata(key, tape.token, amount)
            raw = self._call('eth_call', [{'to': self.registry['quoter']['address'],
                'data': data}, head['number']], reads)
            output, gas = (int.from_bytes(w, 'big') for w in words(raw, 2))
            if output <= 0 or output >= 2**127 or gas <= 0:
                raise PAPER.Unresolved('V4_NO_EXECUTABLE_LIQUIDITY')
            slot = keccak256_hex(bytes.fromhex(proof['pool_id'][2:]) + word(6))
            raw_slot = self._call('eth_call', [{'to': proof['pool_manager'],
                'data': selector('extsload(bytes32)') + slot[2:]}, head['number']], reads)
            sqrt = int.from_bytes(words(raw_slot, 1)[0], 'big') & (2**160 - 1)
            if sqrt == 0:
                raise PAPER.Unresolved('V4_POOL_UNINITIALIZED')
            reference = (2**192) / (sqrt * sqrt) # native ETH is currency0; token is currency1
            after = self._header(block, reads)
            if after['hash'].lower() != head['hash'].lower():
                raise PAPER.Unresolved('V4_QUOTE_REORG')
            result = {'version': VERSION, 'route': 'PONS_V4', 'token': tape.token,
                'curve': tape.curve, 'pool_id': proof['pool_id'], 'pool_key': key,
                'block_number': block, 'block_hash': head['hash'].lower(),
                'block_timestamp': stamp, 'observed_at': int(self.now()),
                'minimum_ts': int(minimum_ts), 'amount_in_wei': str(amount),
                'registry_digest': sha256(canonical(self.registry)).hexdigest(),
                'amount_out_wei': str(output), 'quoter_gas_estimate': gas,
                'sqrt_price_x96': str(sqrt), 'reference_price': reference,
                'swap_and_hook_fees': 'INCLUDED_IN_OUTPUT_NOT_SEPARATELY_DECOMPOSED',
                'full_input_consumed': True, 'own_curve_delta_carried_to_v4': False,
                'proof': proof, 'quoter': self.registry['quoter'], 'reads': reads}
            result['evidence_id'] = 'v4-quote:' + sha256(canonical(result)).hexdigest()
            self.history.append(result['evidence_id'], {'kind': 'V4_EXIT_QUOTE',
                'ts': stamp, 'quote': result})
            self.store.record_headers([head])
            self.last_quote = result
            return result
        except (RpcError, PAPER.Unresolved, abi.AbiError, ValueError) as exc:
            reason = exc.reason if isinstance(exc, PAPER.Unresolved) else 'V4_QUOTE_UNAVAILABLE'
            self.history.append('v4-failure:' + sha256(canonical({'reads': reads,
                'reason': reason, 'at': int(self.now()), 'token': tape.token})).hexdigest(),
                {'kind': 'V4_QUOTE_UNAVAILABLE', 'ts': int(self.now()),
                 'token': tape.token, 'reason': reason,
                 'rpc_code': getattr(exc, 'code', None), 'reads': reads})
            raise PAPER.Unresolved(reason, 'V4 exit not quoted; position retained') from None


class V4PaperExecution(ProductPaperExecution):
    version = VERSION

    def __init__(self, *, v4_router, **kw):
        super().__init__(**kw)
        self.v4 = v4_router
        self.last_exit_evidence = None

    def _plan(self, quote, quantity, when):
        return V4FillPlan(quote, quantity, self.gas_sell_wei + self.gas_approval_wei, int(when))

    def plan_sell(self, tape, when, tokens, clock, *, tokens_wei=None):
        try:
            return super().plan_sell(tape, when, tokens, clock, tokens_wei=tokens_wei)
        except PAPER.Unresolved as exc:
            if exc.reason != PAPER.ROUTE_TRANSITION: raise
        if tokens_wei is None:
            raise PAPER.Unresolved('V4_EXACT_INVENTORY_REQUIRED')
        return self._plan(self.v4.quote(tape, tokens_wei, minimum_ts=when), tokens, when)

    def plan_horizon_exit(self, tape, cutoff, clock):
        position = self.account.position
        try:
            # Preserve the registered curve exit rule byte-for-byte.
            return super().plan_sell(tape, self.horizon_ts, position.quantity, clock,
                tokens_wei=self.entry_tokens_wei)
        except PAPER.Unresolved as exc:
            if exc.reason != PAPER.ROUTE_TRANSITION: raise
        if self.entry_tokens_wei is None:
            raise PAPER.Unresolved('V4_EXACT_INVENTORY_REQUIRED')
        saved = self.v4.history.state('v4-pending-exit')
        pending = saved['value'] if saved else {}
        if pending.get('episode_id') == position.episode_id:
            quote = pending['quote']
            if pending['horizon_ts'] != self.horizon_ts:
                raise RecoveryError('Pending V4 exit horizon changed')
            try:
                self.v4.validate_quote(quote, token=tape.token,
                    amount=self.entry_tokens_wei, minimum_ts=self.horizon_ts)
            except RpcError:
                raise PAPER.Unresolved('V4_CONFIRMATION_UNAVAILABLE', 'Pending quote retained for retry') from None
            except PAPER.Unresolved as exc:
                if exc.reason in ('V4_QUOTE_REORG', 'V4_PROVENANCE_REORG'):
                    self.v4.history.append('v4-invalidated:' + quote['evidence_id'],
                        {'kind': 'V4_EXIT_INVALIDATED', 'ts': int(self.v4.now()),
                         'quote_evidence_id': quote['evidence_id'], 'reason': exc.reason})
                    self.v4.history.save_state('v4-pending-exit', {})
                raise PAPER.Unresolved(exc.reason, 'No settlement; position retained') from None
        else:
            quote = self.v4.quote(tape, self.entry_tokens_wei,
                minimum_ts=max(self.horizon_ts, int(cutoff)))
            self.v4.history.save_state('v4-pending-exit', {'episode_id': position.episode_id,
                'horizon_ts': self.horizon_ts, 'quote': quote})
        return self._plan(quote, position.quantity, self.horizon_ts)

    def mark(self, tape, cutoff, clock):
        result = super().mark(tape, cutoff, clock)
        if result.get('available') and self.v4.last_quote:
            quote = self.v4.last_quote
            if quote['token'] == tape.token and quote['block_number'] == result.get('block_number'):
                result.update(route='PONS_V4', quote_ts=quote['block_timestamp'],
                    quote_evidence_id=quote['evidence_id'], pool_id=quote['pool_id'],
                    swap_and_hook_fees=quote['swap_and_hook_fees'])
        self.last_mark = dict(result)
        return result

    def close(self, *, tape, reason, cutoff, clock):
        if self.account.position is None:
            return super().close(tape=tape, reason=reason, cutoff=cutoff, clock=clock)
        plan = self.plan_horizon_exit(tape, cutoff, clock)
        self.last_exit_evidence = None
        if isinstance(plan, V4FillPlan):
            summary = {k: plan.evidence[k] for k in ('version', 'route', 'token', 'curve',
                'pool_id', 'pool_key', 'block_number', 'block_hash', 'block_timestamp',
                'amount_in_wei', 'amount_out_wei', 'evidence_id', 'reference_price',
                'swap_and_hook_fees', 'full_input_consumed', 'own_curve_delta_carried_to_v4')}
            self.last_exit_evidence = {**summary, 'requested_exit_ts': self.horizon_ts,
                'execution_delay_s': plan.delay_s, 'modeled_gas_wei': str(plan.gas_wei),
                'timing_rule': 'FIRST_OBSERVED_EXECUTABLE_QUOTE_AFTER_HORIZON',
                'cost_classification': 'V4_SWAP_FEES_EMBEDDED_IN_EXECUTION_DRAG'}
        return super().close(tape=tape, reason=reason, cutoff=cutoff, clock=clock)

    def as_dict(self):
        out = super().as_dict()
        out['post_curve_exit'] = VERSION
        return out
