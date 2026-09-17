"""Operation: four verbs, a user unit, no sudo, no linger. P1 addendum 5."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "the live-loop launcher"
UNIT = ROOT / "product" / "the-pons-user-unit"
INSTALLED = Path.home() / ".config" / "systemd" / "user" / "the-pons-user-unit"


def test_the_script_has_the_four_verbs():
    assert SCRIPT.exists() and os.access(SCRIPT, os.X_OK)
    text = SCRIPT.read_text()
    for verb in ("start", "stop", "status", "tail"):
        assert re.search(rf"^\s+{verb}\)", text, re.M), verb
    out = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True,
                         text=True)
    assert out.returncode == 0, out.stderr
    usage = subprocess.run([str(SCRIPT)], capture_output=True, text=True)
    assert usage.returncode == 2
    assert "start|stop|status|tail" in usage.stdout


def test_the_script_and_the_unit_name_no_sudo_and_no_linger():
    for path in (SCRIPT, UNIT):
        text = path.read_text()
        assert "sudo" not in text.replace("no sudo", "").replace("No sudo", "")
        assert "enable-linger" not in text.replace(
            "`loginctl enable-linger`", "").replace("loginctl enable-linger", "")
        assert "the system service" not in text
        assert "/etc/systemd" not in text


def test_the_unit_is_a_user_unit_with_restart_and_an_environment_file():
    text = UNIT.read_text()
    assert "Restart=on-failure" in text
    assert re.search(r"^RestartSec=\d+", text, re.M)
    assert "EnvironmentFile=.env" in text
    assert "KillSignal=SIGTERM" in text
    assert re.search(r"^TimeoutStopSec=\d+", text, re.M)
    assert "ExecStart=" in text and "product/run.py" in text
    # a user unit names no User=, no Group= and no privileged directive
    for forbidden in ("User=", "Group=", "AmbientCapabilities",
                      "PrivateDevices", "CapabilityBoundingSet"):
        assert forbidden not in text
    assert "WantedBy=default.target" in text


def test_the_unit_reads_the_endpoint_by_key_name_and_never_echoes_it():
    text = UNIT.read_text()
    assert "CHAINSTACK_RPC_HTTPS_KEYED" in text          # the NAME is not a secret
    run = (ROOT / "product" / "run.py").read_text()
    # the value goes from the environment straight into the client and nowhere
    # else: no print, no log, no artifact
    assert "def endpoint_url" in run
    for line in run.splitlines():
        if "endpoint_url" in line and "def " not in line:
            assert "print" not in line and "log(" not in line


@pytest.mark.skipif(not INSTALLED.exists(),
                    reason="the unit is not installed on this machine")
def test_the_installed_unit_is_the_committed_one():
    assert INSTALLED.read_text() == UNIT.read_text()


def test_status_opens_no_socket(tmp_path):
    """``--status`` reads the state file. It never constructs a client."""
    import ast
    run = ast.parse((ROOT / "product" / "run.py").read_text())
    fn = next(n for n in run.body
              if isinstance(n, ast.FunctionDef) and n.name == "print_status")
    names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
    assert not names & {"RpcClient", "RetryingRpc", "read_endpoint",
                        "endpoint_url", "Collector"}
    env = {**os.environ, "CHAINSTACK_RPC_HTTPS_KEYED": ""}
    out = subprocess.run(
        [sys.executable, str(ROOT / "product" / "run.py"), "--status"],
        cwd=str(ROOT), capture_output=True, text=True, env=env, timeout=120)
    assert out.returncode == 0, out.stderr
    assert "PONS / LIVE / PAPER / FROZEN" in out.stdout


def test_the_script_refuses_a_second_worker(tmp_path):
    """One process owns the journal; a second would be a second fly."""
    text = SCRIPT.read_text()
    assert "already running" in text
    assert "one process owns this journal" in text
    run = (ROOT / "product" / "run.py").read_text()
    assert "a worker is already running" in run
