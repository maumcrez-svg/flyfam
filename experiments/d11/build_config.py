#!/usr/bin/env python
"""Write ``experiments/d11/config.json`` — the registration, before the numbers.

    .venv/bin/python experiments/d11/build_config.py            # register (step i)
    .venv/bin/python experiments/d11/build_config.py --calibrated  # step (ii)

Step (i) writes the admission constants, the ten v2 features in their declared
order with each scale **rule** written out, the calibration rule verbatim, the
calibration-set selection rule, ``reinforce_full_scale`` as a per-experiment
parameter with its old value stated, the next-run identity and the statement
that D11 runs no neural experiment. The two fitted feature scales and the new
reinforcement scale read ``null`` with the rule beside them.

Step (ii) re-runs the same builder with ``--calibrated``, which reads the two
committed artifacts ``reward_calibration.json`` and ``feature_scales_v2.json``
and substitutes their numbers — and the ``input_schema_sha256`` those numbers
determine — and changes nothing else. The diff of the calibration commit is
exactly those values.

The channel map is derived from ``data/malecns-v1.0/annotations.npz`` by
``flytrade.encoder.channel_glomeruli``, which contains no market quantity.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
HERE = ROOT / "experiments" / "d11"

FEATURES = ("age", "since_last_trade", "ret_30s", "ret_2m", "ret_5m",
            "flow_imb_2m", "trade_count_2m", "gross_volume_2m", "rv_2m",
            "drawdown_5m")

#: Every scale that is a declared constant, and where it comes from.
FIXED_SCALES = {
    "age": 600.0,
    "since_last_trade": 60.0,
    "ret_30s": 0.0051,
    "ret_2m": 0.11,
    "ret_5m": 0.36,
    "flow_imb_2m": 1.0,
    "rv_2m": 0.029,
    "drawdown_5m": 0.51,
}
FITTED = ("trade_count_2m", "gross_volume_2m")

SCALE_RULES = {
    "age": "fixed constant 600 s, carried unchanged from experiments/d10/config.json (p90 of |x| on the first 60 minutes of d10-backfill-v1, rounded to two significant figures, computed there before any outcome existed)",
    "since_last_trade": "fixed constant 60 s, DECLARED by Fable addendum 4 and equal to maximum_seconds_since_last_trade, so an admitted token spans tanh(x/60) in (0, 0.76] and a held token that goes quiet keeps rising toward 1. It is not fitted to any sample.",
    "ret_30s": "fixed constant 0.0051, carried unchanged from experiments/d10/config.json",
    "ret_2m": "fixed constant 0.11, carried unchanged from experiments/d10/config.json",
    "ret_5m": "fixed constant 0.36, carried unchanged from experiments/d10/config.json",
    "flow_imb_2m": "fixed constant 1.0, carried unchanged from experiments/d10/config.json (the feature is bounded in [-1, 1] by construction)",
    "trade_count_2m": "FITTED BY RULE X, VALUE PENDING THE CALIBRATION COMMIT",
    "gross_volume_2m": "FITTED BY RULE X, VALUE PENDING THE CALIBRATION COMMIT",
    "rv_2m": "fixed constant 0.029, carried unchanged from experiments/d10/config.json",
    "drawdown_5m": "fixed constant 0.51, carried unchanged from experiments/d10/config.json",
}

RULE_X = (
    "RULE X, registered here before it is computed: the scale of a fitted "
    "feature is p90 of |x| over the 30-second grid points of the tokens "
    "launched in the first 60 minutes of d10-backfill-v1 at which "
    "admission_v2 admits that token at that grid point, computed causally at "
    "each grid point with the tape truncated there, rounded to two "
    "significant figures. No outcome, no post-cutoff return, no PnL and no "
    "survival is computed anywhere in the fitting, and the fit is never "
    "repeated after a run is observed. The denominator is the admitted "
    "(token, grid point) pairs; its size is recorded in "
    "experiments/d11/feature_scales_v2.json."
)

CALIBRATION_RULE = (
    "q = 90th percentile of abs(net_return) over the calibration set, with "
    "linear interpolation.\n"
    "new_full_scale = max(old_full_scale, 2 * q)."
)

CALIBRATION_SET_RULE = (
    "The calibration set is the distinct, confirmed D10 LEARN outcomes that "
    "actually generated the reported learning updates: the eight LEARNING "
    "records that exist, namely d10-001/learning episodes 4000000, 36000009, "
    "68000017, 100000022, 132000028, 165000109 and 203000217, and "
    "d10-live-001 episode 7000087. Excluded: the determinism re-run of "
    "d10-001/learning (the same events, not new ones, same normalised "
    "sha256 34a74b0b780e...); the eight SETTLED_FROZEN outcomes of "
    "d10-001/frozen_reference (no reinforcement was ever called); the "
    "pending live position d10-live-001 episode 72000315 "
    "(PENDING_CONFIRMATION, no exit leg, no settlement); and every estimated "
    "or unavailable settlement. net_return = net_pnl / notional with "
    "notional 0.01 ETH, read back from the OUTCOME records and re-derived "
    "from the leg integers published in experiments/d10/closure_complement.md; "
    "the two must agree."
)


def channel_map():
    from flytrade import encoder as E
    from flytrade import populations as P
    ann = P.Annotations.load(ROOT / "data" / "malecns-v1.0" / "annotations.npz")
    enc = E.MarketToSensoryEncoder(ann, features=FEATURES)
    return enc.channel_table(ann), int(enc.n_orns)


def build(calibrated: bool) -> dict:
    table, n_orns = channel_map()
    fitted_meta = None
    reward = None
    fitted_values = {name: None for name in FITTED}
    if calibrated:
        fs = json.loads((HERE / "feature_scales_v2.json").read_text())
        for name in FITTED:
            fitted_values[name] = float(fs["scales"][name])
        fitted_meta = fs["statistics"]
        reward = json.loads((HERE / "reward_calibration.json").read_text())
    scales = {name: (FIXED_SCALES[name] if name in FIXED_SCALES
                     else fitted_values[name]) for name in FEATURES}

    cfg = {
        "config_version": "flytrade-d11-config-1",
        "plan": "experiments/d11/PLAN.md",
        "committed_alone_before_any_number": True,
        "amendment": ("docs/SPEC.md, D11 canonical amendment (owner, "
                      "2026-09-12), the owner rationale recorded with it and "
                      "the nine Fable addenda"),
        "wave": "D11",
        "venue": "PONS",
        "chain_id": 4663,
        "network": "Robinhood Chain",
        "native_asset": "ETH",
        "label": ("RECENT-ACTIVITY ADMISSION, SENSORY CONTEXT V2 AND THE "
                  "REINFORCEMENT SCALE"),
        "d11_runs_no_neural_experiment": (
            "D11 is design, implementation and focused tests. It starts no "
            "historical and no live market-neural run, collects no new RPC "
            "data, exercises nothing live, searches no parameter, does no "
            "visual work and touches no real money. The only numbers it "
            "computes are the reward calibration, the two fitted feature "
            "scales and the retrospective admission/encoder diagnostic, all "
            "from artifacts that already exist on disk."),
        "preserved_from_d10_unchanged": [
            "k = 8, gain 0.1, 100 steps, 20 ms presentation window",
            "decoder populations, signs, baseline and thresholds",
            "the biological plasticity mechanism and the learning rate",
            "normalised episode-specific credit assignment, one update per settled outcome",
            "exact integer curve quoting, the three curve costs, gas and the accounting identities",
            "the fixed 900-second horizon and the 0.01 ETH position size",
            "collector budgets, recovery, the observer contracts and the upstream audit",
            "cadence 30 s, at most 6 candidates per round, one open position, long only",
            "round-robin rotation, blind to price, volume, flow, outcome and ticker",
            "REINFORCE_CAP = 1.0, the signed normalisation and clipping mechanism, neutral treatment and the eligibility rules",
        ],
        "admission": {
            "version": "admission_v2",
            "module": "flytrade/pons/admission_v2.py",
            "v1_is_untouched": ("flytrade/pons/admission.py keeps admission_v1 "
                                "byte-identical so every D10 log, test and the "
                                "determinism check keep reproducing"),
            "constants": {
                "recent_window_seconds": 120,
                "minimum_valid_trades_in_window": 2,
                "maximum_seconds_since_last_trade": 60,
            },
            "constants_are_an_engineering_choice": (
                "these three numbers are a declared initial engineering "
                "default, not a discovery about which tokens profit. They are "
                "registered here before any D11 number is computed and are not "
                "searched, tuned or revisited after a run is observed."),
            "valid_trade": (
                "a CurveBuy or CurveSell event with a nonzero quote leg and a "
                "nonzero token leg, deduplicated by log id, with orphaned and "
                "removed logs excluded. Creation, liquidity configuration, "
                "CurveCompleted and duplicated log lines are not trades. A "
                "snipe-tax exemption is not a trade and a snipe-taxed buy is "
                "an ordinary trade. The same definition is used by "
                "pons_context_v2 for trade_count_2m, gross_volume_2m, "
                "flow_imb_2m, rv_2m and since_last_trade."),
            "rule_for_a_new_entry": [
                "every admission_v1 condition EXCEPT its '>= 3 trades ever': deployment pons-v2, quote asset native ETH, curve not completed at the cutoff, reconstructed state valid (sellableTokens > 0 and realQuoteReserve > 0), the 0.01 ETH paper buy does not exhaust the curve, age >= 60 s, and in replay cutoff + latency + horizon inside the token's coverage",
                "AND at the cutoff: at least minimum_valid_trades_in_window valid trades inside (cutoff - recent_window_seconds, cutoff]",
                "AND the last valid trade at most maximum_seconds_since_last_trade before the cutoff",
            ],
            "evaluated_against": ("the canonical market-information cutoff, "
                                  "using only successfully decoded events "
                                  "available at that cutoff. No future event "
                                  "enters an admission decision."),
            "never_ranked_by": ["future returns", "eventual survival", "ticker",
                                "direction of the recent return",
                                "promoter identity", "any desired trading outcome"],
            "not_a_classifier": ("these are recent-activity filters. They are "
                                 "not an organic-flow, anti-manipulation or "
                                 "profitability classifier and must never be "
                                 "reported as one."),
            "reversible": ("admission is evaluated fresh at every tick from the "
                           "tape as it stands, so an inactive candidate returns "
                           "the moment new qualifying activity appears. Nothing "
                           "is remembered between ticks except the rotation "
                           "counter."),
            "reason_codes": {
                "INACTIVE": "the tape is complete at this cutoff and the recency rule fails: fewer than 2 valid trades in the window, or the last valid trade more than 60 s back",
                "INSUFFICIENT_HISTORY": "age < 60 s, or the cutoff precedes the launch, or the tape is too short to answer",
                "COLLECTOR_LAG": "the observation's confirmed/fast block is more than 2 ticks (60 s) behind the cutoff clock. Replay: never, by construction",
                "QUOTE_UNSUPPORTED": "the quote asset is not native ETH",
                "ROUTE_COMPLETED": "the curve completed onto the unsupported post-graduation route at or before the cutoff",
                "STATE_INVALID": "the reconstructed state fails its own arithmetic, or sellableTokens <= 0, or realQuoteReserve <= 0",
                "COVERAGE": "replay only: cutoff + latency + horizon lies outside the token's coverage",
                "CURVE_EXHAUSTED": "the 0.01 ETH paper buy would exhaust the curve (a refund, or tokens_out >= sellableTokens)",
                "DEPLOYMENT_UNSUPPORTED": "carried unchanged from admission_v1: the deployment is not the supported pons-v2 curve route. DECLARED ADDITION to the eight codes the addendum names, because dropping it would either admit a v1-factory curve or mislabel it as QUOTE_UNSUPPORTED",
                "ROTATED": "carried unchanged from admission_v1: admitted, but not presented this round by the round-robin",
            },
            "collector_lag_is_not_inactivity": (
                "a COLLECTOR_LAG on the whole tracked set marks the round "
                "DATA_LAG. A collector outage can never be reported as every "
                "token becoming inactive."),
            "round_statuses": {
                "NO_ELIGIBLE_CANDIDATES": "no tracked token qualified at this cutoff. No presentation happens and nothing is relaxed to force a decision",
                "DATA_LAG": "every considered token was excluded by COLLECTOR_LAG",
            },
            "never_relaxed": ("the criteria are never relaxed automatically to "
                              "force a decision, and fewer than six candidates "
                              "are used when fewer qualify."),
            "controls_new_entries_only": (
                "a held position is observed, marked and settled at its own "
                "horizon regardless of whether its token still satisfies "
                "admission. Admission gates entries, never exits."),
            "rotation": "unchanged from admission_v1, round-robin and blind to every price",
            "max_candidates_per_round": 6,
            "track_seconds": 3600,
        },
        "features": {
            "version": "pons_context_v2",
            "module": "flytrade/pons/context_v2.py",
            "v1_is_untouched": ("flytrade/pons/context.py keeps pons_context_v1 "
                                "byte-identical"),
            "order": list(FEATURES),
            "count": len(FEATURES),
            "causal": ("every feature is computed from tape points at or "
                       "before the cutoff and from nothing after it"),
            "windows_clipped_to_launch": (
                "as in D10: ret_w = log(p(cutoff) / p(max(cutoff - w, launch))) "
                "and drawdown_5m maxes from max(cutoff - 5 min, launch). A "
                "window that starts before the launch is measured from the "
                "launch, never zeroed."),
            "definitions": {
                "age": "seconds since the launch block",
                "since_last_trade": "seconds since the last VALID trade at or before the cutoff; when the token has never traded it is the age, which is the same clipped-to-launch convention every windowed feature uses. It is a sensory input only and is never fed to a reward or output neuron",
                "ret_30s": "log change of the marginal curve price over 30 s",
                "ret_2m": "the same over 120 s",
                "ret_5m": "the same over 300 s",
                "flow_imb_2m": "(buy quote in - sell quote out) / (their sum) over the valid trades of the last 120 s, in [-1, 1]; 0 when the window is empty",
                "trade_count_2m": "the number of VALID trades inside (cutoff - 120 s, cutoff]. It replaces D10's trade_rate_2m, which was the same count divided by the window in minutes",
                "gross_volume_2m": "the sum of |curve-side quote delta| over the valid trades of the last 120 s, in ETH: a buy contributes its net quote into the curve (quoteIn - fee - tax) and a sell its gross quote out of the curve (quoteOut + fee + tax). This is the GROSS traded volume, the absolute sum, against flow_imb_2m's signed one; the per-leg convention is the same signed quantity TokenTape.apply stores as flow",
                "rv_2m": "SD of per-trade log marginal-price changes over the valid trades of the last 120 s",
                "drawdown_5m": "log distance below the 5-minute maximum marginal price, <= 0",
            },
            "the_four_owner_distinctions": {
                "A_no_trades_in_the_observed_interval": "trade_count_2m = 0 and gross_volume_2m = 0 with since_last_trade large",
                "B_many_trades_and_almost_no_net_price_change": "trade_count_2m and gross_volume_2m high, ret_30s / ret_2m / ret_5m near 0, rv_2m small",
                "C_balanced_buys_and_sells_with_meaningful_gross_volume": "gross_volume_2m high with flow_imb_2m near 0",
                "D_missing_or_incomplete_observations": "NOT PRESENTED. The status is INSUFFICIENT_TAPE, INCONSISTENT_STATE or COLLECTOR_LAG and the candidate is excluded with its reason; it is never a zero vector",
            },
            "missing_is_not_zero": (
                "an unusable observation is not encoded at all. There is no "
                "stub returning zeros, because a modality or a measurement "
                "that returns zeros is indistinguishable from one that was "
                "never made."),
            "no_manufactured_diversity": (
                "no random jitter, no ticker-dependent stimulation and no "
                "invented activity. Two tokens with equal raw vectors and "
                "different addresses produce equal rate vectors, and that is "
                "asserted by a test. Identical measured contexts are ALLOWED "
                "to encode identically; the requirement is to preserve the "
                "declared distinctions, not to make every token unique."),
            "normalisation": "tanh(raw / scale), fixed declared scales, never refitted during operation",
            "scales": scales,
            "scale_rules": SCALE_RULES,
            "rule_x": RULE_X,
            "fitted_features": list(FITTED),
            "scale_artifact": "experiments/d11/feature_scales_v2.json",
            "scale_statistics": fitted_meta,
            "single_signed": ["age", "since_last_trade", "trade_count_2m",
                              "gross_volume_2m", "drawdown_5m"],
            "single_signed_note": (
                "five of the ten features never change sign, so one glomerulus "
                "of each of those pairs only ever receives the carrier. They "
                "keep the two-channel rule anyway, as D10 declared. rv_2m is a "
                "standard deviation and is non-negative by construction too, "
                "and is listed here as it was in D10: not declared "
                "single-signed, and in fact never negative."),
        },
        "encoder": {
            "version": "pons_encoder_v2",
            "module": "flytrade/pons/encoder_v2.py",
            "v1_is_untouched": "flytrade/pons/encoder.py keeps pons_encoder_v1 byte-identical",
            "interface": "flytrade.pons.encoder_v2.SensoryEncoderV2",
            "olfactory": "flytrade.encoder.MarketToSensoryEncoder, unchanged; the verified olfactory pathway, with no gain or decoder retune",
            "modalities_returned": ["olfactory"],
            "extension_points_named_and_unimplemented": ["visual", "taste",
                                                         "mechanosensory"],
            "channels_needed": 2 * len(FEATURES),
            "candidate_glomeruli_available": 31,
            "orns": n_orns,
            "channel_map": table,
            "coding": "normalized",
            "carrier": 0.1,
            "drive_budget_hz": 12000.0,
            "drive_max_hz": 150.0,
            "steps": 100,
            "window_ms": 20,
            "global_gain": 0.1,
            "input_schema_sha256": (None if not calibrated else None),
            "input_schema_rule": (
                "sha256 of the canonical JSON {\"features\": [the ordered "
                "feature names], \"scales\": {name: scale}, \"channels\": [the "
                "channel map rows]} with sorted keys and no whitespace. It "
                "cannot be computed until the two fitted scales exist, so it "
                "is written by the calibration commit together with them."),
            "checkpoint_metadata": (
                "the checkpoint's metadata gains encoder_version and "
                "input_schema_sha256. Loading a checkpoint whose metadata "
                "carries a DIFFERENT schema hash for continued learning "
                "RAISES. The one exception is a run declared "
                "from_clean_reference whose checkpoint is the clean reference "
                "itself, which predates the field and is the only checkpoint "
                "allowed to lack it."),
        },
        "reinforcement": {
            "updates_per_settled_episode": 1,
            "attributed_to": "the entry decision's stored k=8 eligibility trace set, by episode id",
            "mapping": ("valence is the sign of the settled net outcome and "
                        "amount is min(|net_pnl / notional| / "
                        "reinforce_full_scale, reinforce_cap) — "
                        "flytrade.execution.ExecutionPolicy.reinforcement, "
                        "mechanism unchanged. Only the full-scale parameter "
                        "moves."),
            "reinforce_cap": 1.0,
            "reinforce_full_scale_is_per_experiment": (
                "reinforce_full_scale becomes a per-experiment configuration "
                "parameter, read from this file by the Pons loop's execution "
                "policy. flytrade.execution.REINFORCE_FULL_SCALE stays 0.01, "
                "every D5-D10 code path stays byte-identical, and the IBM "
                "historical loop keeps reading its own config's 0.01."),
            "old_full_scale": 0.01,
            "new_full_scale": (None if reward is None
                               else float(reward["new_full_scale"])),
            "calibration_rule": CALIBRATION_RULE,
            "calibration_set_rule": CALIBRATION_SET_RULE,
            "calibration_artifact": "experiments/d11/reward_calibration.json",
            "q": None if reward is None else float(reward["q"]),
            "sample_count": None if reward is None else int(reward["n"]),
            "same_scale_for_both_signs": (
                "the same scale is used for positive and negative outcomes. "
                "No average loss is subtracted, no cost is refunded through "
                "the reward, and a net loss is never converted into positive "
                "reinforcement."),
            "frozen_for_the_next_experiment": (
                "the scale is frozen for the next experiment version. There is "
                "no rolling recalibration during operation, and the "
                "multiplier, the quantile and the scale are never tuned after "
                "observing a BUY frequency or a run's performance."),
            "not_applied_to_old_checkpoints": (
                "the proposed rewards are NOT applied to any old checkpoint. "
                "D10's learned state stays exactly as it is."),
            "coarse_engineering_reference": (
                "the calibration set is eight selected outcomes from one "
                "15-minute-horizon window on one instrument class. It is a "
                "coarse engineering reference for a scale parameter and is "
                "not an estimate of the memecoin market's return "
                "distribution."),
            "no_interim_reward": True,
            "no_reward_from_a_blocked_sell": True,
            "no_reward_from_a_mark": True,
            "no_counterfactual_reward_for_skipped_entries": True,
        },
        "next_run": {
            "id": "d11-001",
            "status": "DECLARED, NOT RUN. It is the owner's next decision and D11 stops before it.",
            "from_clean_reference": True,
            "clean_reference_checkpoint": {
                "graph_sha256": "8feb08a0d2a80cbcf69328f9707d5dd748d73d2e12246526d96e48d995f843b9",
                "plastic_synapses": 44042,
                "gain": 1.0,
                "state_digest": "ba95b60503d658e989b649ecd3994264791fbead92f0bdacfd555e5d86ab61f5",
            },
            "shape": ("one replay branch on data/pons/d10-backfill-v1 from the "
                      "clean reference checkpoint, then one live hour, with an "
                      "evaluation designed before the run"),
            "it_is_a_new_environment_experiment": (
                "d11-001 is an explicit new encoder/environment experiment "
                "under a new identity. It is NOT a silent erasure of D10's "
                "losses or learned state: d10-001 and d10-live-001 keep their "
                "identities, their logs, their checkpoints and their pending "
                "position, available for recovery under their original policy. "
                "The pending live position (d10-live-001, episode 72000315) is "
                "not cancelled, closed or migrated because the observation "
                "exercise ended."),
            "a_combined_correction_cannot_attribute": (
                "admission, sensory context and the reinforcement scale change "
                "together. A later behavioural difference cannot be attributed "
                "to any one of them, and d11-001 must be reported as an "
                "integrated environment repair, never as isolated proof about "
                "one component."),
        },
        "success_is_not": [
            "a profit, a win rate or a BUY frequency",
            "a smaller loss than D10",
            "any comparison of d11-001 with d10-001, which ran a different environment",
        ],
        "no_parameter_changes_after_observing_results": True,
        "profitability_is_not_a_gate_metric": True,
    }
    if calibrated:
        cfg["encoder"]["input_schema_sha256"] = schema_hash(
            list(FEATURES), scales, table)
    return cfg


def schema_hash(features, scales, channels) -> str:
    """The rule, in one place: features + scales + channel map, sha256."""
    import hashlib
    payload = json.dumps(
        {"features": list(features),
         "scales": {k: float(scales[k]) for k in features},
         "channels": channels},
        sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--calibrated", action="store_true")
    ap.add_argument("--out", default=str(HERE / "config.json"))
    args = ap.parse_args(argv)
    cfg = build(args.calibrated)
    Path(args.out).write_text(json.dumps(cfg, indent=1) + "\n")
    print(f"wrote {args.out} (calibrated={args.calibrated})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
