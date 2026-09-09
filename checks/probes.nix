{
  lib,
  stdenv,
  pkgsCross,
  pkg-config,
  wayland,
  vulkan-headers,
  patchelf,
  writeText,
  symlinkJoin,
  guests,
}:
let
  server = stdenv.mkDerivation {
    name = "x86-on-arm-wayland-probe-server";
    dontUnpack = true;
    nativeBuildInputs = [ pkg-config ];
    buildInputs = [ wayland ];
    buildPhase = ''
      $CC -Wall -Wextra -Werror ${./wayland-server.c} -o wayland-server $(pkg-config --cflags --libs wayland-server)
    '';
    installPhase = ''mkdir -p "$out/bin"; cp wayland-server "$out/bin/"'';
  };
  nativeCancellation = stdenv.mkDerivation {
    name = "x86-on-arm-native-cancellation-probe";
    dontUnpack = true;
    buildPhase = "$CC -Wall -Wextra -Werror -O2 ${./cancellation.c} -o cancellation-probe-native";
    installPhase = ''mkdir -p "$out/bin"; cp cancellation-probe-native "$out/bin/"'';
  };
  probe =
    bits: cross: p:
    let
      paths = {
        "libGL.so.1" = "${p.libglvnd}/lib/libGL.so.1";
        "libEGL.so.1" = "${p.libglvnd}/lib/libEGL.so.1";
        "libOpenGL.so.0" = "${p.libglvnd}/lib/libOpenGL.so.0";
        "libGLESv2.so.2" = "${p.libglvnd}/lib/libGLESv2.so.2";
        "libwayland-client.so.0" = "${p.wayland}/lib/libwayland-client.so.0";
        "libasound.so.2" = "${lib.getLib p.alsa-lib}/lib/libasound.so.2";
        "libdrm.so.2" = "${lib.getLib p.libdrm}/lib/libdrm.so.2";
        "libvulkan.so.1" = "${p.vulkan-loader}/lib/libvulkan.so.1";
      };
      header = writeText "x86-on-arm-probe-paths-${bits}.h" ''
        static const struct { const char *name; const char *path; } nix_libraries[] = {
        ${lib.concatStringsSep "\n" (lib.mapAttrsToList (name: path: ''{"${name}", "${path}"},'') paths)}
        };
      '';
    in
    cross.stdenv.mkDerivation {
      name = "x86-on-arm-thunk-probe-${bits}";
      dontUnpack = true;
      nativeBuildInputs = [ patchelf ];
      buildPhase = ''
        $CC -Wall -Wextra -Werror -I${vulkan-headers}/include -I${wayland.dev}/include -include ${header} \
          -DWAYLAND_SERVER='"${server}/bin/wayland-server"' ${./thunks.c} -o thunk-probe-${bits} -ldl
        $CC -Wall -Wextra -Werror -O2 ${./cancellation.c} -o cancellation-probe-${bits}
      '';
      installPhase = ''mkdir -p "$out/bin"; cp thunk-probe-${bits} cancellation-probe-${bits} "$out/bin/"'';
      postFixup = ''
        for executable in "$out/bin/"*; do
          patchelf --set-interpreter ${
            if bits == "32" then "/lib/ld-linux.so.2" else "/lib64/ld-linux-x86-64.so.2"
          } --remove-rpath "$executable"
        done
      '';
    };
in
symlinkJoin {
  name = "x86-on-arm-thunk-probes";
  paths = [
    nativeCancellation
    (probe "64" pkgsCross.gnu64 guests)
    (probe "32" pkgsCross.gnu32 guests.pkgsi686Linux)
  ];
}
