{ pkgs }:
let
  evaluated = import "${pkgs.path}/nixos/lib/eval-config.nix" {
    system = "aarch64-linux";
    modules = [
      ../nix/module.nix
      {
        nixpkgs.config.allowUnfree = true;
        programs.x86-on-arm.enable = true;
        system.stateVersion = "26.05";
      }
    ];
  };
  c = evaluated.config;
  rules = c.boot.binfmt.registrations;
  rulesFile = pkgs.writeText "x86-on-arm-binfmt-rules.json" (builtins.toJSON rules);
  filteredAssertions = builtins.filter (
    a: !a.assertion && pkgs.lib.hasInfix "x86-on-arm" a.message
  ) c.assertions;
  softwareAssertions =
    allowed:
    builtins.filter (a: !a.assertion && pkgs.lib.hasInfix "x86-on-arm" a.message)
      (evaluated.extendModules {
        modules = [
          {
            programs.x86-on-arm = {
              gpuMode = "software";
              allowSoftwareRendering = allowed;
            };
          }
        ];
      }).config.assertions;
in
assert filteredAssertions == [ ];
assert c.boot.binfmt.emulatedSystems == [ ];
assert !c.programs.x86-on-arm.allowSoftwareRendering;
assert builtins.length (softwareAssertions false) == 1;
assert softwareAssertions true == [ ];
assert builtins.elem "nixpkgs=${evaluated.pkgs.path}" c.nix.nixPath;
assert builtins.elem "nixpkgs-overlays=${../nix/x86pkgs.nix}" c.nix.nixPath;
assert evaluated.pkgs.x86pkgs.hello.system == "x86_64-linux";
assert evaluated.pkgs.x86packages.hello.outPath == evaluated.pkgs.x86pkgs.hello.outPath;
assert builtins.length (builtins.attrNames rules) == 2;
pkgs.runCommand "x86-on-arm-module-check"
  {
    passthru = { inherit rulesFile; };
    nativeBuildInputs = [ pkgs.nix ];
    NIX_PATH = pkgs.lib.concatStringsSep ":" c.nix.nixPath;
  }
  ''
    ${pkgs.python3}/bin/python3 ${./module.py} ${rulesFile} \
      ${evaluated.pkgs.x86pkgs.coreutils}/bin/true \
      ${evaluated.pkgs.x86pkgs.pkgsi686Linux.coreutils}/bin/true ${pkgs.coreutils}/bin/true
    test "$(nix-instantiate --store dummy:// --eval --strict --expr \
      '(import <nixpkgs> {}).x86pkgs.hello.system')" = '"x86_64-linux"'
    test "$(readlink -f ${evaluated.pkgs.x86-on-arm-steam}/bin/steam)" = \
      "$(readlink -f ${evaluated.pkgs.x86-on-arm-steam}/bin/x86-arm-steam)"
    touch "$out"
  ''
