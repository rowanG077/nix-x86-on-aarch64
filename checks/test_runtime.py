"""Exercise observable contracts without KVM or privileged kernel registration."""

import json
import os
import shutil
import signal
import socket
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from x86_on_arm.environment import (
    backend_for,
    graphics,
    guest_environment,
    native_environment,
    x11_socket,
)
from x86_on_arm.execution import command_script, private_script, resolve_program
from x86_on_arm.vm import VirtualMachine


class ExecutionTests(unittest.TestCase):
    def host_script(self, script):
        return script.replace("/usr/bin/env", os.environ.get("TEST_ENV", "/usr/bin/env")).replace(
            " /bin/bash ", " " + os.environ.get("TEST_BASH", "/bin/bash") + " "
        )

    def test_arguments_environment_and_working_directory(self):
        with tempfile.TemporaryDirectory(prefix="cwd ' spaces ") as cwd:
            wanted = ["", "a b", "line\nbreak", "$(exit 92)", "'\";*?", "EOM"]
            code = "import json, os, sys; print(json.dumps([os.getcwd(), sys.argv[1:], os.environ['TOKEN']]))"
            env = {"TOKEN": "private\n'EOM'\n$(exit 91)", "PATH": os.environ["PATH"]}
            script = command_script(
                os.sys.executable, "python", ["-c", code, *wanted], env, cwd, False
            )
            # The test uses the host env utility; runtime uses the guest FHS one.
            script = self.host_script(script)
            with private_script(script) as path:
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
                output = subprocess.check_output([os.environ.get("TEST_BASH", "bash"), str(path)])
            self.assertFalse(path.exists())
            self.assertEqual(json.loads(output), [cwd, wanted, env["TOKEN"]])

    def test_binfmt_argv_zero_and_status(self):
        bash = os.environ.get("TEST_BASH", "bash")
        script = command_script(
            bash,
            "-custom shell",
            ["--noprofile", "--norc", "-c", 'printf "%s" "$0"; exit 17'],
            {"PATH": os.environ["PATH"]},
            os.getcwd(),
            False,
        )
        script = self.host_script(script)
        result = subprocess.run([bash, "-c", script], capture_output=True)
        self.assertEqual(result.returncode, 17)
        self.assertEqual(result.stdout, b"-custom shell")

    def test_equals_in_executable_path(self):
        bash = os.environ.get("TEST_BASH", "/bin/bash")
        with tempfile.TemporaryDirectory(prefix="program=with spaces ") as directory:
            executable = Path(directory) / "bash"
            executable.symlink_to(shutil.which(bash))
            script = command_script(
                str(executable),
                "original=argv0",
                ["-c", 'printf "%s" "$0"; exit 17'],
                {},
                directory,
                False,
            )
            result = subprocess.run([bash, "-c", self.host_script(script)], capture_output=True)
            self.assertEqual(result.returncode, 17, result.stderr)
            self.assertEqual(result.stdout, b"original=argv0")

    def test_path_search_skips_native_and_nonexecutable_candidates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, machine, mode in (
                ("native", 183, 0o755),
                ("disabled", 62, 0o644),
                ("x86", 62, 0o755),
            ):
                binary = root / name / "example"
                binary.parent.mkdir()
                header = bytearray(20)
                header[:4] = b"\x7fELF"
                header[18:20] = machine.to_bytes(2, "little")
                binary.write_bytes(header)
                binary.chmod(mode)
            with patch.dict(
                os.environ,
                {"PATH": os.pathsep.join(str(root / p) for p in ("native", "disabled", "x86"))},
            ):
                self.assertEqual(resolve_program("example", str(root)), str(root / "x86/example"))

    def test_signal_to_launcher_reaches_child_and_cleans_up(self):
        code = """
import os, signal, sys
from x86_on_arm.execution import private_script, run_process
with private_script("private") as path:
    print(path, flush=True)
    sys.exit(run_process([os.sys.executable, "-c", 'import signal; print("READY", flush=True); signal.pause()'], dict(os.environ)))
"""
        process = subprocess.Popen(
            [os.sys.executable, "-c", code], stdout=subprocess.PIPE, text=True
        )
        try:
            path = Path(process.stdout.readline().strip())
            self.assertEqual(process.stdout.readline().strip(), "READY")
            process.send_signal(signal.SIGTERM)
            process.wait(timeout=5)
            self.assertEqual(process.returncode, 143)
            self.assertFalse(path.parent.exists())
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            process.stdout.close()

    def test_private_file_cleanup_on_failure(self):
        with self.assertRaises(ValueError):
            with private_script("secret") as path:
                raise ValueError("failure")
        self.assertFalse(path.parent.exists())


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.settings = {
            "backend": "muvm",
            "allowSoftwareRendering": False,
            "rootfs": "/missing",
            "nativeVulkanDirectory": "/missing",
            "gpuMode": "auto",
            "thunkConfig": "/thunks",
            "environment": {},
        }

    def test_page_size_selects_transport(self):
        self.assertEqual(backend_for("auto", 4096), "fex")
        for size in (16384, 65536):
            self.assertEqual(backend_for("auto", size), "muvm")
            with self.assertRaises(RuntimeError):
                backend_for("fex", size)
        self.assertEqual(backend_for("muvm", 4096), "muvm")

    def test_gpu_policy_is_not_board_specific(self):
        for driver in ("asahi", "msm", "amdgpu"):
            self.assertEqual(graphics(self.settings, {driver})[0], "drm")
        with self.assertRaisesRegex(RuntimeError, "never selected automatically"):
            graphics(self.settings, {"panthor"})
        self.assertEqual(graphics(self.settings, {"panthor"}, backend="fex")[0], "native")
        self.settings["gpuMode"] = "venus"
        self.assertEqual(graphics(self.settings, {"panthor"})[0], "venus")

    def test_software_requires_both_gate_and_explicit_mode(self):
        self.settings["gpuMode"] = "software"
        with self.assertRaisesRegex(RuntimeError, "allowSoftwareRendering"):
            graphics(self.settings, {"asahi"})
        self.settings["allowSoftwareRendering"] = True
        self.assertEqual(graphics(self.settings, {"asahi"})[0], "software")
        self.settings["gpuMode"] = "auto"
        with self.assertRaisesRegex(RuntimeError, "never selected automatically"):
            graphics(self.settings, {"panthor"})

    def test_vm_icds_match_transport_even_with_populated_host_directory(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            nixos, packaged = root / "nixos", root / "packaged"
            guest = root / "usr/share/x86-on-arm/vulkan"
            for directory in (nixos, packaged, guest):
                directory.mkdir(parents=True)
            (nixos / "asahi_icd.aarch64.json").write_text("{}")
            for driver in ("asahi", "virtio", "lvp"):
                (packaged / f"{driver}_icd.aarch64.json").write_text("{}")
                for abi in ("x86_64", "i686"):
                    (guest / f"{driver}_icd.{abi}.json").write_text("{}")
            self.settings.update(rootfs=str(root), nativeVulkanDirectory=str(packaged))
            with patch("x86_on_arm.environment.NIXOS_VULKAN_DIRECTORY", nixos):
                for mode, driver in (("venus", "virtio"), ("software", "lvp"), ("drm", "asahi")):
                    self.settings.update(gpuMode=mode, allowSoftwareRendering=mode == "software")
                    _, icds, native = graphics(self.settings, {"asahi"})
                    self.assertEqual(
                        set(icds.split(":")),
                        {
                            f"/usr/share/x86-on-arm/vulkan/{driver}_icd.{abi}.json"
                            for abi in ("x86_64", "i686")
                        },
                    )
                    directory = nixos if mode == "drm" else packaged
                    self.assertEqual(
                        native, {"VK_DRIVER_FILES": str(directory / f"{driver}_icd.aarch64.json")}
                    )
                    with patch("x86_on_arm.environment.drm_drivers", return_value={"asahi"}):
                        env = guest_environment(self.settings, {}, "muvm")
                    if mode == "venus":
                        self.assertEqual(env["MESA_LOADER_DRIVER_OVERRIDE"], "zink")
                    if mode == "software":
                        self.assertEqual(env["LIBGL_ALWAYS_SOFTWARE"], "1")

                self.settings.update(allowSoftwareRendering=False, gpuMode="auto")
                _, guest_icds, native = graphics(self.settings, {"panthor"}, backend="fex")
                self.assertNotIn("lvp_icd", guest_icds)
                self.assertNotIn("lvp_icd", native["VK_DRIVER_FILES"])

    def test_loader_and_display_domains(self):
        source = {
            "DISPLAY": ":7",
            "LD_LIBRARY_PATH": "/arm/lib",
            "LD_PRELOAD": "/arm/hook.so",
            "VK_DRIVER_FILES": "/arm/icd.json",
            "TOKEN": "keep",
            "PATH": "/tools",
        }
        native = native_environment(source)
        self.assertNotIn("LD_LIBRARY_PATH", native)
        self.assertNotIn("VK_DRIVER_FILES", native)
        with patch("x86_on_arm.environment.graphics", return_value=("drm", "/guest/icd.json", {})):
            vm = guest_environment(self.settings, source, "muvm")
            direct = guest_environment(self.settings, source, "fex")
            self.assertNotIn("DISPLAY", vm)
            self.assertEqual(direct["DISPLAY"], ":7")
            self.assertEqual(vm["TOKEN"], "keep")
            self.assertEqual(vm["VK_DRIVER_FILES"], "/guest/icd.json")
            self.settings["environment"] = {"LD_LIBRARY_PATH": "/x86/lib"}
            self.assertEqual(
                guest_environment(self.settings, source, "muvm")["LD_LIBRARY_PATH"], "/x86/lib"
            )

    def test_native_vulkan_discovery_without_nixos(self):
        self.settings["backend"] = "fex"
        with tempfile.TemporaryDirectory() as root:
            nixos, packaged = Path(root) / "nixos", Path(root) / "packaged"
            packaged.mkdir()
            self.settings["nativeVulkanDirectory"] = str(packaged)
            with (
                patch("x86_on_arm.environment.NIXOS_VULKAN_DIRECTORY", nixos),
                patch("x86_on_arm.environment.os.sysconf", return_value=4096),
            ):
                for drivers in ({"panthor"}, {"asahi"}):
                    self.assertEqual(graphics(self.settings, drivers)[2], {})
                driver = packaged / "panfrost_icd.aarch64.json"
                driver.write_text("{}")
                (packaged / "directory.json").mkdir()
                (packaged / "broken.json").symlink_to(packaged / "missing")
                for drivers in ({"panthor"}, {"asahi"}):
                    self.assertEqual(
                        graphics(self.settings, drivers)[2], {"VK_DRIVER_FILES": str(driver)}
                    )
                asahi = packaged / "asahi_icd.aarch64.json"
                asahi.write_text("{}")
                self.assertEqual(
                    graphics(self.settings, {"asahi"})[2], {"VK_DRIVER_FILES": str(asahi)}
                )
                nixos.mkdir()
                selected = nixos / "asahi_icd.aarch64.json"
                selected.write_text("{}")
                self.assertEqual(
                    graphics(self.settings, {"asahi"})[2], {"VK_DRIVER_FILES": str(selected)}
                )

    def test_runtime_identity_and_original_audio_endpoint(self):
        with tempfile.TemporaryDirectory() as root:
            config = Path(root) / "config.json"
            config.write_text('{"rootfs":"one"}')
            source = {"XDG_RUNTIME_DIR": root, "PATH": os.environ["PATH"]}
            first = VirtualMachine({}, str(config), source)
            second = VirtualMachine({}, str(config), source)
            self.assertEqual(first.unit, second.unit)
            self.assertEqual(first.host_environment()["PULSE_SERVER"], f"unix:{root}/pulse/native")
            self.assertEqual(first.host_environment()["PIPEWIRE_RUNTIME_DIR"], root)
            config.write_text('{"rootfs":"two"}')
            self.assertNotEqual(first.unit, VirtualMachine({}, str(config), source).unit)

    def test_display_socket_without_shared_directory_mutation(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            path = directory / "X7"
            renamed = directory / "X7_"
            source = {"DISPLAY": ":7.0"}
            self.assertIsNone(x11_socket(source, directory))
            with socket.socket(socket.AF_UNIX) as server:
                server.bind(str(renamed))
                self.assertEqual(x11_socket(source, directory), str(renamed))
                self.assertFalse(path.exists())
                with patch("x86_on_arm.environment.os.getuid", return_value=os.getuid() + 1):
                    self.assertIsNone(x11_socket(source, directory))
                renamed.rename(path)
                self.assertEqual(x11_socket(source, directory), str(path))
            self.assertIsNone(x11_socket({"DISPLAY": "remote:7"}, directory))
            self.assertEqual(x11_socket({"X11_SOCKET": "/custom/socket"}), "/custom/socket")


if __name__ == "__main__":
    unittest.main()
