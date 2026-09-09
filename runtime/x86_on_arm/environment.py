"""Keep application state separate from the ARM loaders and VM transports."""

import os
import re
from pathlib import Path

VM_ENVIRONMENT = {
    "DISPLAY",
    "XAUTHORITY",
    "XDG_RUNTIME_DIR",
    "PULSE_SERVER",
    "WAYLAND_DISPLAY",
    "DBUS_SESSION_BUS_ADDRESS",
    "GTK_IM_MODULE",
    "QT_IM_MODULE",
    "XRE_PROFILE_PATH",
    "PIPEWIRE_RUNTIME_DIR",
    "PIPEWIRE_REMOTE",
    "X11_SOCKET",
}
LOADER_ENVIRONMENT = {
    "LD_LIBRARY_PATH",
    "LD_PRELOAD",
    "VK_DRIVER_FILES",
    "VK_ICD_FILENAMES",
    "LIBGL_DRIVERS_PATH",
    "__EGL_VENDOR_LIBRARY_DIRS",
    "__EGL_VENDOR_LIBRARY_FILENAMES",
    "LIBGL_VENDORS_PATH",
    "LOCPATH",
    "GCONV_PATH",
    "GI_TYPELIB_PATH",
    "GIO_EXTRA_MODULES",
    "GTK_PATH",
    "QT_PLUGIN_PATH",
    "QT_QPA_PLATFORM_PLUGIN_PATH",
    "QML2_IMPORT_PATH",
    "ALSA_PLUGIN_DIR",
    "GST_PLUGIN_PATH",
    "GST_PLUGIN_PATH_1_0",
    "MESA_LOADER_DRIVER_OVERRIDE",
    "LIBGL_ALWAYS_SOFTWARE",
    "GALLIUM_DRIVER",
}
NIXOS_VULKAN_DIRECTORY = Path("/run/opengl-driver/share/vulkan/icd.d")


def backend_for(requested, pagesize):
    if requested == "auto":
        return "fex" if pagesize == 4096 else "muvm"
    if requested == "fex" and pagesize != 4096:
        raise RuntimeError("direct FEX needs 4096-byte pages; use --backend muvm on this host")
    return requested


def drm_drivers(sysfs=Path("/sys/class/drm")):
    return {path.resolve().name for path in sysfs.glob("renderD*/device/driver")}


def graphics(settings, drivers=None, *, backend=None):
    drivers = drm_drivers() if drivers is None else drivers
    backend = backend or backend_for(settings["backend"], os.sysconf("SC_PAGESIZE"))
    mode = "native" if backend == "fex" else settings["gpuMode"]
    if mode == "auto":
        if not drivers & {"asahi", "msm", "amdgpu"}:
            raise RuntimeError(
                "no supported muvm DRM native-context driver found; select gpuMode = venus "
                "for Vulkan virtualization (software rendering is never selected automatically)"
            )
        mode = "drm"
    allow_software = settings.get("allowSoftwareRendering", False)
    if mode == "software" and not allow_software:
        raise RuntimeError("gpuMode = software requires allowSoftwareRendering = true")

    patterns = ["*.json"]
    if mode == "venus":
        patterns = ["virtio_icd.*.json"]
    elif mode == "software":
        patterns = ["lvp_icd.*.json"]
    elif mode == "drm":
        known = {"asahi": "asahi", "msm": "freedreno", "amdgpu": "radeon"}
        patterns = [f"{known[driver]}_icd.*.json" for driver in sorted(drivers & known.keys())]
        patterns = patterns or ["*.json"]

    def manifests_in(directory):
        return sorted(
            {
                path
                for pattern in patterns
                for path in directory.glob(pattern)
                if path.is_file() and (allow_software or not path.name.startswith("lvp_icd."))
            }
        )

    manifests = Path(settings["rootfs"]) / "usr/share/x86-on-arm/vulkan"
    guest = ":".join("/usr/share/x86-on-arm/vulkan/" + p.name for p in manifests_in(manifests))
    native_paths = []
    for directory in (NIXOS_VULKAN_DIRECTORY, Path(settings["nativeVulkanDirectory"])):
        native_paths = manifests_in(directory)
        if native_paths:
            break
    if "asahi" in drivers and mode == "native":
        asahi = [p for p in native_paths if p.match("asahi_icd*.json")]
        if asahi:
            native_paths = asahi
    native = {"VK_DRIVER_FILES": ":".join(map(str, native_paths))} if native_paths else {}
    return mode, guest, native


def native_environment(source):
    return {key: value for key, value in source.items() if key not in LOADER_ENVIRONMENT}


def x11_socket(source, directory=Path("/tmp/.X11-unix")):
    if source.get("X11_SOCKET"):
        return source["X11_SOCKET"]
    display = re.fullmatch(r":(\d+)(?:\.\d+)?", source.get("DISPLAY", ""))
    if not display:
        return None
    path = directory / ("X" + display[1])
    if path.is_socket():
        return str(path)
    renamed = path.with_name(path.name + "_")
    if renamed.is_socket() and renamed.stat().st_uid == os.getuid():
        return str(renamed)
    return None


def guest_environment(settings, source, backend):
    omitted = LOADER_ENVIRONMENT | (VM_ENVIRONMENT if backend == "muvm" else set())
    env = {key: value for key, value in source.items() if key not in omitted}
    mode, icds, _ = graphics(settings, backend=backend)
    env.update(
        {
            "PATH": "/usr/local/bin:/usr/bin:/bin:" + source.get("PATH", ""),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "FEX_ROOTFS": settings["rootfs"],
            "FEX_THUNKCONFIG": settings["thunkConfig"],
            "XDG_DATA_DIRS": "/usr/local/share:/usr/share:" + source.get("XDG_DATA_DIRS", ""),
            "SSL_CERT_FILE": "/etc/ssl/certs/ca-bundle.crt",
            "LIBGL_DRIVERS_PATH": "/run/opengl-driver/lib/dri:/run/opengl-driver-32/lib/dri",
            "__EGL_VENDOR_LIBRARY_DIRS": "/run/opengl-driver/share/glvnd/egl_vendor.d:/run/opengl-driver-32/share/glvnd/egl_vendor.d",
        }
    )
    if icds:
        env["VK_DRIVER_FILES"] = icds
    if backend == "muvm":
        env["PULSE_SERVER"] = f"unix:/run/user/{os.getuid()}/pulse/native"
        env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path=/run/user/{os.getuid()}/bus"
        env["SDL_AUDIODRIVER"] = "pulseaudio"
        if mode == "venus":
            env["MESA_LOADER_DRIVER_OVERRIDE"] = "zink"
        elif mode == "software":
            env["MESA_LOADER_DRIVER_OVERRIDE"] = "llvmpipe"
            env["LIBGL_ALWAYS_SOFTWARE"] = "1"
            env["GALLIUM_DRIVER"] = "llvmpipe"
    env.update(settings["environment"])
    return env
