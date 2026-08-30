"""Makes `pytest -q` work on a clean checkout without installing the package.

Round-1 audit finding D10: the canonical command in the README failed on a bare
clone because `roadstar` was not importable. Prepending the repository root is
the smallest fix that keeps the documented command honest.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
