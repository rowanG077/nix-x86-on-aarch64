set -euo pipefail
export WINEPREFIX="${WINEPREFIX:-${XDG_DATA_HOME:-$HOME/.local/share}/x86-on-arm/wineprefix}"
if [[ "$WINEPREFIX" != /* ]]; then
    echo 'x86-arm-wine: WINEPREFIX must be an absolute path' >&2
    exit 2
fi
(umask 077; mkdir -p "$WINEPREFIX")
export WINEDLLOVERRIDES="${WINEDLLOVERRIDES:-winemenubuilder.exe=d}"
# The guest shell must expand these variables after entering FEX.
# shellcheck disable=SC2016
exec @runtime@/bin/x86-arm shell -c '
    "@wine@/bin/wine" "$@"
    status=$?
    "@wine@/bin/wineserver" -w
    exit "$status"
' wine "$@"
