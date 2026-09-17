"""Path setup for the D12 tests. ``upstream/`` and D11 are imported read-only.

The order matters: ``experiments/d12`` comes **before** ``experiments/d11``,
because both directories hold an ``evaluate.py`` and the D12 tests mean D12's.
Nothing in D12 is named ``common``, ``stats``, ``retrospective`` or ``grid``,
which are the four D11 modules D12 imports unchanged.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

for p in (str(ROOT), str(ROOT / "upstream"), str(ROOT / "experiments" / "d11"),
          str(ROOT / "experiments" / "d12")):
    while p in sys.path:
        sys.path.remove(p)
    sys.path.insert(0, p)
