final: prev:
let
  guests = final.x86pkgs;
  stack = final.x86-on-arm-components;
in
(import ./x86pkgs.nix final prev)
// {
  x86-on-arm-components = rec {
    inherit guests;
    image = final.callPackage ../guest/image.nix { inherit guests; };
    fex = final.callPackage ../compat/fex.nix {
      upstream = prev.fex;
      inherit (image) thunkLibraryDirs;
    };
    muvm = final.callPackage ../compat/muvm.nix {
      upstream = prev.muvm.override {
        inherit fex;
        libkrun = prev.libkrun.overrideAttrs (old: {
          patches = (old.patches or [ ]) ++ [ ../compat/patches/libkrun/x11-socket.patch ];
        });
      };
    };
  };
  x86-on-arm = final.callPackage ./runtime.nix { inherit stack; };
  x86-on-arm-steam = (final.callPackage ./applications.nix { }).steam;
  x86-on-arm-wine = (final.callPackage ./applications.nix { }).wine;
}
