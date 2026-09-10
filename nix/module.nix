{
  config,
  lib,
  pkgs,
  utils,
  ...
}:
let
  cfg = config.programs.x86-on-arm;
  runtime = pkgs.x86-on-arm.override {
    inherit (cfg)
      backend
      gpuMode
      allowSoftwareRendering
      memoryMiB
      environment
      nativeEnvironment
      ;
  };
  apps = pkgs.callPackage ./applications.nix { x86-on-arm = runtime; };
  interpreter = pkgs.writeShellScript "x86-on-arm-binfmt" ''
    exec ${lib.getExe runtime} binfmt "$@"
  '';
in
{
  options.programs.x86-on-arm = {
    enable = lib.mkEnableOption "x86 and x86-64 applications on ARM64 Linux";
    backend = lib.mkOption {
      type = lib.types.enum [
        "auto"
        "fex"
        "muvm"
      ];
      default = "auto";
      description = "Use FEX directly on 4 KiB hosts, or a muvm kernel on larger-page hosts.";
    };
    gpuMode = lib.mkOption {
      type = lib.types.enum [
        "auto"
        "drm"
        "venus"
        "software"
      ];
      default = "auto";
      description = "muvm graphics transport. Auto selects DRM for supported native-context drivers; other GPUs require an explicit transport.";
    };
    allowSoftwareRendering = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Allow software graphics and Mesa CPU Vulkan drivers.";
    };
    memoryMiB = lib.mkOption {
      type = lib.types.nullOr lib.types.ints.positive;
      default = null;
      description = "muvm memory ceiling in MiB; null keeps its upstream default.";
    };
    environment = lib.mkOption {
      type = lib.types.attrsOf lib.types.str;
      default = { };
      description = "Guest application environment overrides, including any explicit x86 loader paths.";
    };
    nativeEnvironment = lib.mkOption {
      type = lib.types.attrsOf lib.types.str;
      default = { };
      description = "Native thunk environment, applied through FEX HostEnv independently of the guest.";
    };
    steam.enable = lib.mkEnableOption "the Steam desktop launcher";
    wine.enable = lib.mkEnableOption "the Wine WoW64 launcher";
  };

  config = lib.mkIf cfg.enable {
    nixpkgs.overlays = [ (import ./overlay.nix) ];
    assertions = [
      {
        assertion = cfg.gpuMode != "software" || cfg.allowSoftwareRendering;
        message = "x86-on-arm: gpuMode = software requires allowSoftwareRendering = true.";
      }
      {
        assertion = pkgs.stdenv.hostPlatform.system == "aarch64-linux";
        message = "programs.x86-on-arm requires ARM64 Linux.";
      }
      {
        assertion =
          !(lib.any (
            system:
            lib.elem system [
              "x86_64-linux"
              "i686-linux"
            ]
          ) config.boot.binfmt.emulatedSystems);
        message = "x86-on-arm owns the x86 ELF handlers. Remove x86_64-linux/i686-linux from boot.binfmt.emulatedSystems.";
      }
    ];
    environment.systemPackages = [
      runtime
    ]
    ++ lib.optional cfg.steam.enable apps.steam
    ++ lib.optional cfg.wine.enable apps.wine;
    boot.binfmt.registrations =
      lib.mapAttrs
        (
          name: magic:
          magic
          // {
            inherit interpreter;
            preserveArgvZero = true;
            openBinary = false;
            matchCredentials = false;
            fixBinary = false;
            wrapInterpreterInShell = false;
          }
        )
        {
          x86-on-arm-x86_64 = utils.binfmtMagics.x86_64-linux;
          # Modern i686 binaries use EM_386 (3).
          x86-on-arm-i686 = utils.binfmtMagics.i386-linux;
        };
    # Defining nixPath overrides NixOS's default list, including <nixpkgs>.
    # Keep nix-shell on the same revision as the system and its x86 overlay.
    nix.nixPath = [
      "nixpkgs=${pkgs.path}"
      "nixpkgs-overlays=${./x86pkgs.nix}"
    ];
    hardware.graphics.enable = lib.mkDefault true;
  };
}
