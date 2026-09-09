# Runs in a private user/mount namespace, with a synthetic host filesystem.
set -euo pipefail
work=$(mktemp -d)
root=
cleanup() {
    if [[ -n "$root" ]] && mountpoint -q "$root"; then
        umount -R "$root" || return
    fi
    rm -rf "$work"
}
trap cleanup EXIT

for layout in split merged; do
    root="$work/$layout"
    mkdir -p "$root"/{usr/bin,usr/share,etc,run,nix/store,proc,dev}
    if [[ "$layout" == merged ]]; then
        ln -s usr/bin "$root/bin"
    else
        mkdir "$root/bin"
    fi
    touch "$root/usr/share/host-only"
    printf 'NAME=fixture\nID=fixture\n' > "$root/etc/os-release"
    mount --bind "$root" "$root"
    mount --bind /nix/store "$root/nix/store"
    mount --bind /proc "$root/proc"
    touch "$root/dev/null"
    mount --bind /dev/null "$root/dev/null"
    mount -t tmpfs -o size=16m,noexec tmpfs "$root/run"
    chroot "$root" @init@
    # Expand the mount options inside the synthetic filesystem.
    # shellcheck disable=SC2016
    chroot "$root" @bash@/bin/bash -euc '
        test ! -e /usr/share/host-only
        test -L /usr/bin/env
        test -L /usr/bin/sh
        test -L /usr/bin/lsb_release
        /usr/bin/env /bin/sh -c "test -d /usr/lib64"
        /usr/bin/lsb_release --id
        options=$(/usr/bin/findmnt -n -o VFS-OPTIONS --target /usr)
        [[ ",$options," == *,noexec,* ]]
    '
    umount -R "$root"
done
echo 'PASS bounded native filesystem on split and merged /usr, with noexec /run'
