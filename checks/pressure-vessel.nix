{ pkgs }:
let
  recorder = pkgs.writeShellScript "record-bwrap" ''
    exec ${pkgs.python3}/bin/python3 ${./pressure-vessel.py} --record "$@"
  '';
in
pkgs.runCommandCC "x86-on-arm-pressure-vessel-check" { } ''
  $CC -D_GNU_SOURCE -Wall -Wextra -Werror -O2 \
    -DBWRAP='"${recorder}"' -DCOREUTILS_PATH='"${pkgs.coreutils}/bin"' \
    ${../applications/pressure-vessel.c} -o wrapper
  ${pkgs.python3}/bin/python3 ${./pressure-vessel.py} "$PWD/wrapper"
  touch "$out"
''
