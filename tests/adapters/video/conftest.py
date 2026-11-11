"""The video adapter's tests import each other's helpers by module name, so this folder is on the
path.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
