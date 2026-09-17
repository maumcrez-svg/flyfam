"""The product stack over a **scripted endpoint**. Every chain number invented.

``tests.d10.scripted`` is the fake node (see its docstring); this builds the
real product worker on top of it — the real ``brains/trader-v1`` checkpoint,
the real journal, credit assigner, admission_v2, context_v2, encoder_v2,
readout, paper execution, curve quotes, feed and state file — and drives it on
a fake wall clock so a sixty-tick run takes seconds.

**No number produced here is an observation of Robinhood Chain or of PONS.**
The chain runs at one block a second, its logs are constructed, and the
*decoder* is scripted in the tests that need a position: the loop's mechanics
must be testable without the brain's answer deciding whether the test runs at
all. Everything else is the object the product runs.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import replace
from pathlib import Path

from flytrade import decoder as D
from flytrade import readout as RO
from flytrade.pons.seed import LAUNCH_SEED
from tests.d10 import scripted as S

ROOT = Path(__file__).resolve().parents[2]
URL = "https://nd-1-2-3.p2pify.com/deadbeefdeadbeefdeadbeefdeadbeef"


def _run_module():
    """``product/run.py``, imported by path: it is a script, not a package."""
    name = "product_run"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, ROOT / "product" / "run.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


RUN = _run_module()


class Clock:
    """A fake wall clock the driver's sleeps advance. Invented, like the chain."""

    def __init__(self, t0: float = 1_800_000_000.0):
        self.t = float(t0)
        self.slept = 0.0

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        seconds = max(0.0, float(seconds))
        self.t += seconds
        self.slept += seconds


def pinned_launch(block: int, *, token=S.TOKEN, curve=S.CURVE) -> dict:
    return S.make_log(address=S.FACTORY, event=S.factory_event("TokenLaunched"),
                      indexed=[token, curve, S.BUYER],
                      data_values=[S.NATIVE,
                                   int(LAUNCH_SEED["launch_config_id"]),
                                   int(LAUNCH_SEED["graduation_threshold"])],
                      block=block)


def trades(first_block: int, n: int, *, every: int = 10, curve=S.CURVE,
           quote_in: int = 10 ** 16, creator_tax_bps: int = 200) -> list:
    """``n`` ordinary buys, one every ``every`` blocks. Invented amounts.

    The integers are the curve's own: ``fee = quote * fee_bps / 10_000``,
    ``tax = quote * creator_tax_bps / 10_000`` and
    ``tokensOut = net * T / (Q + net)`` in integer arithmetic, walked forward
    from the pinned launch seed — which is what
    :class:`flytrade.pons.curve.CurveReconstruction` re-derives and refuses a
    stream that does not reproduce. Nothing here is an observation; it is a
    tape that the real reconstruction accepts.
    """
    from flytrade.pons.curve import BPS
    from flytrade.pons.seed import seed_state

    state = seed_state(int(creator_tax_bps))
    reserved = state.token_reserve - state.sellable_tokens
    out = []
    for i in range(int(n)):
        fee = int(quote_in) * state.fee_bps // BPS
        tax = int(quote_in) * int(creator_tax_bps) // BPS
        net = int(quote_in) - fee - tax
        tokens = net * state.token_reserve // (state.quote_reserve + net)
        tokens = min(tokens, state.sellable_tokens)
        out.append(S.make_log(
            address=curve, event=S.curve_event("CurveBuy"),
            indexed=[S.BUYER, S.BUYER],
            data_values=[int(quote_in), tokens, fee, tax],
            block=int(first_block) + i * int(every), log_index=1))
        token_reserve = state.token_reserve - tokens
        state = replace(state, quote_reserve=state.quote_reserve + net,
                        real_quote_reserve=state.real_quote_reserve + net,
                        token_reserve=token_reserve,
                        sellable_tokens=max(token_reserve - reserved, 0))
    return out


def config(tmp_path: Path, **over) -> dict:
    """The committed configuration, with the scripted chain's own constants."""
    cfg = json.loads((ROOT / "product" / "pons_live.json").read_text())
    cfg["settlement"]["median_block_interval_s"] = 1.0
    cfg["settlement"]["confirm_depth_blocks"] = 60
    cfg["limits"]["backfill_seconds"] = 5
    cfg["limits"]["backfill_requests"] = 200
    cfg["limits"]["hourly_request_cap"] = 100_000
    for key, value in over.items():
        section, _, name = key.partition(".")
        if name:
            cfg[section][name] = value
        else:
            cfg[key] = value
    return cfg


class ScriptedDecoder:
    """BUY until ``buys`` positions have been opened, then WAIT. Invented.

    It exists so that the loop's *mechanics* — the position, the settlement,
    the CREDIT that is recorded and not applied, the resume of an open
    position — can be tested without the frozen brain's answer on a scripted
    tape deciding whether the test runs. Every number it reports (the valence,
    the rates, the status) is the **real** decoder's own: only the action is
    overridden, and only while the loop is flat.
    """

    def __init__(self, execution=None, buys: int = 1):
        self.x = execution
        self.buys = int(buys)
        self.calls = 0

    def decode(self, presentation):
        self.calls += 1
        out = RO.decoder_k8().decode(presentation)
        if self.x is None or out.status is not D.ReadoutStatus.VALID:
            return out
        open_now = self.x.account.position is not None
        opened = len(self.x.outcomes) + (1 if open_now else 0)
        action = (D.Action.BUY if (not open_now and opened < self.buys)
                  else D.Action.WAIT)
        return replace(out, action=action)

    def as_dict(self):
        return {"version": "scripted-for-tests"}


def stack(tmp_path, *, clock=None, logs=None, head: int = 1_000, cfg=None,
          decoder=None, log=None, monkeypatch=None):
    """The whole worker on the scripted chain. Returns what ``build`` returns."""
    clock = clock or Clock()
    cfg = cfg or config(tmp_path)
    endpoint = S.TickingEndpoint(logs=list(logs or []), head=head,
                                 first=max(0, head - 400), clock=clock.now)
    paths = RUN.paths_of(cfg, tmp_path)
    paths["dir"].mkdir(parents=True, exist_ok=True)
    Path(paths["stop"]).unlink(missing_ok=True)      # as `run_worker` does
    if monkeypatch is not None:
        monkeypatch.setenv(cfg["endpoint"]["env_key"], URL)
    built = RUN.build(cfg, paths=paths, log=log or (lambda *a, **k: None),
                      opener=endpoint, now=clock.now, sleep=clock.sleep)
    built.update(endpoint=endpoint, clock=clock, paths=paths, cfg=cfg,
                 tmp_path=tmp_path)
    if decoder is not None:
        if getattr(decoder, "x", "keep") is None:
            decoder.x = built["execution"]
        built["loop"].decoder = decoder
    RUN.wire_state(built, started_at=clock.now())
    return built


def stop_after(built: dict, ticks: int):
    """Write the stop flag once ``ticks`` ticks have happened."""
    driver = built["driver"]
    original = driver.on_tick

    def hook(d):
        if original is not None:
            original(d)
        if d.ticks_done >= int(ticks):
            Path(built["paths"]["stop"]).write_text("test\n")
    driver.on_tick = hook


def read_events(built: dict) -> list[dict]:
    rows = []
    for path in sorted(Path(built["paths"]["dir"]).glob("events-*.jsonl")):
        for line in path.read_text().splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return sorted(rows, key=lambda e: e["seq"])


def read_state(built: dict) -> dict:
    return json.loads(Path(built["paths"]["state"]).read_text())
