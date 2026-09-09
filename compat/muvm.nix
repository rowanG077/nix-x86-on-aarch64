{ upstream, rustPlatform }:
upstream.overrideAttrs (
  final: old: {
    version = "0.6.0-unstable-2026-08-24";
    src = old.src.override {
      tag = null;
      rev = "c50e79c11eb59fc5d7c18c5598130cf3a05072f2";
      hash = "sha256-439WyB3BEE/tCwIKRswHw/RpaHKNgWzZ/HKzNY0vEW0=";
    };
    patches = (old.patches or [ ]) ++ [
      ./patches/muvm/interactive-stdio.patch
      ./patches/muvm/client-lifetime.patch
      ./patches/muvm/display-number.patch
    ];
    cargoDeps = rustPlatform.fetchCargoVendor {
      inherit (final) pname version src;
      hash = "sha256-vKrf8tTcEjk6b+bOjRjcZHcypdUEh1H0PYFN+GSExRg=";
    };
  }
)
