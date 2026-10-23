#!/usr/bin/env python3
import os
from pathlib import Path
import socket
import subprocess
import threading
import time
from run import command


def run_debugger(args, log, timeout=25):
    """Timeouts fail too, but their partial output must survive for diagnosis."""
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


def main():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    symbols = subprocess.check_output([os.environ.get("NM", "riscv64-linux-gnu-nm"),
                                       "build/lesson09/user.elf"], text=True)
    idle = next(line.split()[0] for line in symbols.splitlines() if line.endswith(" idle_loop"))
    serial_path = Path("build/lesson09/gdb-uart.log")
    with serial_path.open("wb") as serial:
        guest = subprocess.Popen(command() + ["-S", "-gdb", f"tcp:127.0.0.1:{port}"],
                                 stdin=subprocess.PIPE, stdout=serial, stderr=serial)
        def delayed_character():
            end = time.monotonic() + 10
            while time.monotonic() < end:
                if b"09> " in serial_path.read_bytes():
                    time.sleep(0.3)
                    guest.stdin.write(b"e")
                    guest.stdin.flush()
                    return
                time.sleep(0.05)
        writer = threading.Thread(target=delayed_character, daemon=True)
        writer.start()
        try:
            time.sleep(0.1)
            debug = run_debugger([os.environ.get("GDB", "gdb-multiarch"), "-q", "-batch",
                                    "-ex", "file build/lesson09/kernel.elf",
                                    "-ex", f"set $idle_pc = 0x{idle}",
                                    "-ex", f"target remote 127.0.0.1:{port}",
                                    "-x", "lessons/09/irq.gdb"],
                                 Path("build/lesson09/gdb.log"))
            assert debug.returncode == 0 and "PASS: GDB real idle UART IRQ" in debug.stdout
            writer.join(timeout=1)
            guest.stdin.write(b"cho gdb-woke\r")
            guest.stdin.flush()
            end = time.monotonic() + 5
            while b"echo: gdb-woke" not in serial_path.read_bytes():
                assert time.monotonic() < end, "GDB continuation did not execute command"
                time.sleep(0.05)
            guest.stdin.write(b"shutdown\r")
            guest.stdin.flush()
            assert guest.wait(timeout=5) == 0
            assert b"shutdown: explicit user request" in serial_path.read_bytes()
        finally:
            if guest.poll() is None:
                guest.kill()
                guest.wait()
            guest.stdin.close()


if __name__ == "__main__":
    main()
