"""Verify the installed image as a closed, relocatable multilib filesystem."""

import json
import sys
from collections import deque
from pathlib import Path

root = Path(sys.argv[1])


def resolve(path):
    parts = deque(Path(path).parts)
    result = root
    links = 0
    while parts:
        part = parts.popleft()
        if part == "/":
            result = root
        elif part == "..":
            assert result != root, path
            result = result.parent
        else:
            result /= part
            if result.is_symlink():
                links += 1
                assert links < 100, path
                parts.extendleft(reversed(result.readlink().parts))
                result = result.parent
    assert result.exists(), (path, result)
    assert result.is_relative_to(root), result
    return result


def machine(path):
    with resolve(path).open("rb") as stream:
        header = stream.read(20)
    return int.from_bytes(header[18:20], "little") if header[:4] == b"\x7fELF" else None


for path, abi in [
    ("/bin/sh", 62),
    ("/bin/python3", 62),
    ("/lib64/ld-linux-x86-64.so.2", 62),
    ("/lib/ld-linux.so.2", 3),
    ("/sbin/ldconfig", 62),
]:
    assert machine(path) == abi, path
for directory, abi in (("usr/lib64", 62), ("usr/lib32", 3)):
    count = 0
    for path in (root / directory).glob("*.so*"):
        value = machine("/" + str(path.relative_to(root)))
        if value:
            assert value == (3 if path.name == "ld-linux.so.2" else abi), (path, value)
            assert path.resolve().is_relative_to(root), path
            count += 1
    assert count > 100, (directory, count)
for manifest in (root / "usr/share/x86-on-arm/vulkan").glob("*.json"):
    expected = 62 if ".x86_64." in manifest.name else 3
    assert machine(json.loads(manifest.read_text())["ICD"]["library_path"]) == expected, manifest
assert resolve("/etc/ld.so.cache").read_bytes().startswith(b"glibc-ld.so.cache")
assert resolve("/etc/ssl/certs/ca-bundle.crt").stat().st_size > 100000
assert resolve("/sbin/ldconfig") == resolve("/usr/bin/ldconfig")
assert "libs.native" in resolve("/etc/alsa/conf.d/00-x86-on-arm.conf").read_text()
database = json.loads(Path(sys.argv[2]).read_text())["DB"]
directories = json.loads(sys.argv[3])
for name, paths in directories.items():
    overlays = set(database[name]["Overlay"])
    for directory in paths:
        mapped = {Path(path).name for path in overlays if path.startswith(directory + "/")}
        assert mapped, (name, directory)
        families = {name for name in mapped if name.endswith(".so")}
        for path in resolve(directory).iterdir():
            if any(path.name == stem or path.name.startswith(stem + ".") for stem in families):
                assert f"{directory}/{path.name}" in overlays, (name, path)
print("Image: both ABIs, libraries, all Mesa ICDs, certificates, cache and thunk paths passed")
