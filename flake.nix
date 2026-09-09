{
  description = "nix-x86-on-aarch64: x86 Linux applications on AArch64 with a reproducible Nix userspace";
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";

  outputs =
    { self, nixpkgs }:
    let
      system = "aarch64-linux";
      pkgs = import nixpkgs {
        inherit system;
        config.allowUnfree = true;
        overlays = [ self.overlays.default ];
      };
      stack = pkgs.x86-on-arm-components;
    in
    {
      overlays.default = import ./nix/overlay.nix;
      overlays.x86pkgs = import ./nix/x86pkgs.nix;
      nixosModules.default = {
        imports = [ ./nix/module.nix ];
      };
      packages.${system} = {
        default = pkgs.x86-on-arm;
        inherit (stack) fex muvm;
        rootfs = stack.image;
        steam = pkgs.x86-on-arm-steam;
        wine = pkgs.x86-on-arm-wine;
        probes = pkgs.callPackage ./checks/probes.nix { inherit (stack) guests; };
        verify = pkgs.callPackage ./checks/verify.nix {
          runtime = pkgs.x86-on-arm;
          probes = self.packages.${system}.probes;
          inherit (stack) guests;
        };
      };
      checks.${system} = import ./nix/checks.nix { inherit self pkgs; };
      formatter.${system} = pkgs.nixfmt;
      devShells.${system}.default = pkgs.mkShell {
        packages = [
          pkgs.python3
          pkgs.ruff
          pkgs.nixfmt
          pkgs.shellcheck
          pkgs.x86-on-arm
        ];
      };
    };
}
