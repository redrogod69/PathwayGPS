"""Test configuration: deterministic offline replay of recorded source responses.

`tests/fixtures/replay` holds real API responses recorded from the live sources on
2026-10-17 (see docs/RESEARCH_NOTES.md). Tests run with PATHWAYGPS_OFFLINE=1, so no
network access happens and results do not drift with database releases. Tests assert
structural invariants and identifiers rather than exact record counts.
"""

import os
import sys
import tempfile
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ["PATHWAYGPS_OFFLINE"] = "1"
os.environ["PATHWAYGPS_CACHE_DIR"] = str(BACKEND_ROOT / "tests" / "fixtures" / "replay")
os.environ["PATHWAYGPS_SNAPSHOT_DIR"] = tempfile.mkdtemp(prefix="pathwaygps-snapshots-")
os.environ["ANTHROPIC_API_KEY"] = ""
