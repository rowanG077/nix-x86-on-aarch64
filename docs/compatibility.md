# Compatibility

## Hosts

The package target is ARM64 Linux with Nix. The NixOS module installs the ELF handlers and overlay. FEX needs 4 KiB pages; `auto` chooses it when available and muvm otherwise. muvm needs KVM and a systemd user session.

DRM acceleration depends on hardware and kernel support; muvm documents freedreno, AMDGPU and Asahi native contexts. Other boards need an explicit transport such as Venus. Software mode requires `gpuMode = "software"` and `allowSoftwareRendering = true`. See [muvm](https://github.com/AsahiLinux/muvm) and [FEX](https://github.com/FEX-Emu/FEX).

Cancellation requires cgroup v2 and `cgroup.kill` in the guest kernel. Requests fail before exec when those interfaces are unavailable.

## Library forwarding

| Family | x86-64 | i386 |
|---|---|---|
| GL, including OpenGL/GLX/GLES aliases | Native thunk | Native thunk |
| EGL | Native thunk | Native thunk |
| Wayland client | Native thunk | Native thunk |
| Vulkan | Native thunk | x86 library |
| ALSA | Native thunk | x86 library |
| DRM | Native thunk | x86 library |

All six are enabled by default. The pinned FEX revision does not implement i386 Vulkan, ALSA or DRM thunks, so these use the image's corresponding x86 libraries. CUDA is not part of this hardware-independent forwarding set. Upstream application-specific FEX configuration can disable a thunk to work around an application bug.

Checks cover native dependencies, guest ABIs, C++ lifetime, GL/EGL entrypoints, Wayland interfaces and Nix library paths. Live probes also cover callbacks, audio, EGL/GL and Vulkan. They do not cover every extension or application.

## Application behavior

Steam is a separate launcher with native PressureVessel support. It uses muvm even on 4 KiB hosts to provide the native helpers' FHS filesystem. Its downloads and updates remain Steam-managed. GPU acceleration, game compatibility, DRM and anti-cheat behavior depend on the application and drivers.

The tested Steam client emits CEF GPU-process warnings and may render its UI in software; game rendering and graphics thunks remain active. Exit Steam before stopping its VM to avoid stale Chromium profile locks.

Wine is an x86 package executed through FEX. Windows PE programs need `x86-arm-wine program.exe`, or x86 Wine from `nix-shell`. Use `WINEPREFIX` to select a prefix. Proton prefixes can contain build-specific DLLs and may require a matching Wine build.

muvm supplies X11 and audio endpoints. Native Wayland desktop forwarding, arbitrary host devices and Ethernet sensor communication are outside the tested surface.
