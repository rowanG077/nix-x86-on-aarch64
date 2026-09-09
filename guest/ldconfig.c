/* An x86 entrypoint is required by PressureVessel's architecture probe.
 * Static glibc ldconfig needs QEMU until its FEX startup crash is resolved. */
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

int main(int argc, char **argv) {
    const char *root = getenv("FEX_ROOTFS");
    if (!root || !*root) {
        fputs("ldconfig: FEX_ROOTFS is required\n", stderr);
        return 1;
    }
    char **command = calloc((size_t)argc + 4, sizeof(*command));
    if (!command) { perror("calloc"); return 1; }
    command[0] = QEMU;
    command[1] = LDCONFIG;
    command[2] = "-r";
    command[3] = (char *)root;
    for (int i = 1; i < argc; ++i) command[i + 3] = argv[i];
    unsetenv("LD_LIBRARY_PATH");
    unsetenv("LD_PRELOAD");
    execv(command[0], command);
    perror("ldconfig: exec");
    free(command);
    return 1;
}
