"""Import the installed wheel independently of a source checkout or OrcaCast."""

from __future__ import annotations

import importlib
import importlib.abc
import pkgutil
import sys
from pathlib import Path


class BlockApplication(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "orcacast" or fullname.startswith("orcacast."):
            raise ImportError(f"Unexpected application dependency: {fullname}")
        return None


sys.meta_path.insert(0, BlockApplication())
import seascape

location = Path(seascape.__file__).resolve()
if "site-packages" not in location.parts:
    raise RuntimeError(f"Expected an installed wheel, imported: {location}")
count = 1
for module in pkgutil.walk_packages(seascape.__path__, seascape.__name__ + "."):
    importlib.import_module(module.name)
    count += 1
print(f"Imported {count} installed modules with OrcaCast blocked: {location}")
