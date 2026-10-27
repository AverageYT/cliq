"""Start Cliq: ``python run.py`` (same as ``python -m cliq``)."""

import sys
from pathlib import Path

if sys.version_info < (3, 11):
    sys.exit(f"Cliq needs Python 3.11 or newer (this is {sys.version.split()[0]}).\n"
             "Install it from https://www.python.org/downloads/ (or `brew install python@3.12`),\n"
             "then create a fresh virtual environment with it - see README.md.")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cliq.__main__ import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
