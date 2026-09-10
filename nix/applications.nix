{
  lib,
  stdenv,
  stdenvNoCC,
  writeShellApplication,
  makeDesktopItem,
  symlinkJoin,
  bubblewrap,
  coreutils,
  util-linux,
  steam-unwrapped,
  x86pkgs,
  x86-on-arm,
}:
let
  render = import ./render.nix lib;
  bwrap = stdenv.mkDerivation {
    name = "x86-on-arm-pressure-vessel";
    dontUnpack = true;
    buildPhase = ''
      $CC -D_GNU_SOURCE -Wall -Wextra -Werror -O2 \
        -DBWRAP='"${lib.getExe bubblewrap}"' -DCOREUTILS_PATH='"${coreutils}/bin"' \
        ${../applications/pressure-vessel.c} -o x86-arm-bwrap
    '';
    installPhase = ''mkdir -p "$out/bin"; cp x86-arm-bwrap "$out/bin/"'';
  };
  bootstrap = stdenvNoCC.mkDerivation {
    pname = "x86-on-arm-steam-bootstrap";
    inherit (steam-unwrapped) version src;
    dontBuild = true;
    dontFixup = true; # Preserve the vendor's portable guest shebangs.
    installPhase = ''
      mkdir -p "$out"
      cp bin_steam.sh bootstraplinux_ubuntu12_32.tar.xz steam_subscriber_agreement.txt "$out/"
    '';
  };
  launcher = writeShellApplication {
    name = "x86-arm-steam";
    runtimeInputs = [
      coreutils
      util-linux
    ];
    text = render ../applications/steam.sh {
      inherit bootstrap bwrap;
      inherit (steam-unwrapped) version;
      runtime = x86-on-arm;
    };
  };
in
{
  steam = symlinkJoin {
    name = "x86-on-arm-steam";
    paths = [
      launcher
      (makeDesktopItem {
        name = "x86-on-arm-steam";
        desktopName = "Steam (x86 on ARM)";
        exec = "x86-arm-steam %U";
        icon = "steam";
        categories = [
          "Game"
          "Network"
        ];
        mimeTypes = [
          "x-scheme-handler/steam"
          "x-scheme-handler/steamlink"
        ];
      })
    ];
    postBuild = ''
      ln -s ${steam-unwrapped}/share/icons "$out/share/icons"
      ln -s x86-arm-steam "$out/bin/steam"
    '';
    meta.mainProgram = "x86-arm-steam";
  };
  wine = writeShellApplication {
    name = "x86-arm-wine";
    runtimeInputs = [ coreutils ];
    text = render ../applications/wine.sh {
      runtime = x86-on-arm;
      wine = x86pkgs.wineWow64Packages.stable;
    };
  };
  inherit bwrap;
}
