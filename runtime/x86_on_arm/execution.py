"""Transport a command without reinterpreting its arguments or exposing secrets."""

import os
import shlex
import shutil
import signal
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path


def resolve_program(program, rootfs):
    if "/" in program:
        result = os.path.abspath(program)
        if not os.path.exists(result) and not (Path(rootfs) / result[1:]).exists():
            raise RuntimeError(f"executable does not exist: {program}")
        return result
    for directory in os.get_exec_path():
        found = shutil.which(program, path=directory or os.curdir)
        if not found:
            continue
        with open(found, "rb") as executable:
            header = executable.read(20)
        if (
            header.startswith(b"#!")
            or header[:4] == b"\x7fELF"
            and int.from_bytes(header[18:20], "little") in (3, 62)
        ):
            return os.path.abspath(found)
    for directory in ("usr/bin", "bin", "usr/sbin"):
        if (Path(rootfs) / directory / program).exists():
            return f"/{directory}/{program}"
    raise RuntimeError(f"x86 executable not found: {program}")


def command_script(program, argv0, arguments, environment, cwd, bridge):
    command = ["/usr/bin/env", "-i", "--"]
    inherited = ""
    if bridge:
        inherited = " ".join(
            f'"{key}=${{{key}-}}"'
            for key in (
                "DISPLAY",
                "XAUTHORITY",
                "XDG_RUNTIME_DIR",
                "GTK_IM_MODULE",
                "QT_IM_MODULE",
                "XRE_PROFILE_PATH",
                "MESA_LOADER_DRIVER_OVERRIDE",
            )
        )
    assignments = [f"{key}={value}" for key, value in environment.items()]
    target = [
        "/bin/bash",
        "--noprofile",
        "--norc",
        "-c",
        'exec -a "$1" -- "${@:2}"',
        "x86-arm-exec",
        argv0,
    ]
    return (
        "set -eu\ncd -- "
        + shlex.quote(cwd)
        + "\nexec "
        + shlex.join(command)
        + " "
        + inherited
        + " "
        + shlex.join([*assignments, *target, program, *arguments])
        + "\n"
    )


@contextmanager
def private_script(contents):
    with tempfile.TemporaryDirectory(prefix="x86-on-arm-", dir="/tmp") as directory:
        path = Path(directory) / "command.sh"
        with open(
            path,
            "w",
            encoding="utf-8",
            errors="surrogateescape",
            opener=lambda name, flags: os.open(name, flags, 0o600),
        ) as stream:
            stream.write(contents)
        yield path


def run_process(command, environment):
    process = None
    pending = []

    def forward(signum, _frame):
        if process is None:
            pending.append(signum)
        else:
            process.send_signal(signum)

    signals = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGQUIT)
    handlers = {signum: signal.signal(signum, forward) for signum in signals}
    try:
        process = subprocess.Popen(command, env=environment)
        for signum in pending:
            process.send_signal(signum)
        status = process.wait()
        return status if status >= 0 else 128 - status
    finally:
        for signum, handler in handlers.items():
            signal.signal(signum, handler)
