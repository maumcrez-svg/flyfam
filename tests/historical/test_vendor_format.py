"""
The actual vendor format: parsed explicitly, validated, and rejected.

Amendment D6 §3 and §8 ("actual vendor-format parsing"). The importer is not
allowed to be lenient: a file that is not what the format reference describes
is refused with the row number, never repaired into something plausible.
"""
from __future__ import annotations

from datetime import date, datetime

import pytest

from flytrade import historical as H
from tests.historical import make_fixtures as MF


def test_the_headerless_seven_field_format_is_parsed_field_by_field(fixtures):
    rows, rep = H.parse_kibot_minute(fixtures["A"], "A")
    assert rep.symbol == "A"
    assert rep.dataset_label == "HISTORICAL_MARKET"
    assert rep.rows == len(rows) == 346
    assert rep.time_format == "HH:MM"
    assert rep.sessions == 3
    assert rep.blank_lines == 0
    assert rep.excluded_extended_hours == 0
    first = rows[0]
    # the first row of the file, read back as numbers rather than as text
    line = fixtures["A"].read_text().splitlines()[0].split(",")
    assert line[0] == "08/03/2026" and line[1] == "09:30"
    assert first.open == pytest.approx(float(line[2]))
    assert first.high == pytest.approx(float(line[3]))
    assert first.low == pytest.approx(float(line[4]))
    assert first.close == pytest.approx(float(line[5]))
    assert first.volume == pytest.approx(float(line[6]))
    # and the sha256 in the report is the sha256 of the bytes on disk
    import hashlib
    assert rep.sha256 == hashlib.sha256(
        fixtures["A"].read_bytes()).hexdigest()


def test_both_documented_time_formats_are_accepted_and_recorded(fixtures):
    _, rep = H.parse_kibot_minute(fixtures["seconds"], "S")
    assert rep.time_format == "HH:MM:SS"
    rows_s, _ = H.parse_kibot_minute(fixtures["seconds"], "S")
    rows_m, _ = H.parse_kibot_minute(fixtures["A"], "A")
    # the same minutes, whichever spelling the vendor used
    assert [r.bar_start for r in rows_s] == \
        [r.bar_start for r in rows_m[:len(rows_s)]]


def test_exponent_form_prices_are_read_as_numbers_not_as_text(fixtures):
    rows, rep = H.parse_kibot_minute(fixtures["exponent"], "X")
    assert rep.exponent_prices == 2
    assert rows[0].open == pytest.approx(1e-06)
    assert rows[0].close == pytest.approx(1.5e-06)
    # a fixed-point parser would have read "1E-06" as something else entirely
    assert rows[0].open != 1.0


def test_extended_hours_rows_are_excluded_and_counted_never_kept(fixtures):
    rows, rep = H.parse_kibot_minute(fixtures["extended"], "E")
    assert rep.excluded_extended_hours == 4
    assert rep.rows == 120
    for r in rows:
        assert H.in_regular_session(r.bar_start)
        t = H.ny_datetime(r.bar_start).time()
        assert H.SESSION_OPEN <= t < H.SESSION_CLOSE
    # the 08:00 and 16:30 prints are simply not in the parsed rows
    assert not any(H.ny_datetime(r.bar_start).hour in (8, 9 - 1, 16, 18)
                   and H.ny_datetime(r.bar_start).minute == 0 for r in rows)


@pytest.mark.parametrize("name,fragment", [
    ("dup", "duplicate timestamp"),
    ("unordered", "not strictly increasing"),
    ("ohlc", "OHLC relationship violated"),
    ("sixfields", "the one-minute format has 7"),
    ("nonpositive", "non-positive price"),
])
def test_a_malformed_file_is_refused_with_its_row_number(fixtures, name,
                                                         fragment):
    with pytest.raises(H.VendorFormatError) as exc:
        H.parse_kibot_minute(fixtures[name], name)
    msg = str(exc.value)
    assert fragment in msg
    # the message names the file and the line, so a human can go and look
    assert f"{name}.txt:" in msg


def test_eastern_time_becomes_utc_with_the_right_offset(fixtures):
    rows, _ = H.parse_kibot_minute(fixtures["A"], "A")
    ts = rows[0].bar_start
    # 2026-08-03 is EDT, UTC-4, so 09:30 ET is 13:30 UTC
    assert H.ny_datetime(ts).utcoffset().total_seconds() == -4 * 3600
    from datetime import timezone
    assert datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
        "%Y-%m-%d %H:%M") == "2026-08-03 13:30"
    # and the round trip back to New York wall time is exact
    assert H.ny_datetime(ts).strftime("%Y-%m-%d %H:%M") == "2026-08-03 09:30"
    assert H.session_date(ts) == date(2026, 8, 3)
    assert H.minute_index(ts) == 0


def test_the_fixture_generator_is_deterministic(tmp_path):
    one = MF.write_all(tmp_path / "one")
    two = MF.write_all(tmp_path / "two")
    for k in one:
        assert one[k].read_bytes() == two[k].read_bytes(), k


def test_no_test_reads_the_downloaded_vendor_files(fixtures):
    """The committed suite never opens anything under the download directory.

    The needle is assembled at run time so that this test's own source does
    not contain it and cannot match itself.
    """
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    needle = "data" + "/" + "mar" + "ket"
    offenders = []
    for f in sorted((root / "tests").rglob("*.py")):
        text = f.read_text()
        for n, line in enumerate(text.splitlines(), start=1):
            if needle in line and "gitignored" not in line \
                    and "No downloaded" not in line and "only by" not in line:
                offenders.append(f"{f.relative_to(root)}:{n}: {line.strip()}")
    assert offenders == []
    # and the fixtures these tests do read are in a tmp directory
    assert needle not in str(fixtures["A"])
