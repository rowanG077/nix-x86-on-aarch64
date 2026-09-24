"""Check the native wrapper's protocol and, optionally, real container mounts."""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

PROVIDERS = (
    "/var/pressure-vessel/gfx/main",
    "/run/pressure-vessel/interpreter-root/var/pressure-vessel/gfx/main",
)
INTERPRETER = "/run/pressure-vessel/interpreter-root"


def record():
    args = sys.argv[2:]
    packed = []
    while args[:1] == ["--args"]:
        with os.fdopen(int(args[1]), "rb") as stream:
            packed.append(stream.read().decode())
        args = args[2:]
    print(json.dumps({"args": args, "packed": packed, "path": os.environ["PATH"]}))


def invoke(helper, root, packets, payload):
    from contextlib import ExitStack

    with ExitStack() as stack:
        files = [stack.enter_context(tempfile.TemporaryFile()) for _ in packets]
        args = []
        for file, packet in zip(files, packets, strict=True):
            file.write(packet.encode())
            file.seek(0)
            args += ["--args", str(file.fileno())]
        env = os.environ | {"PATH": "/original path"}
        env.pop("FEX_ROOTFS", None)
        if root is not None:
            env["FEX_ROOTFS"] = str(root)
        return subprocess.run(
            [helper, *args, *payload],
            env=env,
            pass_fds=tuple(file.fileno() for file in files),
            capture_output=True,
            text=True,
            timeout=15,
        )


def protocol(helper):
    with tempfile.TemporaryDirectory(prefix="provider ' with spaces ") as directory:
        root = Path(directory)
        (root / "nix").mkdir()
        (root / "run").mkdir()
        payload = ["--", "/payload", "", "--args", "not a descriptor", "x y", "line\nbreak"]
        for packets in (["--dir\0/run\0"], ["--dir\0/run\0", "--setenv\0VALUE\0a b\0"]):
            result = invoke(helper, root, packets, payload)
            assert result.returncode == 0, result.stderr
            recorded = json.loads(result.stdout)
            assert recorded["packed"] == packets, recorded
            assert recorded["path"] == "/original path", recorded
            args = recorded["args"]
            assert args[-len(payload) :] == payload, args
            mounts = args[: -len(payload)]
            assert len(mounts) % 3 == 0, mounts
            bindings = {}
            for index in range(0, len(mounts), 3):
                option, source, dest = mounts[index : index + 3]
                assert option == "--ro-bind", mounts
                assert dest not in bindings, mounts
                bindings[dest] = source
            if Path("/run/opengl-driver").is_dir():
                assert bindings["/run/opengl-driver"] == "/run/opengl-driver", bindings
            assert "/run/opengl-driver-32" not in bindings, bindings
            assert bindings[INTERPRETER + "/nix"] == str(root / "nix"), bindings
            for provider in PROVIDERS:
                for subdir in ("nix", "run"):
                    assert bindings[provider + "/" + subdir] == str(root / subdir), bindings
            if Path("/nix").is_dir():
                assert bindings["/nix"] == "/nix", bindings

        # Bubblewrap's feature probes must work before FEX_ROOTFS is available.
        probe = ["--ro-bind", "/", "/", "--", "/bin/true"]
        result = invoke(helper, None, [], probe)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["args"] == probe, result.stdout
        assert json.loads(result.stdout)["path"].endswith(":/original path"), result.stdout
        for invalid in (None, "", "relative/root", root / "missing"):
            result = invoke(helper, invalid, ["--dir\0/run\0"], payload)
            assert result.returncode != 0 and "FEX" in result.stderr, result
        (root / "run").rmdir()
        result = invoke(helper, root, ["--dir\0/run\0"], payload)
        assert result.returncode != 0 and "rootfs directory" in result.stderr, result
    print(
        "PressureVessel: packed FDs, payload preservation, provider mounts and diagnostics passed"
    )


def containers(helper, bubblewrap):
    with tempfile.TemporaryDirectory(prefix="pressure-vessel ' ") as directory:
        fixture = Path(directory)
        native = fixture / "native"
        native.mkdir()
        (native / "architecture").write_text("native")
        guest = fixture / "guest"
        for driver, abi in (("opengl-driver", "x86_64"), ("opengl-driver-32", "i386")):
            mesa = guest / "nix/store" / abi
            (mesa / "share/drirc.d").mkdir(parents=True)
            (mesa / "architecture").write_text(abi)
            (mesa / "share/drirc.d/fixture.conf").write_text(abi)
            alias = guest / "run" / driver
            alias.mkdir(parents=True)
            for entry in ("architecture", "share"):
                (alias / entry).symlink_to(f"../../nix/store/{abi}/{entry}")

        # Create the --args FD inside the outer namespace, since bwrap closes
        # unrelated FDs. No host /run paths or store files are modified.
        launch = """
import json, os, sys
fd = os.memfd_create("pressure-vessel-args", 0)
os.write(fd, b"\\0".join(os.fsencode(a) for a in json.loads(sys.argv[2])) + b"\\0")
os.lseek(fd, 0, 0)
os.execv(sys.argv[1], [sys.argv[1], "--args", str(fd), "--", *sys.argv[3:]])
"""
        inspect = f"""
from pathlib import Path
assert Path('/run/opengl-driver/architecture').read_text() == 'native'
for prefix in {(*PROVIDERS, INTERPRETER)!r}:
    for driver, abi in (('opengl-driver', 'x86_64'), ('opengl-driver-32', 'i386')):
        path = Path(prefix) / 'run' / driver
        assert (path / 'architecture').read_text() == abi, path
        assert (path / 'share/drirc.d/fixture.conf').read_text() == abi, path
"""
        for layout in ("symlink", "directory"):
            packed = [
                "--ro-bind",
                "/fixtures",
                "/fixtures",
                # Simulate an export that must be restored to the native store.
                "--ro-bind",
                "/fixtures/guest/nix",
                "/nix",
                "--ro-bind",
                "/fixtures/guest/run",
                INTERPRETER + "/run",
                # /run is shared with the emulator. PressureVessel exports
                # the guest driver here; the helper must restore native DSOs.
                "--ro-bind",
                "/fixtures/guest/run/opengl-driver",
                "/run/opengl-driver",
            ]
            if layout == "symlink":
                native_export = ["--symlink", "/fixtures/native", "/run/opengl-driver"]
            else:
                native_export = ["--ro-bind", str(native), "/run/opengl-driver"]
            result = subprocess.run(
                [
                    bubblewrap,
                    "--ro-bind",
                    "/nix",
                    "/nix",
                    "--ro-bind",
                    str(fixture),
                    "/fixtures",
                    "--ro-bind",
                    helper,
                    helper,
                    *native_export,
                    "--dir",
                    "/etc/alsa",
                    "--dir",
                    "/tmp",
                    "--proc",
                    "/proc",
                    "--dev",
                    "/dev",
                    "--setenv",
                    "FEX_ROOTFS",
                    "/fixtures/guest",
                    "--chdir",
                    "/",
                    "--",
                    sys.executable,
                    "-c",
                    launch,
                    helper,
                    json.dumps(packed),
                    sys.executable,
                    "-c",
                    inspect,
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert result.returncode == 0, (layout, result.stderr)
    print(
        "PressureVessel: native symlink/directory drivers, native store and both x86 providers passed"
    )


if __name__ == "__main__":
    if sys.argv[1:2] == ["--record"]:
        record()
    else:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("helper")
        parser.add_argument("--bubblewrap")
        args = parser.parse_args()
        if args.bubblewrap:
            containers(args.helper, args.bubblewrap)
        else:
            protocol(args.helper)
