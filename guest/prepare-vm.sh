set -euo pipefail

work=/run/x86-on-arm/fhs
mkdir -p "$work/etc"
mkdir -p "$work/usr/"{bin,lib,lib32,lib64,share/x86-on-arm/vulkan}

for executable in @nativeTools@/bin/*; do
    ln -s "$executable" "$work/usr/bin/"
done
ln -s @glibc@/share/i18n "$work/usr/share/i18n"
cp @image@/usr/share/x86-on-arm/vulkan/*.json "$work/usr/share/x86-on-arm/vulkan/"

for name in host.conf hostname hosts localtime os-release resolv.conf nsswitch.conf group passwd machine-id services protocols networks gai.conf NIXOS; do
    if [[ -r "/etc/$name" ]]; then
        cp -aL "/etc/$name" "$work/etc/$name"
    fi
done
for name in alsa fonts ssl pki pulse xdg udev; do
    if [[ -d "/etc/$name" ]]; then
        cp -rL "/etc/$name" "$work/etc/$name"
    fi
done
mkdir -p "$work/etc/"{alsa/conf.d,ld.so.conf.d,alternatives,xdg,pulse}
cp @alsaConfig@ "$work/etc/alsa/conf.d/00-x86-on-arm.conf"
for name in ld.so.cache ld.so.conf timezone; do
    [[ -e "$work/etc/$name" ]] || touch "$work/etc/$name"
done

if [[ -d /run/opengl-driver ]]; then
    driver=$(readlink -f /run/opengl-driver)
    ln -sfn "$driver" /run/opengl-driver
fi
mount --bind "$work/usr" /usr
mount --bind "$work/usr/bin" /bin
mount --bind "$work/etc" /etc
