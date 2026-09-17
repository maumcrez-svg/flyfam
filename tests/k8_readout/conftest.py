"""Fixtures for the k = 8 readout wave.

The connectome fixtures are the Phase One ones, imported rather than copied so
that "the brain the tests run against" stays one fact in one place. pytest
already imports that module as ``phase_one.conftest``; this import binds the
same object.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from phase_one.conftest import (      # noqa: F401,E402
    REAL_DATA, ROOT, ann, brain, fresh_weights, graph_sha256, has_real_graph,
    requires_real_graph,
)
