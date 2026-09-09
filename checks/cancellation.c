#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

static const char *directory;
static volatile sig_atomic_t terminated;

static void fail(const char *operation) { perror(operation); exit(90); }
static void on_term(int sig) { (void)sig; terminated = 1; }

static void delay(unsigned milliseconds) {
    struct timespec remaining = { milliseconds / 1000, (milliseconds % 1000) * 1000000L };
    while (nanosleep(&remaining, &remaining) != 0 && errno == EINTR) {}
}

static void marker(const char *name) {
    char path[4096];
    if (snprintf(path, sizeof(path), "%s/%s", directory, name) >= (int)sizeof(path)) exit(91);
    FILE *out = fopen(path, "w");
    if (!out) fail("marker");
    fprintf(out, "%d %d %d\n", getpid(), getpgrp(), getsid(0));
    FILE *membership = fopen("/proc/self/cgroup", "r");
    if (!membership) fail("cgroup");
    char line[4096];
    while (fgets(line, sizeof(line), membership)) fputs(line, out);
    fclose(membership);
    if (fclose(out) != 0) fail("fclose");
}

static void worker(int blocked_output) {
    signal(SIGTERM, SIG_IGN);
    signal(SIGHUP, SIG_IGN);
    marker("ready");
    if (blocked_output) {
        alarm(5);
        char buffer[4096] = {0};
        for (int i = 0; i < 4096; ++i) {
            if (write(STDOUT_FILENO, buffer, sizeof(buffer)) < 0) break;
        }
    }
    delay(2000);
    marker("survived");
    _exit(0);
}

int main(int argc, char **argv) {
    if (argc != 3) return 2;
    const char *mode = argv[1];
    directory = argv[2];
    signal(SIGTERM, SIG_IGN);
    signal(SIGHUP, SIG_IGN);
    marker("leader");
    if (!strcmp(mode, "late-fork")) {
        signal(SIGTERM, on_term);
        marker("ready");
        for (int i = 0; !terminated && i < 500; ++i) delay(10);
        if (!terminated) return 92;
        pid_t child = fork();
        if (child < 0) fail("fork");
        if (!child) {
            if (setsid() < 0) fail("setsid");
            marker("late-fork");
            worker(0);
        }
        return 23;
    }
    pid_t child = fork();
    if (child < 0) fail("fork");
    if (!child) {
        if (!strcmp(mode, "group")) {
            if (setpgid(0, 0) < 0) fail("setpgid");
        } else if (!strcmp(mode, "session") || !strcmp(mode, "orphan")) {
            if (setsid() < 0) fail("setsid");
        }
        if (!strcmp(mode, "orphan")) {
            pid_t intermediate = getpid();
            pid_t grandchild = fork();
            if (grandchild < 0) fail("double fork");
            if (grandchild) _exit(0);
            while (getppid() == intermediate) delay(1);
        }
        if (!strcmp(mode, "closed-output")) {
            close(STDIN_FILENO);
            close(STDOUT_FILENO);
            close(STDERR_FILENO);
        }
        worker(!strcmp(mode, "blocked-output"));
    }
    if (!strcmp(mode, "orphan") || !strcmp(mode, "closed-output")) return 23;
    while (waitpid(child, NULL, 0) < 0) if (errno != EINTR) fail("waitpid");
    return 23;
}
