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


def main():
    base = Path("build/lesson10/disk.img")
    before = hashlib.sha256(base.read_bytes()).hexdigest()
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
        debugger = None
        try:
            debugger = subprocess.Popen([os.environ.get("GDB", "gdb-multiarch"), "-q", "-batch", "-x", str(commands)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            g.until("10> ", 10)
            g.send("fwrite proof durable\r")
            output, _ = debugger.communicate(timeout=15)
            Path("build/lesson10/gdb-flush.log").write_bytes(output)
            assert debugger.returncode == 0 and b"PASS GDB: actual FLUSH" in output, output.decode(errors="replace")
            g.until("fwrite target=0 result=7\r\n10> ")
            g.cmd("echo after-debugger", "echo: after-debugger\r\n")
            g.shutdown()
        finally:
            if debugger and debugger.poll() is None:
                debugger.kill()
                debugger.wait(timeout=3)
            g.close()
    assert hashlib.sha256(base.read_bytes()).hexdigest() == before
    print("PASS lesson10 GDB: validated device FLUSH completion, detach, live IRQ echo, shutdown")


if __name__ == "__main__":
    main()
