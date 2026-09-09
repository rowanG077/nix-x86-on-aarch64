"""Require every supplied thunk to keep its ABI and native runtime dependencies."""

import os
import re
import subprocess
import sys
from pathlib import Path

fex, headers = map(Path, sys.argv[1:])


def output(*arguments):
    return subprocess.check_output(arguments, text=True)


def symbols(path):
    return {
        line.split()[7]
        for line in output("readelf", "--dyn-syms", "--wide", str(path)).splitlines()
        if len(line.split()) >= 8 and line.split()[0].endswith(":") and line.split()[6] != "UND"
    }


libraries = {"GL": "1", "EGL": "1", "vulkan": "1", "drm": "2", "asound": "2", "wayland-client": "0"}
for bits, suffix in ((64, ""), (32, "_32")):
    for name, version in libraries.items():
        if bits == 32 and name in ("vulkan", "drm", "asound"):
            continue  # FEX 2609 has no i386 implementation for these three.
        host = fex / f"lib/fex-emu/HostThunks{suffix}/lib{name}-host.so"
        guest = fex / f"share/fex-emu/GuestThunks{suffix}/lib{name}-guest.so"
        assert "AArch64" in output("readelf", "-h", str(host))
        assert ("X86-64" if bits == 64 else "80386") in output("readelf", "-h", str(guest))
        needed = output("patchelf", "--print-needed", str(guest)).splitlines()
        assert all(lib in needed for lib in ("libstdc++.so.6", "libgcc_s.so.1", "libc.so.6")), guest
        dynamic = output("readelf", "-d", str(guest))
        assert "NODELETE" in dynamic and "FINI_ARRAY" in dynamic, guest
        exported = symbols(guest)
        if name in ("GL", "EGL"):
            filenames = ["EGL/egl.h"] if name == "EGL" else ["GL/gl.h", "GL/glx.h", "GLES3/gl32.h"]
            for filename in filenames:
                expected = set(
                    re.findall(r"\b((?:egl|gl)[A-Z]\w*)\s*\(", (headers / filename).read_text())
                )
                assert len(expected) > 40, filename
                assert expected <= exported, (bits, filename, sorted(expected - exported))
        if name == "asound":
            assert {
                "snd_mixer_elem_set_callback",
                "snd_mixer_elem_set_callback_private",
                "snd_mixer_elem_new",
                "snd_mixer_class_set_compare",
            } <= exported
        if name == "wayland-client":
            native = symbols(Path(os.environ["WAYLAND"]) / "lib/libwayland-client.so.0")
            required = {
                value
                for value in native
                if value.startswith("wl_") and value.endswith("_interface")
            }
            assert len(required) >= 23 and required <= exported, required - exported
        rpath = output("patchelf", "--print-rpath", str(host)).strip()
        subprocess.run(["patchelf", "--set-rpath", rpath, "./load"], check=True)
        subprocess.run(["./load", f"lib{name}.so.{version}"], check=True)
print("Forwarding: native dlopen dependencies, x86 ABI, constructors and public APIs passed")
