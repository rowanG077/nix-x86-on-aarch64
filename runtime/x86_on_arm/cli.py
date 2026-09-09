"""Public command interface. All application launchers use the same execution path."""

import argparse
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

from .environment import backend_for, graphics, guest_environment, native_environment, x11_socket
from .execution import command_script, private_script, resolve_program, run_process
from .vm import VirtualMachine


def execute(settings, config_path, command, arguments, source):
    backend = backend_for(settings["backend"], os.sysconf("SC_PAGESIZE"))
    if command == "shell":
        program, argv0 = "/bin/bash", "bash"
    elif command == "binfmt":
        if len(arguments) < 2:
            raise RuntimeError("binfmt requires an executable and original argv[0] (the P flag)")
        program, argv0, *arguments = arguments
        program = os.path.abspath(program)
    else:
        if not arguments:
            raise RuntimeError("usage: x86-arm run PROGRAM [ARG...]")
        argv0, *arguments = arguments
        program = resolve_program(argv0, settings["rootfs"])
    env = guest_environment(settings, source, backend)
    env.setdefault("FEX_APP_CONFIG", settings["nativeConfig"])
    _, _, native = graphics(settings, backend=backend)
    if "VK_DRIVER_FILES" in native and "VK_DRIVER_FILES" not in settings["nativeEnvironment"]:
        env.setdefault("FEX_HOSTENV", "VK_DRIVER_FILES=" + native["VK_DRIVER_FILES"])
    launch_env = native_environment(source)
    controls = {key: value for key, value in env.items() if key.startswith("FEX_")}
    launch_env.update(controls)
    vm = None
    if backend == "muvm":
        for key in ("MESA_LOADER_DRIVER_OVERRIDE", "LIBGL_ALWAYS_SOFTWARE", "GALLIUM_DRIVER"):
            if key in env:
                controls[key] = env[key]
        vm = VirtualMachine(settings, config_path, source)
        vm.ensure()
        launch_env = vm.host_environment() | controls
    script = command_script(program, argv0, arguments, env, os.getcwd(), vm is not None)
    with private_script(script) as path:
        invocation = [settings["fex"], str(path)]
        if vm:
            invocation = [settings["muvm"], "--interactive"]
            if all(os.isatty(fd) for fd in (0, 1, 2)):
                invocation.append("--tty")
            for key, value in controls.items():
                invocation += ["-e", key + "=" + value]
            invocation += ["--", settings["fex"], str(path)]
        return run_process(invocation, launch_env)


def main(config_path, argv=None):
    parser = argparse.ArgumentParser(
        prog="x86-arm", description="Run x86 Linux applications on ARM64."
    )
    parser.add_argument("--backend", choices=("auto", "fex", "muvm"))
    parser.add_argument(
        "command", nargs="?", default="doctor", choices=("run", "shell", "doctor", "stop", "binfmt")
    )
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    options = parser.parse_args(argv)
    try:
        settings = json.loads(Path(config_path).read_text())
        if settings["schema"] != 1:
            raise RuntimeError("unsupported configuration schema")
        if options.backend:
            settings["backend"] = options.backend
        source = dict(os.environ)
        if options.command == "doctor":
            backend = backend_for(settings["backend"], os.sysconf("SC_PAGESIZE"))
            mode, _, _ = graphics(settings, backend=backend)
            report = {
                "host": platform.machine(),
                "pageSize": os.sysconf("SC_PAGESIZE"),
                "backend": backend,
                "gpuMode": mode,
                "rootfs": settings["rootfs"],
                "versions": settings["versions"],
                "forwarding": ["GL", "EGL", "Vulkan", "drm", "asound", "WaylandClient"],
            }
            if backend == "muvm":
                vm = VirtualMachine(settings, config_path, source)
                report.update(
                    kvmAccess=os.access("/dev/kvm", os.R_OK | os.W_OK),
                    service=vm.unit,
                    running=vm.ready(),
                    x11Socket=x11_socket(source),
                )
            print(json.dumps(report, indent=2))
            return 0
        if os.getuid() == 0 or os.geteuid() == 0:
            raise RuntimeError("run as a regular user; this runtime is for applications")
        if options.command == "stop":
            return VirtualMachine(settings, config_path, source).stop()
        return execute(settings, config_path, options.command, options.arguments, source)
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as error:
        print(f"x86-arm: {error}", file=sys.stderr)
        return 126
    except KeyboardInterrupt:
        return 130
