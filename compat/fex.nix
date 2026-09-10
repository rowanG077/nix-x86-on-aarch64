{
  lib,
  upstream,
  patchelf,
  python3,
  writeText,
  pkgsCross,
  alsa-lib,
  libdrm,
  libglvnd,
  vulkan-loader,
  wayland,
  libx11,
  libxcb,
  libxrandr,
  libxrender,
  thunkLibraryDirs,
}:
let
  dependencies = [
    alsa-lib
    libdrm
    libglvnd
    vulkan-loader
    wayland
    libx11
    libxcb
    libxrandr
    libxrender
  ];
  crt =
    cross:
    "${cross.stdenv.cc.cc}/lib/gcc/${cross.stdenv.hostPlatform.config}/${cross.stdenv.cc.cc.version}";
in
upstream.overrideAttrs (old: {
  version = "2609-unstable-2026-09-10";
  src = old.src.override {
    tag = null;
    rev = "e431bfe0fa80d44207eafc6c2c798cda70d41266";
    hash = "sha256-JfCAWwHZ59zeoiwgZ8h9wlBuQaSsEqGHh7Yr1MT44oQ=";
  };
  patches =
    (old.patches or [ ])
    ++ (map (name: ./patches/fex + "/${name}.patch") [
      "wayland-32bit-allocations"
      "wayland-fixes-interface"
      "egl-thunk-database"
      "egl-core-api"
      "gles-core-entrypoints"
      "host-environment-isolation"
      "alsa-mixer-callbacks"
      "wayland-proxy-interface"
    ]);
  postPatch = (old.postPatch or "") + ''
    ${lib.getExe python3} ${./thunk-paths.py} Data/ThunksDB.json \
      ${writeText "x86-on-arm-thunk-paths.json" (builtins.toJSON thunkLibraryDirs)}
    cat >> ThunkLibs/GuestLibs/CMakeLists.txt <<'EOF'
    if (GENERATE_GUEST_INSTALL_TARGETS)
      if (BITNESS EQUAL 32)
        set(NIX_GUEST_CRT "${crt pkgsCross.gnu32}")
      else()
        set(NIX_GUEST_CRT "${crt pkgsCross.gnu64}")
      endif()
      foreach(name GL EGL vulkan drm asound wayland-client cuda fex_thunk_test)
        if (TARGET ''${name}-guest)
          target_link_options(''${name}-guest PRIVATE "''${NIX_GUEST_CRT}/crtbeginS.o" "LINKER:-z,nodelete")
          target_link_libraries(''${name}-guest PRIVATE "''${NIX_GUEST_CRT}/crtendS.o")
        endif()
      endforeach()
    endif()
    EOF
  '';
  nativeBuildInputs = (old.nativeBuildInputs or [ ]) ++ [ patchelf ];
  postFixup = (old.postFixup or "") + ''
    # dlopen dependencies must survive Nix's RUNPATH shrinking. Both host
    # directories contain ARM64 code, including the one serving i386 clients.
    for thunk in "$out"/lib/fex-emu/HostThunks{,_32}/*.so; do
      patchelf --add-rpath ${lib.escapeShellArg (lib.makeLibraryPath dependencies)} "$thunk"
    done
    # Guest libraries resolve C++ through the active x86 userspace. A native
    # absolute DT_NEEDED here would load the wrong architecture.
    for thunk in "$out"/share/fex-emu/GuestThunks{,_32}/*.so; do
      case "$thunk" in */libVDSO-guest.so) continue ;; esac
      patchelf --add-needed libstdc++.so.6 --add-needed libgcc_s.so.1 --add-needed libc.so.6 "$thunk"
    done
  '';
})
