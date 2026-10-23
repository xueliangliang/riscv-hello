#!/usr/bin/env python3
"""Check real per-hart restoration with QEMU's debugger, then finish the demo."""
import os
from pathlib import Path
import socket
import subprocess
import time
from test import command, check, symbols, PASS


def run_debugger(args, log, timeout=30):
    """Preserve failure evidence too: TimeoutExpired.stdout can be bytes."""
    try:
        result = subprocess.run(args, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True,
                                timeout=timeout)
    except subprocess.TimeoutExpired as error:
        output = error.stdout or b""
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        log.write_text(output)
        print(output, end="", flush=True)
        print(f"FAIL: GDB timed out after {timeout}s; partial output: {log}",
              flush=True)
        raise
    log.write_text(result.stdout)
    print(result.stdout, end="", flush=True)
    return result


def run_hart(hart):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    log = Path(f"build/lesson08/gdb-hart{hart}-uart.log")
    with log.open("w") as serial:
        process = subprocess.Popen(command("build/lesson08/disk.img") +
                                   ["-S", "-gdb", f"tcp:127.0.0.1:{port}"],
                                   stdin=subprocess.DEVNULL, stdout=serial,
                                   stderr=subprocess.STDOUT)
        try:
            time.sleep(0.1)
            assert process.poll() is None
            result = run_debugger([os.environ.get("GDB", "gdb-multiarch"), "-q", "-batch",
                                   "-ex", "file build/lesson08/kernel.elf",
                                   "-ex", f"target remote 127.0.0.1:{port}",
                                   "-ex", f"set $target_hart = {hart}",
                                   "-x", "lessons/08/switch.gdb"],
                                  Path(f"build/lesson08/gdb-hart{hart}.log"))
            assert result.returncode == 0
            assert f"PASS: GDB hart={hart} timer restoration" in result.stdout
            status = process.wait(timeout=15)
            check(subprocess.CompletedProcess([], status, log.read_text()), symbols())
            assert PASS in log.read_text()
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()


if __name__ == "__main__":
    for hart in range(2):
        run_hart(hart)
    print("PASS: GDB checked timer restoration on BOTH harts in separate disk boots.")
