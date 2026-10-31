"""Real dbt without its start-up cost, for tests: importing dbt takes seconds per process, and every
pipeline run starts two. A server imports dbt once and forks per invocation; a tiny client script
stands in for the `dbt` executable (`FS_DBT_EXECUTABLE`), so callers still run a process.

  DbtServer.start(directory) -> server     server.executable, server.stop()

The server stops by itself when the process that started it dies.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import socket
import struct
import subprocess
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path

# Runs with -IS: no site-packages, so it starts in milliseconds. Connects with retries because the
# server is still importing dbt when the first invocations arrive.
CLIENT = """#!{python} -IS
import array, json, os, socket, struct, sys, time

request = json.dumps(
    {{"argv": sys.argv[1:], "cwd": os.getcwd(), "env": dict(os.environ)}}
).encode()
conn = socket.socket(socket.AF_UNIX)
deadline = time.monotonic() + 120
while True:
    try:
        conn.connect({path!r})
        break
    except (FileNotFoundError, ConnectionRefusedError):
        if time.monotonic() > deadline:
            sys.exit("dbt server did not start: " + {log!r})
        time.sleep(0.02)
socket.send_fds(conn, [struct.pack("!Q", len(request))], [0, 1, 2])
conn.sendall(request)
code = conn.recv(1)
sys.exit(code[0] if code else 1)
"""


def _read(conn: socket.socket, size: int) -> bytes:
    data = b""
    while len(data) < size:
        chunk = conn.recv(size - len(data))
        if not chunk:
            raise EOFError
        data += chunk
    return data


def _invoke(conn: socket.socket) -> None:
    """In the forked child: become the requested dbt process, then report its exit code."""
    from dbt.cli.main import cli

    header, fds, _, _ = socket.recv_fds(conn, 8, 3)
    request = json.loads(_read(conn, struct.unpack("!Q", header)[0]))
    for target, fd in enumerate(fds):
        os.dup2(fd, target)
        os.close(fd)
    os.environ.clear()
    os.environ.update(request["env"])
    os.chdir(request["cwd"])
    try:
        cli(args=request["argv"], prog_name="dbt")
        code = 0
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 0 if e.code is None else 1
    except BaseException:
        traceback.print_exc()
        code = 1
    logging.shutdown()
    sys.stdout.flush()
    sys.stderr.flush()
    conn.sendall(bytes([code]))
    os._exit(code)


def serve(path: str) -> None:
    import dbt.adapters.postgres  # noqa: F401
    import dbt.cli.main  # noqa: F401

    parent = os.getppid()
    signal.signal(signal.SIGCHLD, signal.SIG_IGN)  # no zombies
    listener = socket.socket(socket.AF_UNIX)
    listener.bind(path)
    listener.listen(64)
    listener.settimeout(5)
    while os.getppid() == parent:
        try:
            conn, _ = listener.accept()
        except TimeoutError:
            continue
        if os.fork() == 0:
            signal.signal(signal.SIGCHLD, signal.SIG_DFL)
            listener.close()
            _invoke(conn)
        conn.close()


@dataclass
class DbtServer:
    process: subprocess.Popen
    executable: str

    @classmethod
    def start(cls, directory: Path) -> DbtServer:
        """`directory` must have a short path: it holds a unix socket (~107 bytes at most)."""
        path, log, client = directory / "s", directory / "server.log", directory / "dbt"
        client.write_text(CLIENT.format(python=sys.executable, path=str(path), log=str(log)))
        client.chmod(0o755)
        with open(log, "w") as out:
            process = subprocess.Popen(
                [sys.executable, "-m", "flight_scanner.testing.dbt_server", str(path)],
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=out,
            )
        return cls(process, str(client))

    def stop(self) -> None:
        self.process.terminate()
        self.process.wait()


if __name__ == "__main__":
    serve(sys.argv[1])
