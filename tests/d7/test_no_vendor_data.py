"""
No downloaded market data enters the D7 suite — amendment D7 §10, D6 addendum 10.

``tests/historical/`` already enforces this for the whole ``tests/`` tree; this
file states it again for the D7 fixtures, and adds the property that makes the
statement checkable: the generator is deterministic, so "the fixture" is a
file anyone can reproduce from the committed script rather than an artifact
somebody once had on disk.
"""
from __future__ import annotations

from pathlib import Path

from tests.d7 import make_fixtures as MF

ROOT = Path(__file__).resolve().parents[2]


def test_the_d7_fixture_generator_is_deterministic(tmp_path):
    one = MF.write_all(tmp_path / "one")
    two = MF.write_all(tmp_path / "two")
    for k in one:
        assert one[k].read_bytes() == two[k].read_bytes(), k


def test_no_d7_test_reads_the_downloaded_vendor_files(fixtures):
    """The needle is assembled at run time so this file cannot match itself."""
    needle = "data" + "/" + "mar" + "ket"
    offenders = []
    for f in sorted((ROOT / "tests" / "d7").rglob("*.py")):
        for n, line in enumerate(f.read_text().splitlines(), start=1):
            if needle in line and "gitignored" not in line \
                    and "No downloaded" not in line and "only by" not in line:
                offenders.append(f"{f.relative_to(ROOT)}:{n}: {line.strip()}")
    assert offenders == []
    assert needle not in str(fixtures["W"])


def test_the_fixtures_are_full_sessions_so_the_longest_horizon_is_testable(
        clean):
    """A 120-minute fixture session would have no eligible origin at all."""
    from flytrade import horizon as HZ
    assert all(s.n_present in (390, 389) for s in clean.sessions.values())
    day = MF.DAYS[1]
    assert len(HZ.common_origins(clean, day, HZ.H_SET)) > 100


def test_the_warmup_and_later_fixture_days_are_disjoint():
    assert set(MF.WARMUP_DAYS).isdisjoint(MF.LATER_DAYS)
    assert set(MF.WARMUP_DAYS) | set(MF.LATER_DAYS) == set(MF.DAYS)
