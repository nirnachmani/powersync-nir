"""Provide real EV lock imports to tests executing extracted setup closures."""
from pathlib import Path
import sys
import types


def closure_package():
    """Use an isolated package alias without importing Home Assistant setup."""
    package = "_ev_lock_closure_test"
    root = Path(__file__).resolve().parents[1] / "custom_components" / "power_sync"
    for name, directory in ((package, root), (package + ".automations", root / "automations")):
        if name not in sys.modules:
            module = types.ModuleType(name)
            module.__path__ = [str(directory)]
            sys.modules[name] = module
    return package
