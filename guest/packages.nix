# Shared application userspace for the CLI, Wine and Steam.
{ lib, guests }:
let
  steam = guests.steam.args;
in
{
  targetPkgs =
    p:
    lib.filter (package: (package.pname or "") != "steam-unwrapped") (steam.targetPkgs p)
    ++ (with p; [
      curl
      wget
      procps
      python3
      vulkan-tools
      mesa-demos
      dejavu_fonts
      cacert
    ]);
  multiPkgs =
    p:
    steam.multiPkgs p
    ++ (with p; [
      alsa-lib
      alsa-plugins
      libglvnd
      libpulseaudio
      gtk3
      nss
      openssl
      wayland
      mesa
    ]);
}
