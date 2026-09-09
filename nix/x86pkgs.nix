final: prev: {
  x86pkgs = import prev.path {
    system = "x86_64-linux";
    inherit (prev) config;
    overlays = [ ];
  };
  x86packages = final.x86pkgs;
}
