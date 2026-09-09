"""Extend upstream FHS thunk mappings to the guest libraries' Nix store paths."""

import json
from pathlib import Path
import sys

database_path, directories_path = map(Path, sys.argv[1:])
database = json.loads(database_path.read_text())
directories = json.loads(directories_path.read_text())
for name, paths in directories.items():
    entry = database["DB"][name]
    sonames = {
        path.removeprefix("@PREFIX_LIB@/")
        for path in entry["Overlay"]
        if path.startswith("@PREFIX_LIB@/")
    }
    # Upstream also lists historical full filenames. Discover the versions
    # actually shipped by this nixpkgs (for example Wayland .so.0.26.0).
    families = {name for name in sonames if name.endswith(".so")}
    for directory in paths:
        sonames.update(
            path.name
            for path in Path(directory).iterdir()
            if any(path.name == family or path.name.startswith(family + ".") for family in families)
        )
    entry["Overlay"].extend(
        f"@PREFIX_LIB@/{soname}"
        for soname in sorted(sonames)
        if f"@PREFIX_LIB@/{soname}" not in entry["Overlay"]
    )
    entry["Overlay"].extend(
        f"{directory}/{soname}"
        for directory in sorted(paths)
        for soname in sorted(sonames)
    )
    # nixpkgs' multilib FHS view also exposes the i386 libraries at lib32.
    # Cache entries and explicit dlopen paths must hit the same guest thunk.
    entry["Overlay"].extend(
        f"{directory}/{soname}"
        for directory in ("/usr/lib32", "/lib32")
        for soname in sorted(sonames)
    )
database_path.write_text(json.dumps(database, indent=2) + "\n")
