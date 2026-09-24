/* Preserve the native emulator and the relocated x86 provider across Steam's
 * nested filesystem. This is a native helper; it must never load guest DSOs. */
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

struct command {
    char **args;
    size_t count;
};

static void append(struct command *command, const char *arg) {
    char **args = reallocarray(command->args, command->count + 2, sizeof(*args));
    if (!args) { perror("x86-on-arm: reallocarray"); exit(1); }
    command->args = args;
    command->args[command->count++] = (char *)arg;
    command->args[command->count] = NULL;
}

static void bind_directory(struct command *command, const char *source, const char *dest) {
    append(command, "--ro-bind");
    append(command, source);
    append(command, dest);
}

static bool directory(const char *path) {
    struct stat st;
    return stat(path, &st) == 0 && S_ISDIR(st.st_mode);
}

int main(int argc, char **argv) {
    /* PressureVessel bundles its setup options into --args FDs, followed by
     * the payload. Keep feature probes (ordinary bwrap invocations) intact. */
    if (argc < 3 || strcmp(argv[1], "--args") != 0) {
        /* Probes need native tools, but the real container must retain its
         * guest PATH instead of finding ARM coreutils before x86 programs. */
        const char *old = getenv("PATH");
        char *path = NULL;
        if (asprintf(&path, "%s:%s", COREUTILS_PATH, old ? old : "") < 0) return 1;
        if (setenv("PATH", path, 1) < 0) { perror("setenv"); return 1; }
        free(path);
        argv[0] = BWRAP;
        execv(argv[0], argv);
    } else {
        struct command command = {0};
        append(&command, BWRAP);
        int payload = 1;
        while (payload + 1 < argc && strcmp(argv[payload], "--args") == 0) {
            append(&command, argv[payload++]);
            append(&command, argv[payload++]);
        }
        /* PressureVessel treats /run as shared with the emulator, but exports
         * the guest driver there. Restore the native driver for FEX's thunks.
         * Both prepare-vm and the guest image provide real driver directories:
         * a symlink export here would redirect the bind into the x86 closure,
         * or be rejected by bubblewrap. Keep /nix native for the emulator too. */
        const char *paths[] = { "/nix", "/run/opengl-driver", "/etc/alsa" };
        for (size_t i = 0; i < sizeof(paths) / sizeof(paths[0]); ++i) {
            if (!directory(paths[i])) continue;
            bind_directory(&command, paths[i], paths[i]);
        }
        const char *root = getenv("FEX_ROOTFS");
        if (!root || root[0] != '/') {
            fputs("x86-on-arm: PressureVessel needs an absolute FEX_ROOTFS\n", stderr);
            return 1;
        }
        const char *providers[] = {
            "/var/pressure-vessel/gfx/main",
            "/run/pressure-vessel/interpreter-root/var/pressure-vessel/gfx/main",
        };
        /* The provider's /run driver directories contain relative links into
         * its /nix closure. Both must survive relocation, for Mesa's libraries
         * and data (including share/drirc.d) in both container views. */
        const char *subdirs[] = { "nix", "run" };
        for (size_t i = 0; i < sizeof(subdirs) / sizeof(subdirs[0]); ++i) {
            char *source = NULL;
            if (asprintf(&source, "%s/%s", root, subdirs[i]) < 0) return 1;
            if (!directory(source)) {
                fprintf(stderr, "x86-on-arm: missing FEX rootfs directory: %s\n", source);
                return 1;
            }
            for (size_t j = 0; j < sizeof(providers) / sizeof(providers[0]); ++j) {
                char *dest = NULL;
                if (asprintf(&dest, "%s/%s", providers[j], subdirs[i]) < 0) return 1;
                bind_directory(&command, source, dest);
            }
            if (strcmp(subdirs[i], "nix") == 0)
                bind_directory(&command, source, "/run/pressure-vessel/interpreter-root/nix");
        }
        for (int i = payload; i < argc; ++i) append(&command, argv[i]);
        execv(command.args[0], command.args);
    }
    perror("x86-on-arm: bubblewrap");
    return 1;
}
