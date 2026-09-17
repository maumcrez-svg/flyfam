"""Which teacher a configuration selects, and what the relative one says.

D12 changes **one thing**: the teacher. `docs/SPEC.md`'s D12 owner spec and
Fable addenda 1 and 3 put two rules behind one configuration key:

``absolute_profit_v1``
    what D5-D11 ran and still run. ``valence`` is the sign of the settled net
    outcome and ``amount`` is
    :meth:`flytrade.execution.ExecutionPolicy.reinforcement`'s normalised
    magnitude, clipped at ``REINFORCE_CAP``. Nothing about it moves here: this
    module **delegates** to that method rather than restating its arithmetic,
    so a D10 or a D11 configuration takes a path that is byte-identical to the
    one it took before this file existed.

``relative_cohort_v1``
    the D12 teacher. The cohort is the eligible candidates of **one tick** that
    have a settled evaluator label; a member ranks against the others it was
    seen beside, and the rank — not the money — is the lesson. A cohort in
    which every member lost money still teaches which member lost least.

**This is not a profit reward and must never be called one.** The financial net
and the pedagogical signal are two quantities and the caller keeps them in two
columns. No profit is falsified: the net is what it is.

Rank rather than z-score, because it is scale-free, immune to the tail that
saturated two reinforcement calibrations, and zero-mean per cohort by
construction. **No clipping can occur** — ``|s| <= 1`` by definition — and
neither ``REINFORCE_CAP`` nor ``reinforce_full_scale`` is consulted by the
relative rule.
"""

from __future__ import annotations

VERSION = "pons_reinforcement_v1"

#: the D5-D11 rule: the sign and normalised magnitude of the settled net
ABSOLUTE_PROFIT_V1 = "absolute_profit_v1"

#: the D12 rule: where this candidate ranked among the candidates of its tick
RELATIVE_COHORT_V1 = "relative_cohort_v1"

RULES = (ABSOLUTE_PROFIT_V1, RELATIVE_COHORT_V1)

#: what a configuration with no ``reinforcement.rule`` key selects — every
#: configuration written before D12, so no existing run changes behaviour.
DEFAULT_RULE = ABSOLUTE_PROFIT_V1

#: PLAN.md §3: a cohort smaller than this teaches nothing. Two members give
#: only ``-1`` and ``+1``, which is a coin toss dressed as a ranking.
N_MIN = 3

#: discard reasons a caller records per tick, so a lesson that never happened
#: is a counted line rather than a silence
UNRESOLVED = "UNRESOLVED"
COHORT_TOO_SMALL = "COHORT_TOO_SMALL"
BOUNDARY = "BOUNDARY"
DISCARD_REASONS = (UNRESOLVED, COHORT_TOO_SMALL, BOUNDARY)


class UnknownRule(ValueError):
    """A configuration named a reinforcement rule this repository does not have."""


def rule_from_config(config: dict | None) -> str:
    """The reinforcement rule a configuration selects.

    ``None``, a missing ``reinforcement`` block and a missing ``rule`` key all
    mean :data:`DEFAULT_RULE`, which is the absolute rule. A *present* rule
    that is not one of :data:`RULES` raises rather than falling back: a
    configuration that names a teacher nobody implemented must stop the run,
    not quietly train under a different one.
    """
    block = ((config or {}).get("reinforcement") or {})
    name = block.get("rule")
    if name is None:
        return DEFAULT_RULE
    name = str(name)
    if name not in RULES:
        raise UnknownRule(
            f"reinforcement.rule {name!r} is not one of {RULES}")
    return name


def average_ranks(values) -> list[float]:
    """1-based ranks ascending, **ties sharing their average rank**.

    ``[10, 20, 20, 40]`` gives ``[1.0, 2.5, 2.5, 4.0]``. The order of the
    input is preserved in the output, and equality is the caller's own
    equality — integers stay integers, so two identical wei figures tie
    exactly rather than by tolerance.
    """
    rows = list(values)
    order = sorted(range(len(rows)), key=lambda i: rows[i])
    out = [0.0] * len(rows)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and rows[order[j + 1]] == rows[order[i]]:
            j += 1
        shared = (i + j) / 2.0 + 1.0          # average of the 1-based ranks
        for k in range(i, j + 1):
            out[order[k]] = shared
        i = j + 1
    return out


def relative_cohort_signals(nets, *, n_min: int = N_MIN) -> list[float] | None:
    """``s`` for every member of one cohort, or ``None`` when it is too small.

    ``nets`` is the cohort's settled net outcomes — integers in wei, as the
    evaluator label produces them — in any order; the result is in the same
    order. With ``n`` the cohort size and ranks ascending with average ranks
    for ties::

        s_i = 2 * (rank_i - 1) / (n - 1) - 1        in [-1, +1]

    so the worst net is ``-1``, the best is ``+1``, and the mean over a cohort
    is exactly 0. It is evaluated in the algebraically identical form
    ``(2 * rank_i - n - 1) / (n - 1)``, which is one division instead of a
    division and a subtraction and therefore lands on the exact double the
    registered example names (``0.6``, not ``0.6000000000000001``). The rule is
    the registered rule; only the arithmetic is arranged not to lose a bit.

    ``None`` — never an empty list and never zeros — when ``n < n_min``, so a
    caller cannot mistake "this cohort teaches nothing" for "this cohort
    teaches neutrality".
    """
    rows = list(nets)
    n = len(rows)
    if n < int(n_min):
        return None
    ranks = average_ranks(rows)
    return [(2.0 * r - n - 1) / (n - 1) for r in ranks]


def reinforcement_from_signal(s: float) -> tuple[int, float]:
    """``(valence, amount)`` for one relative signal.

    ``s > 0`` is a reward and ``s < 0`` a punishment, both of amount ``|s|``.
    ``s == 0`` is neutral and delivers nothing — the existing neutral
    treatment, the same one a net outcome of exactly zero gets under the
    absolute rule. No clipping can occur.
    """
    value = float(s)
    if value == 0.0:
        return 0, 0.0
    return (1 if value > 0.0 else -1), abs(value)


def reinforcement_for(rule: str, *, outcome=None, execution=None,
                      signal=None) -> tuple[int, float]:
    """The one dispatch point: ``(valence, amount)`` under the selected rule.

    Under :data:`ABSOLUTE_PROFIT_V1` this returns exactly
    ``execution.reinforcement(outcome)`` — the same call, with the same
    arguments, producing the same tuple — so the learning path of every wave
    before D12 is unchanged. Under :data:`RELATIVE_COHORT_V1` it returns
    :func:`reinforcement_from_signal` of the cohort signal the caller computed.
    """
    if rule == ABSOLUTE_PROFIT_V1:
        if execution is None or outcome is None:
            raise ValueError("the absolute rule needs an execution and an outcome")
        return execution.reinforcement(outcome)
    if rule == RELATIVE_COHORT_V1:
        if signal is None:
            raise ValueError("the relative rule needs a cohort signal")
        return reinforcement_from_signal(signal)
    raise UnknownRule(f"reinforcement rule {rule!r} is not one of {RULES}")


__all__ = ["VERSION", "ABSOLUTE_PROFIT_V1", "RELATIVE_COHORT_V1", "RULES",
           "DEFAULT_RULE", "N_MIN", "UNRESOLVED", "COHORT_TOO_SMALL",
           "BOUNDARY", "DISCARD_REASONS", "UnknownRule", "rule_from_config",
           "average_ranks", "relative_cohort_signals",
           "reinforcement_from_signal", "reinforcement_for"]
