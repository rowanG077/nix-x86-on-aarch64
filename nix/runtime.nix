{
  lib,
  stdenvNoCC,
  python3,
  writeText,
  writeShellApplication,
  buildEnv,
  coreutils,
  bash,
  util-linux,
  systemd,
  pciutils,
  pulseaudio,
  lsb-release,
  zenity,
  glibc,
  dbus,
  mesa,
  stack,
  backend ? "auto",
  gpuMode ? "auto",
  allowSoftwareRendering ? false,
  memoryMiB ? null,
  environment ? { },
  nativeEnvironment ? { },
}:
let
  render = import ./render.nix lib;
  nativeTools = buildEnv {
    name = "x86-on-arm-native-tools";
    paths = [
      bash
      coreutils
      util-linux
      pciutils
      pulseaudio
      lsb-release
      zenity
      dbus
    ];
    pathsToLink = [ "/bin" ];
  };
  init = writeShellApplication {
    name = "x86-on-arm-prepare-vm";
    runtimeInputs = [
      coreutils
      util-linux
    ];
    text = render ../guest/prepare-vm.sh {
      inherit nativeTools glibc;
      inherit (stack) image;
      inherit (stack.image) alsaConfig;
    };
  };
  userInit = writeShellApplication {
    name = "x86-on-arm-prepare-session";
    text = ''
      exec ${python3}/bin/python3 ${../guest/session.py} ${stack.image} \
        ${stack.fex}/bin/FEXServer ${dbus}/bin/dbus-daemon ${dbus}/share/dbus-1/session.conf
    '';
  };
  thunks = writeText "x86-on-arm-thunks.json" (
    builtins.toJSON {
      ThunksDB = lib.genAttrs [ "GL" "EGL" "Vulkan" "drm" "asound" "WaylandClient" ] (_: 1);
    }
  );
  settings = writeText "x86-on-arm.json" (
    builtins.toJSON {
      schema = 1;
      inherit
        backend
        gpuMode
        allowSoftwareRendering
        memoryMiB
        environment
        nativeEnvironment
        ;
      rootfs = toString stack.image;
      nativeVulkanDirectory = "${mesa}/share/vulkan/icd.d";
      thunkConfig = toString thunks;
      # FEX expects repeated JSON keys for string arrays.
      nativeConfig = toString (
        writeText "x86-on-arm-native.json" (
          ''{"Config":{''
          + lib.concatStringsSep "," (
            lib.mapAttrsToList (
              key: value: ''"HostEnv":${builtins.toJSON "${key}=${value}"}''
            ) nativeEnvironment
          )
          + "}}"
        )
      );
      fex = lib.getExe' stack.fex "FEXBash";
      muvm = lib.getExe stack.muvm;
      prepareVM = lib.getExe init;
      prepareSession = lib.getExe userInit;
      sleep = lib.getExe' coreutils "sleep";
      true = lib.getExe' coreutils "true";
      systemctl = lib.getExe' systemd "systemctl";
      systemdRun = lib.getExe' systemd "systemd-run";
      versions = {
        fex = stack.fex.version;
        muvm = stack.muvm.version;
        nixpkgs = lib.version;
      };
    }
  );
in
stdenvNoCC.mkDerivation {
  pname = "x86-on-arm";
  version = "0.1.0";
  src = ../runtime;
  dontBuild = true;
  installPhase = ''
    mkdir -p "$out/lib" "$out/bin" "$out/share/x86-on-arm"
    cp -r x86_on_arm "$out/lib/"
    cp ${settings} "$out/share/x86-on-arm/config.json"
    cat > "$out/bin/x86-arm" <<EOF
    #!${python3}/bin/python3
    import sys
    sys.path.insert(0, "$out/lib")
    from x86_on_arm.cli import main
    sys.exit(main("$out/share/x86-on-arm/config.json"))
    EOF
    chmod +x "$out/bin/x86-arm"
  '';
  passthru = {
    inherit
      stack
      settings
      thunks
      init
      ;
  };
  meta = {
    description = "Run x86 and x86-64 applications on ARM64 Linux";
    platforms = [ "aarch64-linux" ];
    mainProgram = "x86-arm";
    license = lib.licenses.mit;
  };
}
