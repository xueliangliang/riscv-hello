#!/usr/bin/env python3
"""Observe an actual type-4 completion; never break a shared sret epilogue."""
import hashlib
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
from run import command
from test import Guest


class DebuggerSession:
    """One fresh log and one reaped child, including pre-communicate failures."""
    def __init__(self, log):
        self.log = Path(log)
        self.log.write_bytes(b"")
        self.process = None
        self.output = None

    def __enter__(self):
        return self

    def start(self, argv):
        self.process = subprocess.Popen(argv, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT)

    def collect(self, timeout=15):
        assert self.process is not None, "debugger not started"
        try:
            self.output, _ = self.process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            # communicate() after kill returns the complete accumulated bytes,
            # not just the suffix; do not duplicate TimeoutExpired.output.
            self.process.kill()
            self.output, _ = self.process.communicate()
            self.log.write_bytes(self.output)
            raise
        self.log.write_bytes(self.output)
        return self.output

    def __exit__(self, kind, error, traceback):
        try:
            if self.process is not None and self.output is None:
                if self.process.poll() is None:
                    self.process.kill()
                self.output, _ = self.process.communicate()
                self.log.write_bytes(self.output)
        finally:
            if error is not None:
                with self.log.open("ab") as stream:
                    stream.write(f"\nFAIL GDB gate: {kind.__name__}: {error}\n".encode(errors="replace"))
        return False


def main():
    # Truncate before fixture lookup, launch, or any guest wait can fail.
    with DebuggerSession("build/lesson10/gdb-flush.log") as debugger:
        base = Path("build/lesson10/disk.img")
        before = hashlib.sha256(base.read_bytes()).hexdigest()
        try:
            return check_flush(debugger)
        finally:
            assert hashlib.sha256(base.read_bytes()).hexdigest() == before


def check_flush(debugger):
    base = Path("build/lesson10/disk.img")
    with tempfile.TemporaryDirectory(prefix="lesson10-gdb-") as scratch:
        scratch = Path(scratch)
        disk = scratch / "disk.img"
        shutil.copyfile(base, disk)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        commands = scratch / "flush.gdb"
        commands.write_text(f"""set pagination off
set confirm off
set remotetimeout 10
file build/lesson10/kernel.elf
target remote 127.0.0.1:{port}
break block_completion_observed if request_header.type == 4
continue
python
import gdb
def integer(expr):
    return int(gdb.parse_and_eval(expr))
assert integer('request_header.type') == 4
assert integer('request_header.reserved') == 0
assert integer('request_header.sector') == 0
assert integer('descriptors[0].address') == integer('&request_header')
assert integer('descriptors[0].length') == 16
assert integer('descriptors[0].flags') == 1
assert integer('descriptors[0].next') == 2
assert integer('descriptors[2].length') == 1
assert integer('descriptors[2].flags') == 2
assert integer('descriptors[2].next') == 0
assert integer('descriptors[2].address') == integer('&request_status')
assert integer('request_status') == 0
assert integer('used_ring.index') == integer('last_used_index')
assert integer('used_ring.ring[(last_used_index - 1) % 8].id') == 0
assert integer('used_ring.ring[(last_used_index - 1) % 8].length') == 1
print('PASS GDB: actual FLUSH type4 header16 -> status1, no data, used id0 length1 status0')
end
print request_header
print descriptors[0]
print descriptors[2]
print used_ring
print request_status
detach
quit
""")
        opts = command(str(disk)) + ["-S", "-gdb", f"tcp:127.0.0.1:{port}"]
        g = Guest("gdb-uart.log", str(disk), options=opts)
        try:
            debugger.start([os.environ.get("GDB", "gdb-multiarch"), "-q", "-batch", "-x", str(commands)])
            g.until("10> ", 10)
            g.send("fwrite proof durable\r")
            output = debugger.collect(timeout=15)
            assert debugger.process.returncode == 0 and b"PASS GDB: actual FLUSH" in output, output.decode(errors="replace")
            g.until("fwrite target=0 result=7\r\n10> ")
            g.cmd("echo after-debugger", "echo: after-debugger\r\n")
            g.shutdown()
        finally:
            g.close()
    print("PASS lesson10 GDB: validated device FLUSH completion, detach, live IRQ echo, shutdown")


if __name__ == "__main__":
    main()
