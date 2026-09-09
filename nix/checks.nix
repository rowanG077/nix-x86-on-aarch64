{ self, pkgs }:
let
  stack = pkgs.x86-on-arm-components;
in
{
  style =
    pkgs.runCommand "x86-on-arm-style-check"
      {
        nativeBuildInputs = [
          pkgs.nixfmt
          pkgs.ruff
        ];
      }
      ''
        find ${self} -name '*.nix' -print0 | xargs -0 nixfmt --check
        ruff check --no-cache --config ${../ruff.toml} ${../runtime} ${../checks} ${../guest}
        ruff format --check --no-cache --config ${../ruff.toml} ${../runtime} ${../checks} ${../guest}
        touch "$out"
      '';
  runtime = pkgs.runCommand "x86-on-arm-runtime-tests" { nativeBuildInputs = [ pkgs.python3 ]; } ''
    export PYTHONPATH=${../runtime}
    export TEST_BASH=${pkgs.bash}/bin/bash TEST_ENV=${pkgs.coreutils}/bin/env
    python3 -m unittest discover -s ${../checks} -p 'test_*.py' -v
    touch "$out"
  '';
  image = pkgs.runCommand "x86-on-arm-image-check" { } ''
    ${pkgs.python3}/bin/python3 ${../checks/image.py} ${stack.image} \
      ${stack.fex}/share/fex-emu/ThunksDB.json \
      ${pkgs.lib.escapeShellArg (builtins.toJSON stack.image.thunkLibraryDirs)}
    touch "$out"
  '';
  forwarding =
    pkgs.runCommandCC "x86-on-arm-forwarding-check"
      {
        nativeBuildInputs = [
          pkgs.python3
          pkgs.patchelf
          pkgs.binutils
        ];
        WAYLAND = pkgs.wayland;
      }
      ''
        $CC -Wall -Wextra -Werror ${../checks/load.c} -o load -ldl
        python3 ${../checks/forwarding.py} ${stack.fex} ${pkgs.libglvnd.dev}/include
        touch "$out"
      '';
  probes = self.packages.aarch64-linux.probes;
  module = import ../checks/module.nix { inherit pkgs; };
}
