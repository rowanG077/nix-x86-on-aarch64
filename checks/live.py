"""Integration tests against real x86 binaries, pipes, terminals and the kernel."""

import argparse
import concurrent.futures
import fcntl
import json
import os
import pty
import select
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def check_process(command, **kwargs):
    result = subprocess.run(command, capture_output=True, timeout=60, **kwargs)
    assert result.returncode == 0, (command, result.returncode, result.stderr)
    return result


def wait_for_file(path, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists() and "0::" in path.read_text():
            return path.read_text().splitlines()
        time.sleep(0.02)
    raise AssertionError(("marker was not written", path))


def retired_request(fixtures, marker):
    membership = next(line[3:] for line in marker if line.startswith("0::"))
    assert membership.startswith("/muvm-requests/"), membership
    check_process(
        [
            fixtures["runtime"],
            "shell",
            "-c",
            'for ((i=0; i<500; ++i)); do test ! -d "/sys/fs/cgroup$1" && exit 0; sleep 0.01; done; exit 1',
            "retired-request",
            membership,
        ]
    )


def execution(fixtures):
    runner = fixtures["runtime"]
    with tempfile.TemporaryDirectory(prefix="x86 test ' $ ") as cwd:
        for core in (fixtures["core64"], fixtures["core32"]):
            for size in (0, 8193, 2 * 1024 * 1024):
                payload = bytes(range(256)) * (size // 256) + bytes(range(size % 256))
                result = check_process([runner, "run", core + "/bin/cat"], input=payload)
                assert result.stdout == payload and not result.stderr, result.stderr
            file = Path(cwd) / "binary input"
            file.write_bytes(payload)
            with file.open("rb") as stream:
                result = check_process([runner, "run", core + "/bin/cat"], stdin=stream)
                assert result.stdout == payload
            result = check_process([runner, "run", core + "/bin/true"], stdin=subprocess.DEVNULL)
            assert not result.stdout and not result.stderr
            result = check_process([runner, "run", core + "/bin/pwd"], cwd=cwd)
            assert result.stdout.decode().rstrip("\n") == cwd
            print("PASS", Path(core).name, "pipes, regular input, EOF, cwd", flush=True)
        value = "'\"\n$ ` EOM $(exit 91)"
        result = subprocess.run(
            [
                runner,
                "shell",
                "-c",
                'printf "%s\\0%s" "$1" "$CHECK_VALUE"; printf err >&2; exit 17',
                "test",
                value,
            ],
            env=os.environ | {"CHECK_VALUE": value},
            capture_output=True,
            timeout=60,
        )
        assert (result.stdout, result.stderr, result.returncode) == (
            value.encode() + b"\0" + value.encode(),
            b"err",
            17,
        ), result
        result = subprocess.run(
            [runner, "shell", "-c", 'kill -TERM "$$"'], capture_output=True, timeout=60
        )
        assert result.returncode == 143, result
        executable = Path(cwd) / "program=with spaces"
        executable.write_text("#!/bin/bash\nexit 17\n")
        executable.chmod(0o700)
        result = subprocess.run(
            [runner, "run", str(executable), "/bin/bash", "-c", "exit 29"],
            capture_output=True,
            timeout=60,
        )
        assert result.returncode == 17, result
        result = subprocess.run(
            [runner, "shell", "-c", '(sleep 0.2; printf "after parent exit") & exit 23'],
            capture_output=True,
            timeout=60,
        )
        assert (result.returncode, result.stdout, result.stderr) == (
            23,
            b"after parent exit",
            b"",
        ), result
        print("PASS quoting, environment, separate stderr, exit codes and signals", flush=True)

        def job(index):
            result = check_process(
                [runner, "run", fixtures["core64"] + "/bin/printf", "%s", str(index)]
            )
            assert result.stdout == str(index).encode() and not result.stderr, result

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(job, range(24)))
        print("PASS 24 commands across eight concurrent clients", flush=True)


def cancellation(fixtures):
    runner = fixtures["runtime"]
    if json.loads(check_process([runner, "doctor"]).stdout)["backend"] != "muvm":
        return

    def shared_server():
        result = check_process(
            [
                runner,
                "shell",
                "-c",
                """
found=0
for file in /proc/[0-9]*/comm; do
    if read -r name 2>/dev/null < "$file" && [ "$name" = FEXServer ]; then
        printf '%s ' "${file%/comm}"
        cat "${file%/comm}/cgroup"
        found=1
    fi
done
test "$found" = 1
""",
            ]
        )
        assert b"/muvm-requests/" not in result.stdout, "shared FEXServer belongs to an application"
        return result.stdout

    def worker_threads():
        result = check_process(
            [
                runner,
                "shell",
                "-c",
                """
for file in /proc/[0-9]*/comm; do
    if read -r name 2>/dev/null < "$file" && [ "$name" = muvm-guest ]; then
        set -- "${file%/comm}"/task/*
        printf '%s %s\n' "${file%/comm}" "$#"
    fi
done
""",
            ]
        )
        counts = dict(line.split() for line in result.stdout.splitlines())
        assert counts, "muvm worker not found"
        return {pid: int(count) for pid, count in counts.items()}

    before = worker_threads()
    server_before = shared_server()
    with tempfile.TemporaryDirectory(prefix="x86 cancellation ") as directory:
        root = Path(directory)
        source = root / "stdin"
        source.write_bytes(b"x" * (4 * 1024 * 1024))
        for target, sig, parent_exits in (
            ("launcher", signal.SIGTERM, False),
            ("group", signal.SIGTERM, False),
            ("group", signal.SIGKILL, False),
            ("launcher", signal.SIGTERM, True),
            ("group", signal.SIGTERM, True),
            ("group", signal.SIGKILL, True),
        ):
            case = root / f"{target}-{sig.name}-{parent_exits}"
            case.mkdir()
            ready = case / "ready"
            survived = case / "survived"
            script = 'trap "" TERM; (sleep 2; echo survived > "$2") & touch "$1"; wait'
            if parent_exits:
                script = """
parent=$$
trap "" TERM
(
    while read -r _ _ state _ < "/proc/$parent/stat" 2>/dev/null; do
        [ "$state" = Z ] && break
        sleep 0.01
    done
    touch "$1"
    sleep 2
    echo survived > "$2"
) &
exit 23
"""
            with source.open("rb") as stream:
                process = subprocess.Popen(
                    [
                        runner,
                        "shell",
                        "-c",
                        script,
                        "test",
                        str(ready),
                        str(survived),
                    ],
                    stdin=stream,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    start_new_session=True,
                )
                try:
                    deadline = time.monotonic() + 30
                    while (
                        not ready.exists()
                        and process.poll() is None
                        and time.monotonic() < deadline
                    ):
                        time.sleep(0.05)
                    assert ready.exists(), (
                        target,
                        sig,
                        process.poll(),
                        "guest command did not start",
                    )
                    if target == "group":
                        os.killpg(process.pid, sig)
                    else:
                        process.send_signal(sig)
                    process.wait(timeout=5)
                    time.sleep(2.5)
                    assert not survived.exists(), (
                        target,
                        sig,
                        parent_exits,
                        "guest survived cancellation",
                    )
                finally:
                    if process.poll() is None:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                    process.stderr.close()
        request_trees(fixtures, root, source)
        completion_acknowledgement(fixtures, root)
        assert shared_server() == server_before, "cancellation replaced the shared FEXServer"
        after = worker_threads()
        assert before.keys() == after.keys() and all(
            after[pid] <= count for pid, count in before.items()
        ), ("cancellation leaked VM worker threads", before, after)
        print(
            "PASS cancellation, cgroup retirement, completion acknowledgement and worker cleanup",
            flush=True,
        )


def request_trees(fixtures, root, source):
    runner = fixtures["runtime"]
    independent = subprocess.Popen(
        [runner, "shell", "-c", 'echo READY; read -r value; test "$value" = finish; echo SURVIVED'],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        assert select.select([independent.stdout], [], [], 30)[0], (
            "independent request did not start"
        )
        assert independent.stdout.readline() == b"READY\n"
        for abi in ("64", "32"):
            probe = fixtures["probes"] + "/bin/cancellation-probe-" + abi
            for mode in ("group", "session", "orphan", "late-fork", "blocked-output"):
                for target, sig in (("launcher", signal.SIGTERM), ("group", signal.SIGKILL)):
                    case = root / f"tree-{abi}-{mode}-{target}"
                    case.mkdir()
                    with source.open("rb") as stream:
                        process = subprocess.Popen(
                            [runner, "run", probe, mode, str(case)],
                            stdin=stream,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            start_new_session=True,
                        )
                        try:
                            leader = wait_for_file(case / "leader")
                            worker = wait_for_file(case / "ready")
                            assert leader[1:] == worker[1:], (leader, worker)
                            if mode in ("group", "session", "orphan"):
                                assert leader[0].split()[1] != worker[0].split()[1], (
                                    leader,
                                    worker,
                                )
                            if mode in ("session", "orphan"):
                                assert leader[0].split()[2] != worker[0].split()[2], (
                                    leader,
                                    worker,
                                )
                            if mode == "blocked-output":
                                time.sleep(0.2)
                            if target == "group":
                                os.killpg(process.pid, sig)
                            else:
                                process.send_signal(sig)
                            process.wait(timeout=5)
                            if mode == "late-fork":
                                late = wait_for_file(case / "late-fork")
                                assert late[1:] == leader[1:], (late, leader)
                            retired_request(fixtures, worker)
                            assert not (case / "survived").exists(), (abi, mode, target)
                            assert independent.poll() is None, "cancellation killed another request"
                        finally:
                            if process.poll() is None:
                                os.killpg(process.pid, signal.SIGKILL)
                                process.wait()
                            process.stdout.close()
                            process.stderr.close()
            print(
                "PASS",
                abi,
                "bit job groups, setsid, double forks, late forks and blocked output",
                flush=True,
            )
        output, errors = independent.communicate(b"finish\n", timeout=10)
        assert (independent.returncode, output, errors) == (0, b"SURVIVED\n", b""), (output, errors)
    finally:
        if independent.poll() is None:
            os.killpg(independent.pid, signal.SIGKILL)
            independent.wait()
        for stream in (independent.stdin, independent.stdout, independent.stderr):
            stream.close()


def completion_acknowledgement(fixtures, root):
    """Make the disconnect/normal-exit boundary deterministic with a protocol peer."""
    report = json.loads(check_process([fixtures["runtime"], "doctor"]).stdout)
    identity = report["service"].removeprefix("x86-on-arm-").removesuffix(".service")
    directory = Path(os.environ["XDG_RUNTIME_DIR"]) / "x86-on-arm" / identity / "krun"

    def receive(stream, size):
        data = bytearray()
        while len(data) < size:
            chunk = stream.recv(size - len(data))
            assert chunk, ("unexpected transport EOF", data)
            data.extend(chunk)
        return bytes(data)

    for port in range(50199, 49999, -1):
        lock = (directory / f"socket/port-{port}.lock").open("a")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            lock.close()
    else:
        raise AssertionError("no free test transport port")
    path = directory / f"socket/port-{port}"
    with lock:
        try:
            for acknowledge in (False, True):
                case = root / f"completion-ack-{acknowledge}"
                case.mkdir()
                path.unlink(missing_ok=True)
                with (
                    socket.socket(socket.AF_UNIX) as listener,
                    socket.socket(socket.AF_UNIX) as control,
                ):
                    listener.settimeout(15)
                    listener.bind(str(path))
                    listener.listen()
                    control.settimeout(15)
                    control.connect(str(directory / "server"))
                    request = {
                        "command": fixtures["probes"] + "/bin/cancellation-probe-native",
                        "command_args": ["closed-output", str(case)],
                        "env": {},
                        "vsock_port": port,
                        "tty": False,
                        "privileged": False,
                    }
                    control.sendall(json.dumps(request).encode() + b"\nEOM\n")
                    assert receive(control, 3) == b"OK\n"
                    stream, _ = listener.accept()
                    with stream:
                        stream.settimeout(15)
                        stream.sendall(b"\0\0")  # Stdin EOF.
                        while True:
                            packet = int.from_bytes(receive(stream, 2), "little")
                            opcode, size = packet & 3, packet >> 2
                            if opcode == 2:
                                assert size == 23, size
                                break
                            assert opcode in (0, 1), opcode
                            receive(stream, size)
                        worker = wait_for_file(case / "ready")
                        if acknowledge:
                            control.sendall(b"\1")
                if acknowledge:
                    wait_for_file(case / "survived")
                retired_request(fixtures, worker)
                assert (case / "survived").exists() == acknowledge, (acknowledge, worker)
        finally:
            path.unlink(missing_ok=True)
    print("PASS disconnect after CMD_EXIT and normal detached-child completion", flush=True)


def terminal(fixtures):
    pid, fd = pty.fork()
    if pid == 0:
        os.execv(
            fixtures["runtime"],
            [
                fixtures["runtime"],
                "shell",
                "-c",
                "test -t 0 && test -t 1 && test -t 2 || exit 19; echo TERMINAL_READY; exec sleep 60",
            ],
        )
    output = bytearray()
    deadline = time.monotonic() + 30
    try:
        while b"TERMINAL_READY\r\n" not in output and time.monotonic() < deadline:
            if select.select([fd], [], [], 0.2)[0]:
                output.extend(os.read(fd, 4096))
        assert b"TERMINAL_READY\r\n" in output, output
        os.write(fd, b"\x03")
        while time.monotonic() < deadline:
            child, status = os.waitpid(pid, os.WNOHANG)
            if child:
                assert os.waitstatus_to_exitcode(status) == 130, (status, output)
                print("PASS terminal detection and Ctrl-C", flush=True)
                return
            time.sleep(0.1)
        raise AssertionError("terminal did not exit after Ctrl-C")
    finally:
        os.close(fd)


def binfmt(fixtures, stage):
    if stage == "outer":
        with tempfile.TemporaryDirectory(prefix="x86-on-arm-binfmt-") as directory:
            subprocess.run(["mount", "-t", "binfmt_misc", "binfmt_misc", directory], check=True)
            try:
                for name, rule in json.loads(Path(fixtures["rules"]).read_text()).items():
                    registration = f":{name}:M::{rule['magicOrExtension']}:{rule['mask']}:{rule['interpreter']}:P"
                    (Path(directory) / "register").write_text(registration)
                subprocess.run(
                    [
                        "unshare",
                        "--user",
                        "--map-user=" + os.environ["CHECK_UID"],
                        "--map-group=" + os.environ["CHECK_GID"],
                        sys.executable,
                        __file__,
                        sys.argv[1],
                        "--namespace-stage",
                        "inner",
                    ],
                    check=True,
                )
            finally:
                subprocess.run(["umount", directory], check=True)
    elif stage == "inner":
        for core in (fixtures["core64"], fixtures["core32"]):
            payload = b"kernel dispatch\0binary\n" * 20000
            result = check_process([core + "/bin/cat"], input=payload)
            assert result.stdout == payload and not result.stderr, result
        result = check_process(
            ["original argv0", "--noprofile", "--norc", "-c", 'printf "%s" "$0"'],
            executable=fixtures["bash"] + "/bin/bash",
        )
        assert result.stdout == b"original argv0", result
        env = os.environ | {"NIX_PATH": fixtures["nixPath"]}
        result = check_process(["nix-shell", "-p", "x86pkgs.hello", "--run", "hello"], env=env)
        assert result.stdout == b"Hello, world!\n", result
        result = check_process(
            ["nix-shell", "-p", "x86pkgs.wineWow64Packages.stable", "--run", "wine --version"],
            env=env,
        )
        assert result.stdout.startswith(b"wine-"), result
        print(
            "PASS kernel ELF dispatch for both ABIs, original argv0, nix-shell hello and Wine",
            flush=True,
        )
    else:
        subprocess.run(
            [
                "unshare",
                "--user",
                "--map-root-user",
                "--mount",
                "--propagation",
                "private",
                sys.executable,
                __file__,
                sys.argv[1],
                "--namespace-stage",
                "outer",
            ],
            env=os.environ | {"CHECK_UID": str(os.getuid()), "CHECK_GID": str(os.getgid())},
            check=True,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixtures")
    parser.add_argument(
        "--graphics", action="store_true", help="also exercise GPU/audio and both ABIs' thunk APIs"
    )
    parser.add_argument(
        "--binfmt",
        action="store_true",
        help="also test real kernel dispatch in temporary user namespaces",
    )
    parser.add_argument("--namespace-stage", choices=("outer", "inner"), help=argparse.SUPPRESS)
    options = parser.parse_args()
    fixtures = json.loads(Path(options.fixtures).read_text())
    if options.namespace_stage:
        binfmt(fixtures, options.namespace_stage)
    else:
        execution(fixtures)
        cancellation(fixtures)
        terminal(fixtures)
        if options.graphics:
            check_process(
                [
                    fixtures["runtime"],
                    "shell",
                    "-c",
                    "dbus-send --session --print-reply --dest=org.freedesktop.DBus "
                    "/org/freedesktop/DBus org.freedesktop.DBus.ListNames >/dev/null; "
                    "if command -v wpctl >/dev/null; then timeout 15 wpctl status >/dev/null; fi",
                ]
            )
            print("PASS guest session bus and PipeWire query", flush=True)
            for abi in ("64", "32"):
                for arguments in ([], ["--nix-paths"]):
                    subprocess.run(
                        [
                            fixtures["runtime"],
                            "run",
                            fixtures["probes"] + "/bin/thunk-probe-" + abi,
                            *arguments,
                        ],
                        check=True,
                        timeout=180,
                    )
            check_process(
                [
                    fixtures["runtime"],
                    "run",
                    fixtures["vulkanTools"] + "/bin/vkcube",
                    "--wsi",
                    "xcb",
                    "--c",
                    "60",
                ]
            )
            print("PASS x86-64 vkcube function loading and 60 rendered frames", flush=True)
        if options.binfmt:
            subprocess.run(
                [
                    "unshare",
                    "--user",
                    "--map-root-user",
                    "--mount",
                    "--pid",
                    "--fork",
                    "--mount-proc",
                    "--propagation",
                    "private",
                    fixtures["nativeView"],
                ],
                check=True,
            )
            binfmt(fixtures, None)
