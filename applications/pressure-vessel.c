/* Preserve the native emulator and the relocated x86 provider across Steam's
 * nested filesystem. This is a native helper; it must never load guest DSOs. */
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static bool directory(const char *path) {
    struct stat st;
    return stat(path, &st) == 0 && S_ISDIR(st.st_mode);
}

int main(int argc, char **argv) {
    if (argc < 3 || strcmp(argv[1], "--args") != 0) {
        const char *old = getenv("PATH");
        char *path = NULL;
        if (asprintf(&path, "%s:%s", COREUTILS_PATH, old ? old : "") < 0) return 1;
        if (setenv("PATH", path, 1) < 0) { perror("setenv"); return 1; }
        free(path);
        argv[0] = BWRAP;
        execv(argv[0], argv);
    } else {
        char **command = calloc((size_t)argc + 19, sizeof(*command));
        if (!command) { perror("calloc"); return 1; }
        size_t count = 0;
        command[count++] = BWRAP;
        command[count++] = "--args";
        command[count++] = argv[2];
        const char *paths[] = { "/nix", "/run/opengl-driver", "/etc/alsa" };
        for (size_t i = 0; i < sizeof(paths) / sizeof(paths[0]); ++i) {
            if (!directory(paths[i])) continue;
            command[count++] = "--ro-bind";
            command[count++] = (char *)paths[i];
            command[count++] = (char *)paths[i];
        }
        const char *root = getenv("FEX_ROOTFS");
        char *store = NULL;
        if (root && asprintf(&store, "%s/nix", root) < 0) return 1;
        if (store && directory(store)) {
            const char *destinations[] = {
                "/var/pressure-vessel/gfx/main/nix",
                "/run/pressure-vessel/interpreter-root/var/pressure-vessel/gfx/main/nix",
                "/run/pressure-vessel/interpreter-root/nix",
            };
            for (size_t i = 0; i < sizeof(destinations) / sizeof(destinations[0]); ++i) {
                command[count++] = "--ro-bind";
                command[count++] = store;
                command[count++] = (char *)destinations[i];
            }
        }
        for (int i = 3; i < argc; ++i) command[count++] = argv[i];
        execv(command[0], command);
    }
    perror("x86-on-arm: bubblewrap");
    return 1;
}
