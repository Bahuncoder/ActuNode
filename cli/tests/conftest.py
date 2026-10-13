import sys
from pathlib import Path

# The tests import their helpers (fakes.py) and the package from cli/, wherever pytest is started.
sys.path[:0] = [str(Path(__file__).parent), str(Path(__file__).parents[1])]
