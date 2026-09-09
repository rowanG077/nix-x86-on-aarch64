{
  pkgs,
  lib,
  guests,
}:
let
  fhsBuilder = import "${guests.path}/pkgs/build-support/build-fhsenv-bubblewrap/buildFHSEnv.nix" {
    inherit (pkgs)
      lib
      runCommandLocal
      buildEnv
      writeText
      ;
    inherit (guests) stdenv;
    pkgsHostTarget = guests;
    writeShellScriptBin =
      name: text:
      pkgs.writeTextFile {
        inherit name;
        destination = "/bin/${name}";
        executable = true;
        text = "#!${guests.runtimeShell}\n${text}";
      };
    pkgs = guests // {
      inherit (pkgs) runCommand jq writeTextFile;
      buildPackages = pkgs;
      pkgsBuildBuild = pkgs;
      lsb-release = guests.lsb-release.override { inherit (pkgs) replaceVarsWith; };
    };
  };
  base = fhsBuilder (
    guests.steam.args
    // (import ./packages.nix { inherit lib guests; })
    // {
      pname = "x86-on-arm-userspace";
      profile = "";
      extraBuildCommands = "";
    }
  );
  alsaConfig = pkgs.writeText "x86-on-arm-alsa.conf" (
    lib.concatMapStrings
      (kind: ''
        ${kind}_type.pulse {
          libs.native = "${pkgs.alsa-plugins}/lib/alsa-lib/libasound_module_${kind}_pulse.so"
          libs.x86_64 = "${guests.alsa-plugins}/lib/alsa-lib/libasound_module_${kind}_pulse.so"
          libs.i386 = "${guests.pkgsi686Linux.alsa-plugins}/lib/alsa-lib/libasound_module_${kind}_pulse.so"
        }
      '')
      [
        "pcm"
        "ctl"
      ]
  );
  ldconfig = pkgs.pkgsCross.gnu64.stdenv.mkDerivation {
    name = "x86-on-arm-ldconfig";
    dontUnpack = true;
    nativeBuildInputs = [ pkgs.patchelf ];
    buildPhase = ''
      $CC -Wall -Wextra -Werror -O2 \
        -DQEMU='"${pkgs.qemu-user}/bin/qemu-i386"' \
        -DLDCONFIG='"${guests.pkgsi686Linux.glibc.bin}/bin/ldconfig"' \
        ${./ldconfig.c} -o ldconfig
    '';
    installPhase = ''mkdir -p "$out/bin"; cp ldconfig "$out/bin/"'';
    postFixup = ''
      patchelf --set-interpreter /lib64/ld-linux-x86-64.so.2 --remove-rpath "$out/bin/ldconfig"
    '';
  };
  thunkPaths =
    p:
    lib.mapAttrs (_: package: [ "${lib.getLib package}/lib" ]) {
      GL = p.libglvnd;
      EGL = p.libglvnd;
      Vulkan = p.vulkan-loader;
      drm = p.libdrm;
      asound = p.alsa-lib;
      WaylandClient = p.wayland;
    };
in
pkgs.runCommand "x86-on-arm-rootfs"
  {
    exportReferencesGraph = [
      "base-closure"
      base
      "ldconfig-closure"
      ldconfig
      "alsa-closure"
      alsaConfig
    ];
    passthru = {
      inherit guests alsaConfig;
      thunkLibraryDirs = lib.zipAttrsWith (_: values: lib.unique (lib.concatLists values)) (
        map thunkPaths [
          guests
          guests.pkgsi686Linux
        ]
      );
    };
  }
  ''
    ${lib.getExe pkgs.python3} ${./assemble.py} "$out" ${base} base-closure ldconfig-closure alsa-closure
    for entry in bin sbin lib lib32 lib64 libexec; do
      rm "$out/$entry"
      ln -s "usr/$entry" "$out/$entry"
    done
    rm "$out/usr/lib" "$out/usr/lib64/ld-linux.so.2"
    ln -s lib32 "$out/usr/lib"
    ln -s ../lib32/ld-linux.so.2 "$out/usr/lib64/ld-linux.so.2"
    rm -f "$out/etc/ld.so.cache" "$out/etc/os-release"
    printf 'NAME="x86-on-arm"\nID=nixos\nVERSION_ID="${lib.version}"\nPRETTY_NAME="Nix x86 application userspace"\n' > "$out/etc/os-release"
    mkdir -p "$out/etc/alsa/conf.d" "$out/usr/share/x86-on-arm/vulkan" "$out/run"
    cp ${alsaConfig} "$out/etc/alsa/conf.d/00-x86-on-arm.conf"
    printf 'pcm.!default { type pulse }\nctl.!default { type pulse }\n' > "$out/etc/asound.conf"

    cp ${guests.mesa}/share/vulkan/icd.d/*.json "$out/usr/share/x86-on-arm/vulkan/"
    cp ${guests.pkgsi686Linux.mesa}/share/vulkan/icd.d/*.json "$out/usr/share/x86-on-arm/vulkan/"
    ln -s ../nix/store/${baseNameOf (toString guests.mesa)} "$out/run/opengl-driver"
    ln -s ../nix/store/${baseNameOf (toString guests.pkgsi686Linux.mesa)} "$out/run/opengl-driver-32"
    rm "$out/usr/bin/ldconfig" "$out/usr/sbin/ldconfig"
    ln -s ../../nix/store/${baseNameOf (toString ldconfig)}/bin/ldconfig "$out/usr/bin/ldconfig"
    ln -s ../bin/ldconfig "$out/usr/sbin/ldconfig"
    for glibc in ${guests.glibc} ${guests.pkgsi686Linux.glibc}; do
      ln -s ../../../../etc/ld.so.cache "$out$glibc/etc/ld.so.cache"
      ln -s ../../../../etc/ld.so.conf "$out$glibc/etc/ld.so.conf"
    done
    printf '/usr/lib64\n/usr/lib\n' > "$out/etc/ld.so.conf"
    ${pkgs.qemu-user}/bin/qemu-i386 ${guests.pkgsi686Linux.glibc.bin}/bin/ldconfig \
      -r "$out" -C /etc/ld.so.cache -f /etc/ld.so.conf -X
  ''
