"""Start Cliq: ``python run.py`` (same as ``python -m cliq``)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cliq.__main__ import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
