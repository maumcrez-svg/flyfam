"""Path setup for the D10 tests. ``upstream/`` is imported read-only."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UPSTREAM = ROOT / "upstream"

for p in (str(ROOT), str(UPSTREAM)):
    if p not in sys.path:
        sys.path.insert(0, p)
