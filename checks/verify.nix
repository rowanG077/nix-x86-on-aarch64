{
  pkgs,
  lib,
  writeShellApplication,
  writeText,
  runtime,
  probes,
  guests,
}:
let
  nativeView = writeShellApplication {
    name = "x86-on-arm-native-view-check";
    runtimeInputs = [
      pkgs.coreutils
      pkgs.util-linux
    ];
    text = (import ../nix/render.nix lib) ./native-view.sh {
      init = lib.getExe runtime.init;
      inherit (pkgs) bash;
    };
  };
  pressureVessel = writeShellApplication {
    name = "x86-on-arm-pressure-vessel-check";
    text = ''
      exec ${pkgs.python3}/bin/python3 ${./pressure-vessel.py} \
        ${(pkgs.callPackage ../nix/applications.nix { x86-on-arm = runtime; }).bwrap}/bin/x86-arm-bwrap \
        --bubblewrap ${lib.getExe pkgs.bubblewrap}
    '';
  };
  fixtures = writeText "x86-on-arm-live-fixtures.json" (
    builtins.toJSON {
      runtime = lib.getExe runtime;
      settings = toString runtime.settings;
      nativeView = lib.getExe nativeView;
      pressureVessel = lib.getExe pressureVessel;
      core64 = toString guests.coreutils;
      core32 = toString guests.pkgsi686Linux.coreutils;
      bash = toString guests.bashInteractive;
      probes = toString probes;
      vulkanTools = toString guests.vulkan-tools;
      rules = toString (import ./module.nix { inherit pkgs; }).rulesFile;
      nixPath = "nixpkgs=${pkgs.path}:nixpkgs-overlays=${../nix/x86pkgs.nix}";
    }
  );
in
writeShellApplication {
  name = "x86-on-arm-verify";
  runtimeInputs = [
    pkgs.python3
    pkgs.util-linux
    pkgs.nix
  ];
  text = ''exec python3 ${./live.py} ${fixtures} "$@"'';
  passthru = { inherit fixtures; };
}
