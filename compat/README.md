# Downstream compatibility changes

This directory contains downstream patches and probes for ABI and transport issues. The runtime and image are built from the current checkout.

| Change | Reason to retain it | Removal condition |
|---|---|---|
| FEX EGL core API and thunk database | Missing exports, EGL procedure lookup and i386 array/pointer conversion | Upstream implementation passes the public API and live EGL probes |
| FEX GLES core entrypoints | GLES 3.2 names and transform-feedback string arrays | Both guest ABIs pass the GL/GLES checks without it |
| FEX Wayland allocations | Guest interface arrays must stay below 4 GiB for i386 | Upstream allocation strategy passes 32-bit interface/callback probes |
| FEX Wayland fixes interface | Current protocol symbols, queue APIs, guest list/array operations | Installed Wayland and Mesa dependencies are covered upstream |
| FEX host environment isolation | Native ICD overrides previously overwrote guest values | Native/guest ICD isolation works without the patch |
| FEX ALSA mixer callbacks | Chromium uses missing callback and private-data APIs | Mixer callback tests pass with upstream FEX |
| muvm interactive stdio | File stdin, full-duplex deadlocks, truncated output, signal status and concurrent port races | The live pipe/terminal/concurrency suite passes upstream |
| muvm client lifetime | A root-owned cgroup entered before exec retains every descendant across job control, sessions, forks and reparenting; completion acknowledgement distinguishes success from disconnect | Upstream passes the process-tree, late-fork, blocked-I/O, completion-race and cgroup-retirement probes |

`wayland-proxy-interface.patch` makes `wl_proxy_get_interface` return the registered **guest** interface for both ABIs. The live probe checks the pointer identity.

The display patches add an explicit `X11_SOCKET` path to libkrun and normalize muvm's display number for Xauthority. This lets the runtime use a renamed, user-owned desktop socket without changing `/tmp/.X11-unix` or the guest's authentication identity. Remove them when upstream supplies equivalent socket selection and handles `:display.screen` consistently.

`fex.nix` supplies CRT objects and NODELETE behavior for guest C++ thunks, preserves native `dlopen` dependencies after fixup, and uses guest SONAMEs. `thunk-paths.py` maps upstream FHS names to x86 Nix libraries.

The x86 `ldconfig` shim works around static glibc `ldconfig` crashing under FEX. It preserves PressureVessel's architecture check and runs the tool with native QEMU. Both `/usr/bin/ldconfig` and `/sbin/ldconfig` point to it.

## Updating

1. Update `flake.lock` and pinned source/hash entries in `fex.nix` and `muvm.nix`.
2. Review each patch against upstream and drop fixes that have landed.
3. Run `nix flake check`, then `nix run .#verify -- --binfmt --graphics` on a supported desktop.
4. Test the direct backend on a 4 KiB ARM kernel and the muvm backend on a larger-page host. Launch Steam and a representative Wine application.

Source projects: [FEX](https://github.com/FEX-Emu/FEX), [muvm](https://github.com/AsahiLinux/muvm), [nixpkgs](https://github.com/NixOS/nixpkgs).
