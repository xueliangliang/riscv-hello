#!/usr/bin/env python3
"""Run checked switch.gdb against a real, disk-booted, stopped QEMU."""
import os
from pathlib import Path
import socket
import subprocess
import time
from test import command

with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
with Path("build/lesson07/gdb-uart.log").open("w") as serial:
    process = subprocess.Popen(command("build/lesson07/disk.img") +
                               ["-S", "-gdb", f"tcp:127.0.0.1:{port}"],
                               stdin=subprocess.DEVNULL, stdout=serial,
                               stderr=subprocess.STDOUT)
    try:
        # A failed early launch is not silently accepted as a missing breakpoint.
        time.sleep(0.1)
        assert process.poll() is None
        result = subprocess.run([os.environ.get("GDB", "gdb-multiarch"), "-q", "-batch",
                                 "-ex", "file build/lesson07/kernel.elf",
                                 "-ex", f"target remote 127.0.0.1:{port}",
                                 "-x", "lessons/07/switch.gdb"],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, timeout=15)
        Path("build/lesson07/gdb.log").write_text(result.stdout)
        print(result.stdout, end="")
        assert result.returncode == 0
        assert "PASS: GDB observed A timer trap -> B frame -> B SP/sepc at sret." in result.stdout
        assert process.wait(timeout=10) == 0
        assert "PASS: lesson07 preemptive scheduler and lifecycle." in Path("build/lesson07/gdb-uart.log").read_text()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
