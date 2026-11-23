"""Import the modules of `analysis/`, which import each other by their bare names since they run as scripts."""

import importlib
import sys
from pathlib import Path
from types import ModuleType

ANALYSIS_DIR = Path(__file__).parents[2] / "analysis"


def analysis_module(name: str) -> ModuleType:
    """Import the module `analysis/<name>.py` after putting its folder on `sys.path`, as each module does for the modules it imports."""
    if str(ANALYSIS_DIR) not in sys.path:
        sys.path.insert(0, str(ANALYSIS_DIR))
    return importlib.import_module(name)
