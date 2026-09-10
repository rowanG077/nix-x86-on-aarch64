# Testing

## Build checks

`nix flake check` runs without KVM or a graphics session. It covers:

- **Runtime contracts:** backend selection, explicit software gate, transport-specific Vulkan selection despite a populated host driver directory, direct FEX on other GPUs, environment isolation, preserved arguments and `argv[0]`, executable paths containing `=`, lookup past incompatible PATH entries, signal forwarding and private file cleanup, configuration identity, display socket discovery without shared-directory changes.
- **Image:** both x86 ELF loaders, library architectures, closed relative links, all Mesa ICDs, certificates, linker cache and thunk path coverage.
- **Forwarding:** each native thunk's `dlopen` dependencies, guest ELF ABI, constructors/finalizers and NODELETE, public GL/GLES/EGL APIs, Wayland interface symbols and ALSA mixer callbacks.
- **NixOS module:** enabling the module supplies both actual ELF masks with `P` semantics and the x86 package aliases, without enabling Nix daemon emulated build platforms. A fresh Nix evaluation resolves `x86pkgs.hello` through the module's `NIX_PATH`, and the Steam package provides both launcher names. Software mode is rejected unless its separate gate is enabled.
- **Probes:** cross-compile the 32-bit and 64-bit live ABI and cancellation probes and their small native Wayland server.
- **Style:** Nix formatting and Python formatting/lint checks.

## Live checks

`nix run .#verify` uses pinned x86 packages. It covers binary pipes, regular-file stdin, `/dev/null`, quoted working directories, environment and argument round-tripping, separate stdout/stderr, exit status, signals, concurrency and PTY/Ctrl-C behavior.

On muvm it cancels launchers and host process groups while stdin is blocked. The guest command and descendants ignore SIGTERM, so cleanup must escalate.

Cancellation is checked after the guest parent exits, with descendants retaining open output. 32-bit and 64-bit helpers cover process groups, `setsid`, double forks, late forks and blocked stdout. They must retain the request cgroup until cancellation; an unrelated request and the VM worker count must remain healthy.

The protocol tests the completion acknowledgement race, output after parent exit and status preservation. The shared FEXServer stays outside request cgroups and keeps its PID. Helpers have time limits.

`--graphics` checks the session bus and PipeWire, then loads GL, EGL, Wayland, ALSA, DRM and Vulkan for each ABI through FHS and absolute Nix paths. It also exercises callbacks, pointer conversion, audio, EGL/GL contexts and Vulkan enumeration. Finally, the pinned x86-64 `vkcube` renders 60 frames through XCB, covering Vulkan function lookup, device creation and presentation. It needs a working desktop with X11 or Xwayland.

`--binfmt` creates a private binfmt filesystem in nested user/mount namespaces. It registers the **module-generated** handlers, runs both ELF ABIs, checks `argv[0]`, and runs `x86pkgs.hello` and x86 Wine. The table is unmounted afterward and host handlers are unchanged.

This option also tests VM filesystem preparation with split and merged `/usr` layouts and a 16 MiB noexec `/run` tmpfs.

## Hardware record

Validation on 2026-09-09 used ARM64 NixOS, Apple M2 Max, and a 16 KiB host kernel:

| Check | Result |
|---|---|
| Nix builds and flake checks | Passed |
| muvm command, pipe, concurrency and PTY suite | Passed |
| Both ABIs: cgroup cancellation across job groups, sessions, double/late forks and blocked I/O; acknowledgement race, shared-service isolation and cleanup | Passed |
| Actual kernel ELF dispatch, x86pkgs Hello and Wine | Passed |
| 32/64-bit GL, EGL, Wayland, ALSA, DRM and Vulkan probes; FHS and Nix paths | Passed |
| Venus Vulkan and OpenGL through Zink, with no CPU device exposed | Passed |
| Software rejected without its gate; explicit experimental Vulkan/OpenGL through llvmpipe | Passed |
| Direct FEX command/pipe/concurrency/PTY suite inside a 4 KiB ARM guest | Passed |
| Guest D-Bus and PipeWire query | Passed |
| Wine 11.0 Notepad, disposable prefix, rendered test document | Passed |
| Steam login and rendered Library window | Passed |
| VM restart with a renamed host X11 socket; complete live suite | Passed |

GPU-specific results on this machine are not evidence for other ARM GPUs. Direct execution was tested with a real 4 KiB ARM kernel inside the available VM, not on a second physical ARM board.

Application checks cover startup only. They do not establish game compatibility, hardware communication, licensing or every application feature.
