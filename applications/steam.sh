set -euo pipefail
data="${XDG_DATA_HOME:-$HOME/.local/share}/x86-on-arm/steam"
mkdir -p "$data"
# Serialize bootstrap upgrades in Steam's normal data directory.
exec 9>"$data/bootstrap.lock"
flock 9
if [[ ! -f "$data/@version@/bin_steam.sh" ]]; then
    staging=$(mktemp -d "$data/.bootstrap.XXXXXXXX")
    trap 'rm -rf "$staging"' EXIT
    cp -r @bootstrap@/. "$staging/"
    chmod -R u+w "$staging"
    mv "$staging" "$data/@version@"
    trap - EXIT
fi
flock -u 9
exec 9>&-
# Repair a read-only bootstrap archive left by older launchers.
steam_data=$(readlink -e "$HOME/.steam/steam" || true)
if [[ -n "$steam_data" ]]; then
    archive="$steam_data/bootstrap.tar.xz"
    if [[ -f "$archive" && ! -L "$archive" && -O "$archive" && ! -w "$archive" ]]; then
        chmod u+w "$archive"
    fi
fi
export STEAMOS=1 STEAM_RUNTIME=1 PRESSURE_VESSEL_IMPORT_VULKAN_LAYERS=0
export PRESSURE_VESSEL_BWRAP=@bwrap@/bin/x86-arm-bwrap
export PRESSURE_VESSEL_FILESYSTEMS_RO="/nix:/run/opengl-driver${PRESSURE_VESSEL_FILESYSTEMS_RO:+:$PRESSURE_VESSEL_FILESYSTEMS_RO}"
export FEX_MULTIBLOCK="${FEX_MULTIBLOCK:-0}"
# PressureVessel needs the prepared FHS view.
exec @runtime@/bin/x86-arm --backend muvm run "$data/@version@/bin_steam.sh" -cef-force-occlusion "$@"
