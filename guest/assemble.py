"""Relocate a Nix closure without letting FEX or container realpath escape it."""

import os
import shutil
import sys
from pathlib import Path


def assemble(root, base, graphs):
    shutil.copytree(base, root, symlinks=True, dirs_exist_ok=True)
    root.chmod(root.stat().st_mode | 0o200)
    store = root / "nix/store"
    store.mkdir(parents=True, exist_ok=True)
    dependencies = {
        line
        for graph in graphs
        for line in graph.read_text().splitlines()
        if line.startswith("/nix/store/") and line != str(base)
    }
    for dependency in sorted(dependencies):
        source = Path(dependency)
        destination = store / source.name
        if source.is_dir():
            shutil.copytree(source, destination, symlinks=True)
        else:
            shutil.copy2(source, destination, follow_symlinks=False)
    # Do this after the whole closure is present: relative links remain valid
    # when PressureVessel binds the provider at a different path.
    for directory, dirs, files in os.walk(root):
        os.chmod(directory, os.stat(directory).st_mode | 0o200)
        for name in dirs + files:
            path = Path(directory) / name
            if path.is_symlink():
                target = os.readlink(path)
                if target.startswith("/nix/store/"):
                    path.unlink()
                    path.symlink_to(os.path.relpath(root / target[1:], path.parent))


if __name__ == "__main__":
    assemble(*map(Path, sys.argv[1:3]), list(map(Path, sys.argv[3:])))
