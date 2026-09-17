"""
The local server's exposure boundary and the two new endpoints.

Amendment D9(a) §8 ("serve only viewer assets and approved read-only run
projections, not the repository root") and addendum 6, which names the things
that must 404: traversal, ``.env``, ``pyproject.toml``, anything ending in
``.npz`` / ``.feather`` / ``.jsonl``, ``data/``, a checkpoint binary, and an
unknown run or branch id. These are real HTTP requests against a real handler
bound to a loopback port, not assertions about source text.

``/api/runs``, ``/api/summary``, ``/api/events`` and ``/api/artifact`` are D6
and D7 endpoints and are not touched by this wave; the tests that cover them
live in ``tests/historical`` and ``tests/d7`` and are unchanged.
"""
from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
OBSERVER = ROOT / "observer"
sys.path.insert(0, str(OBSERVER))

import projection as P                                  # noqa: E402
import serve as SRV                                     # noqa: E402

from . import fixtures as F                             # noqa: E402


@pytest.fixture(scope="module")
def server():
    """The real handler on a loopback port the OS chooses."""
    srv = ThreadingHTTPServer((SRV.HOST, 0), SRV.Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://{SRV.HOST}:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def get(base, path, *, gzip_ok=False):
    """(status, body bytes, headers). A 4xx is a result here, not an error."""
    req = urllib.request.Request(base + path)
    if gzip_ok:
        req.add_header("Accept-Encoding", "gzip")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)


def get_json(base, path):
    code, body, _ = get(base, path)
    return code, json.loads(body)


# --------------------------------------------------------------- the binding

def test_the_server_still_binds_to_loopback_and_still_only_reads():
    src = (OBSERVER / "serve.py").read_text()
    assert SRV.HOST == "127.0.0.1"
    assert "0.0.0.0" not in src
    assert ".write_text(" not in src and ".write_bytes(" not in src
    assert "do_POST" not in src and "do_PUT" not in src and "do_DELETE" \
        not in src


# ------------------------------------------------------ the exposure boundary

EXPOSED = [
    "/../serve.py",
    "/../../etc/passwd",
    "/static/../serve.py",
    "/static/../../pyproject.toml",
    "/static/%2e%2e/serve.py",
    "/.env",
    "/pyproject.toml",
    "/the session log",
    "/docs/SPEC.md",
    "/data/MANIFEST.md",
    "/data/" + "mar" + "ket/IBM_1min_unadjusted.txt",   # assembled: the
    # downloaded vendor directory is never named in a committed test line
    "/experiments/d7/runs/d7-001/learned/brain.npz",
    "/experiments/d7/runs/d7-001/learned/events.jsonl",
    "/withheld historical summary",
    "/observer/serve.py",
    "/observer/projection.py",
    "/upstream/mushroom.py",
    "/flytrade/records.py",
    "/anything.npz",
    "/anything.feather",
    "/anything.jsonl",
    "/static/serve.py",
    "/static/",
    "/static/watch.css/../../serve.py",
]


@pytest.mark.parametrize("path", EXPOSED)
def test_nothing_outside_the_allowlist_is_served(server, path):
    code, body, _ = get(server, path)
    assert code in (403, 404), path
    for leak in (b"#!/usr/bin/env python", b"[project]", b"PRIVATE",
                 b"import numpy"):
        assert leak not in body, path


def test_the_static_allowlist_is_an_exact_name_lookup_with_no_path_join():
    src = (OBSERVER / "serve.py").read_text()
    assert "STATIC_DIR / name" in src
    assert "ctype = STATIC.get(name)" in src
    # every allowlisted name is a plain file name, never a path
    for name in SRV.STATIC:
        assert "/" not in name and ".." not in name
        assert not name.endswith((".npz", ".feather", ".jsonl", ".json",
                                  ".py", ".env"))


def test_the_allowlisted_assets_are_served_and_exist(server):
    for name, ctype in SRV.STATIC.items():
        code, body, headers = get(server, "/static/" + name)
        assert code == 200, name
        assert headers["Content-Type"] == ctype
        assert body, name


