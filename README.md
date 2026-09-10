# nix-x86-on-aarch64

Run x86 and x86-64 Linux applications on ARM64 with FEX and a reproducible Nix userspace. On hosts with 4 KiB pages, FEX runs directly. Larger-page hosts use muvm to supply a 4 KiB kernel. Steam and Wine use the same runtime.

The target is ARM64 Linux. Asahi is one supported configuration; the runtime and guest filesystem are distribution agnostic.

## Try it

From this directory, in your normal user session:

```sh
nix run . -- doctor
nix run . -- shell -c 'uname -m; getconf PAGESIZE'
nix run . -- run /path/to/x86-program argument
nix run .#wine -- /path/to/windows-installer.exe
nix run .#steam
```

The muvm backend needs `/dev/kvm` access and a systemd user session. It starts its own user service on first use; no manual service installation is necessary. `x86-arm doctor` reports the selected backend, GPU transport, versions and service name. `x86-arm stop` stops that runtime's VM and its applications.

Wine uses the pinned x86 Wine WoW64 package. Its default prefix is `$XDG_DATA_HOME/x86-on-arm/wineprefix` (normally `~/.local/share/x86-on-arm/wineprefix`). Set `WINEPREFIX` to select an existing prefix. Steam uses its usual application data and game library locations. Its launcher uses muvm on all hosts because PressureVessel's native helpers need the VM's prepared filesystem.

## NixOS

Add a flake input pointing at your checkout and import its module:

```nix
inputs.nix-x86-on-aarch64 = {
  url = "path:/absolute/path/to/nix-x86-on-aarch64";
  inputs.nixpkgs.follows = "nixpkgs";
};

# In nixosSystem.modules:
inputs.nix-x86-on-aarch64.nixosModules.default
{
  programs.x86-on-arm = {
    enable = true;
    steam.enable = true; # Optional desktop application
    wine.enable = true;  # Optional Wine launcher
  };
}
```

Rebuild NixOS, then open a new shell. Enabling the runtime installs **both ELF handlers, x86pkgs, and all six supported thunk families by default**. There is no separate forwarding or binfmt opt-in.

```sh
nix-shell -p x86pkgs.hello --run hello
nix-shell -p x86pkgs.wineWow64Packages.stable --run 'wine --version'
steam # When programs.x86-on-arm.steam.enable is true
```

The module sets `<nixpkgs>` to the system's Nixpkgs source and exposes the x86 overlay to `nix-shell`. Steam is available as both `steam` and `x86-arm-steam`, with the same launcher behind either command.

`x86packages` aliases `x86pkgs`, the native x86-64 package set from the same nixpkgs revision. Cached packages work normally; uncached derivations need a suitable builder. The runtime leaves Nix daemon build-platform settings unchanged.

The module replaces the need for x86 entries in `boot.binfmt.emulatedSystems`. Remove those entries, and remove the old `steam-asahi` module when migrating. Keep your machine's normal graphics and KVM access configuration. Steam requires an appropriate unfree-package policy.

## Configuration

The module supports `backend = "auto" | "fex" | "muvm"`, `gpuMode = "auto" | "drm" | "venus" | "software"`, and an optional `memoryMiB` ceiling. Auto graphics uses muvm DRM native context on Asahi, MSM/freedreno and AMDGPU. Other GPUs require an explicit transport, usually `gpuMode = "venus"`. Direct FEX uses the host graphics stack.

Software rendering requires both `allowSoftwareRendering = true;` and `gpuMode = "software";`. It is never selected by `auto`.

Native Vulkan uses hardware ICDs for DRM, Virtio for Venus and Lavapipe for explicit software mode. It uses NixOS drivers when available, then packaged ARM Mesa. `nativeEnvironment` can override the native driver.

`environment` sets guest application variables. `nativeEnvironment` sets FEX's native thunk variables. Native loader and plugin paths inherited from the caller are removed before launching x86 applications; supply deliberate x86 loader overrides through `environment`. Both settings are Nix configuration and are visible in the store.

The overlay exports `pkgs.x86-on-arm`, `pkgs.x86-on-arm-steam`, `pkgs.x86-on-arm-wine`, `pkgs.x86pkgs`, and `pkgs.x86packages`. Its components live under `pkgs.x86-on-arm-components`; it does not replace the host's ordinary `pkgs.fex` or `pkgs.muvm`.

## Validation and limits

```sh
nix flake check
nix run .#verify
nix run .#verify -- --binfmt --graphics
```

The last command requires a usable GPU/audio session and user namespaces. Kernel registration tests use a temporary private binfmt table; they do not change the host's registrations. See [testing](docs/testing.md) for the checks and recorded hardware results, [design](docs/design.md) for the execution model, and [compatibility](docs/compatibility.md) for ABI and platform limits.

Pinned baseline: nixpkgs `58973d74f189`, FEX 2609, muvm 0.6.0 plus upstream commit `c50e79c11eb5`. The small downstream compatibility patch set is documented in [compat/README.md](compat/README.md).
