"""Start shared guest services before any cancellable application request."""

import os
import select
import subprocess
import sys


def main(rootfs, fex_server, dbus_daemon, dbus_config):
    read_fd, write_fd = os.pipe()
    server = None
    try:
        try:
            server = subprocess.Popen(
                [fex_server, "--foreground", "--wait_pipe", str(write_fd)],
                env=os.environ | {"FEX_ROOTFS": rootfs},
                stdin=subprocess.DEVNULL,
                pass_fds=(write_fd,),
            )
        finally:
            os.close(write_fd)
        if not select.select([read_fd], [], [], 15)[0]:
            raise RuntimeError("FEXServer did not become ready")
        if os.read(read_fd, 8) or server.poll() is not None:
            raise RuntimeError("FEXServer exited during session startup")
        subprocess.run(
            [
                dbus_daemon,
                "--config-file=" + dbus_config,
                "--fork",
                f"--address=unix:path=/run/user/{os.getuid()}/bus",
            ],
            check=True,
        )
    except BaseException:
        if server is not None and server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()
        raise
    finally:
        os.close(read_fd)


if __name__ == "__main__":
    main(*sys.argv[1:])