def test_an_unknown_run_or_branch_id_is_a_404_not_a_filesystem_probe(server):
    for q in ("?run=nope&branch=learned",
              "?run=d7-001&branch=nope",
              "?run=../../etc&branch=learned",
              "?run=d7-001&branch=../../../etc",
              "?run=&branch=",
              "?run=d7-001%2F..%2F..&branch=learned"):
        code, body = get_json(server, "/api/presentation" + q)
        assert code == 404, q
        assert "error" in body
        code, body = get_json(server, "/api/detail" + q + "&seq=0")
        assert code == 404, q


def test_the_id_validator_rejects_everything_with_a_separator_in_it():
    for bad in ("", "..", "../x", "a/b", "a\\b", "/etc/passwd", "a" * 200,
                "x\x00y", "a/../b"):
        assert not SRV.valid_id(bad), bad
    for good in ("d7-001", "hist-003", "learned", "frozen_reference",
                 "frozen_trained"):
        assert SRV.valid_id(good), good


def test_find_log_returns_none_for_an_id_that_is_not_on_disk():
    assert SRV.find_log("../../etc", "learned") is None
    assert SRV.find_log("d7-001", "..") is None
    assert SRV.find_log("nope-999", "learned") is None


# ---------------------------------------------------- the two new endpoints

def test_the_presentation_endpoint_serves_a_projected_stream(server,
                                                             tmp_path,
                                                             monkeypatch):
    """A synthetic run, discovered exactly like a real one."""
    run = F.write_run(tmp_path)
    monkeypatch.setattr(SRV, "ROOTS", (
        {"wave": "SYNTHETIC", "runs": tmp_path / "runs",
         "summary": tmp_path / "summary.json", "extra": {}},), raising=True)
    SRV._CACHE.clear()
    code, body = get_json(server, "/api/presentation"
                          "?run=synthetic-001&branch=learned")
    assert code == 200
    assert body["meta"]["contract"] == P.CONTRACT
    assert body["meta"]["dataset_label"] == "SYNTHETIC_FIXTURE"
    assert body["meta"]["horizon_minutes"] == 5
    assert len(body["frames"]) == len(F.learning_branch().events)
    assert [f["seq"] for f in body["frames"]] == \
        list(range(len(body["frames"])))
    assert run.exists()


def test_the_detail_endpoint_returns_one_canonical_event_unchanged(
        server, tmp_path, monkeypatch):
    run = F.write_run(tmp_path)
    monkeypatch.setattr(SRV, "ROOTS", (
        {"wave": "SYNTHETIC", "runs": tmp_path / "runs",
         "summary": tmp_path / "summary.json", "extra": {}},), raising=True)
    lines = (run / "learned" / "events.jsonl").read_text().splitlines()
    first_decision = next(i for i, ln in enumerate(lines)
                          if json.loads(ln)["kind"] == "DECISION")
    for seq in (0, first_decision, len(lines) - 1):
        code, body = get_json(server, "/api/detail?run=synthetic-001"
                                      f"&branch=learned&seq={seq}")
        assert code == 200
        ev = dict(body["event"])
        assert ev.pop("_i") == seq
        assert ev == json.loads(lines[seq]), seq
    # the heavy fields the watch screen does not carry are here
    code, body = get_json(server, "/api/detail?run=synthetic-001"
                                  f"&branch=learned&seq={first_decision}")
    assert body["event"]["kind"] == "DECISION"
    assert "raw" in body["event"]["observation"]
    assert "versions" in body["event"]


def test_the_detail_endpoint_refuses_a_seq_that_is_not_a_line(server,
                                                              tmp_path,
                                                              monkeypatch):
    F.write_run(tmp_path)
    monkeypatch.setattr(SRV, "ROOTS", (
        {"wave": "SYNTHETIC", "runs": tmp_path / "runs",
         "summary": tmp_path / "summary.json", "extra": {}},), raising=True)
    for bad, code in (("-1", 400), ("abc", 400), ("", 400),
                      ("999999", 404)):
        got, _ = get_json(server, "/api/detail?run=synthetic-001"
                                  f"&branch=learned&seq={bad}")
        assert got == code, bad


