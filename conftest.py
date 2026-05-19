import sys
from pathlib import Path

# Make the project root importable as a package root so that
# `from backend import ...` works the same way as with `python -m unittest`.
ROOT = Path(__file__).parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
