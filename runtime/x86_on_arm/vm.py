"""One lazily started VM per immutable runtime, owned by the user's systemd."""

import fcntl
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from .environment import graphics, native_environment, x11_socket


class VirtualMachine:
    def __init__(self, settings, config_path, source):
        self.settings = settings
        self.config_path = config_path
        self.source = source
        runtime = source.get("XDG_RUNTIME_DIR")
        if not runtime:
            raise RuntimeError("muvm needs XDG_RUNTIME_DIR from a regular user session")
        identity = hashlib.sha256(
            os.fsencode(config_path) + Path(config_path).read_bytes()
        ).hexdigest()[:12]
        self.directory = Path(runtime) / "x86-on-arm" / identity
        self.unit = f"x86-on-arm-{identity}.service"
        self.socket = self.directory / "krun/server"

    def host_environment(self):
        env = native_environment(self.source)
        env["XDG_RUNTIME_DIR"] = str(self.directory)
        env.setdefault("RUST_LOG", "init_or_kernel=error")
        env.setdefault("PULSE_SERVER", "unix:" + self.source["XDG_RUNTIME_DIR"] + "/pulse/native")
        env.setdefault("PIPEWIRE_RUNTIME_DIR", self.source["XDG_RUNTIME_DIR"])
        display_socket = x11_socket(self.source)
        if display_socket:
            env["X11_SOCKET"] = display_socket
        return env

    def ready(self):
        request = (
            json.dumps(
                {
                    "command": self.settings["true"],
                    "command_args": [],
                    "env": {},
                    "vsock_port": 0,
                    "tty": False,
                    "privileged": False,
                }
            ).encode()
            + b"\nEOM\n"
        )
        try:
            with socket.socket(socket.AF_UNIX) as connection:
                connection.settimeout(0.5)
                connection.connect(str(self.socket))
                connection.sendall(request)
                return connection.recv(1024) == b"OK"
        except OSError:
            return False

    def ensure(self):
        if not os.access("/dev/kvm", os.R_OK | os.W_OK):
            raise RuntimeError("muvm needs access to /dev/kvm; grant this user KVM access")
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        with (self.directory / "startup.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if self.ready():
                return
            env = native_environment(self.source)
            subprocess.run(
                [self.settings["systemctl"], "--user", "reset-failed", self.unit],
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            command = [
                self.settings["systemdRun"],
                "--user",
                "--quiet",
                "--collect",
                "--unit=" + self.unit,
                "--property=Type=exec",
                "--property=TimeoutStopSec=10",
                "--property=PartOf=graphical-session.target",
                "--property=UnsetEnvironment=LD_LIBRARY_PATH LD_PRELOAD",
                "--property=KillMode=mixed",
                "--property=WorkingDirectory=" + str(Path.home()),
            ]
            for key in (
                "DISPLAY",
                "XAUTHORITY",
                "X11_SOCKET",
                "XDG_RUNTIME_DIR",
                "PULSE_SERVER",
                "PIPEWIRE_RUNTIME_DIR",
                "PIPEWIRE_REMOTE",
                "DBUS_SESSION_BUS_ADDRESS",
            ):
                if key in self.source:
                    command.append("--setenv=" + key + "=" + self.source[key])
            command += [
                sys.executable,
                str(Path(__file__).with_name("service.py")),
                self.config_path,
            ]
            subprocess.run(command, env=env, stdin=subprocess.DEVNULL, check=True)
            deadline = time.monotonic() + 45
            check_after = time.monotonic() + 1
            while time.monotonic() < deadline:
                if self.ready():
                    return
                if time.monotonic() >= check_after:
                    state = subprocess.run(
                        [self.settings["systemctl"], "--user", "is-active", "--quiet", self.unit],
                        env=env,
                        stdin=subprocess.DEVNULL,
                    )
                    if state.returncode:
                        raise RuntimeError(
                            f"VM exited during startup; inspect journalctl --user -u {self.unit}"
                        )
                    check_after = time.monotonic() + 1
                time.sleep(0.1)
            raise RuntimeError(f"VM did not start; inspect journalctl --user -u {self.unit}")

    def serve(self):
        mode, _, _ = graphics(self.settings, backend="muvm")
        command = [
            self.settings["muvm"],
            "--emu=fex",
            "--gpu-mode=" + mode,
            "--execute-pre",
            self.settings["prepareVM"],
            "--user-execute-pre",
            self.settings["prepareSession"],
            "-e",
            f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{os.getuid()}/bus",
        ]
        if self.settings["memoryMiB"]:
            command.append("--mem=" + str(self.settings["memoryMiB"]))
        command += ["--", self.settings["sleep"], "infinity"]
        host_env = self.host_environment()
        host_env.update(graphics(self.settings, backend="fex")[2])
        os.execve(command[0], command, host_env)

    def stop(self):
        return subprocess.run(
            [self.settings["systemctl"], "--user", "stop", self.unit],
            env=native_environment(self.source),
        ).returncode