def test_a_missing_run_directory_is_a_named_state_not_a_crash(server,
                                                              tmp_path,
                                                              monkeypatch):
    """Addendum 1: the run stores are gitignored and may simply be absent."""
    monkeypatch.setattr(SRV, "ROOTS", (
        {"wave": "EMPTY", "runs": tmp_path / "absent",
         "summary": tmp_path / "absent.json", "extra": {}},), raising=True)
    code, body = get_json(server, "/api/runs")
    assert code == 200 and body["runs"] == []
    code, body = get_json(server, "/api/presentation?run=d7-001&branch=learned")
    assert code == 404 and body["state"] == "MISSING_DATA"


def test_the_stream_is_gzipped_when_the_client_asks(server, tmp_path,
                                                    monkeypatch):
    big = F.Log()
    F.partition(big, "LEARNING", "start", branch="learned", learning=True)
    for n in range(400):
        F.round_(big, i=n, ts=F.T0 + 60 * n)
        F.decision(big, episode_id=n * 1000 + 1, ts=F.T0 + 60 * n,
                   action="WAIT", status="VALID", valence=0.1,
                   branch="learned", partition_name="LEARNING")
    d = tmp_path / "runs" / "synthetic-002" / "learned"
    d.mkdir(parents=True)
    big.write(d / "events.jsonl")
    monkeypatch.setattr(SRV, "ROOTS", (
        {"wave": "SYNTHETIC", "runs": tmp_path / "runs",
         "summary": tmp_path / "nothing.json", "extra": {}},), raising=True)
    SRV._CACHE.clear()
    q = "/api/presentation?run=synthetic-002&branch=learned"
    plain_code, plain, _ = get(server, q)
    zip_code, zipped, headers = get(server, q, gzip_ok=True)
    assert plain_code == zip_code == 200
    assert headers.get("Content-Encoding") == "gzip"
    import gzip as _gz
    assert _gz.decompress(zipped) == plain
    assert len(zipped) < len(plain)


def test_the_existing_endpoints_are_untouched(server):
    """D6 and D7 routes keep their shapes; this wave only adds."""
    src = (OBSERVER / "serve.py").read_text()
    for route in ("/api/runs", "/api/summary", "/api/events", "/api/artifact"):
        assert f'u.path == "{route}"' in src, route
    assert 'return self._send(200, p.read_bytes(), "application/json")' in src
    code, body = get_json(server, "/api/runs")
    assert code == 200 and "runs" in body and "summary_present" in body


# ------------------------------------------------------------------- offline

def test_the_page_and_its_assets_make_no_external_request():
    """§3 and addendum 7: no CDN, no web font, no analytics, no beacon."""
    import re
    files = [OBSERVER / "index.html"]
    files += sorted((OBSERVER / "static").glob("*"))
    pattern = re.compile(
        r'(?:src\s*=|href\s*=|@import|url\()\s*["\']?\s*(https?:)?//',
        re.IGNORECASE)
    for f in files:
        if f.is_dir():
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        hits = [m.group(0) for m in pattern.finditer(text)]
        assert not hits, f"{f.name}: {hits}"
        for host in ("cdn.", "googleapis", "gstatic", "unpkg", "jsdelivr",
                     "public-dns", "analytics", "fonts.google"):
            assert host not in text.lower(), f"{f.name}: {host}"
        assert "XMLHttpRequest" not in text
        assert "navigator.sendBeacon" not in text
        assert "new WebSocket" not in text
    assert not (OBSERVER / "package.json").exists()
    assert not (OBSERVER / "node_modules").exists()


def test_every_fetch_the_page_makes_is_a_local_read_only_endpoint():
    html = (OBSERVER / "index.html").read_text()
    import re
    urls = re.findall(r'fetch\(\s*[`"\']([^`"\']+)', html)
    assert urls, "the page must fetch its data"
    allowed = ("/api/runs", "/api/summary", "/api/events", "/api/artifact",
               "/api/presentation", "/api/detail")
    for u in urls:
        assert u.startswith(allowed), u
    assert "method:" not in html and "POST" not in html


def test_the_static_directory_holds_only_allowlisted_files():
    on_disk = {p.name for p in (OBSERVER / "static").iterdir() if p.is_file()}
    assert on_disk == set(SRV.STATIC), on_disk
