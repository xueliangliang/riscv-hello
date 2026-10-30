#!/usr/bin/env python3
"""PTY drives the real UART, never a guest command emulator. Timeout FAILS."""
import errno
import os
from pathlib import Path
import pty
import re
import select
import subprocess
import termios
import time
import tty
from run import command
from decode import decode, inspect, report
import hashlib
import json
import shutil
import signal
import struct
import tempfile
from run import disk_lock



class Guest:
    def __init__(self, name, disk="build/lesson14/disk.img", allow_failure=False, options=None):
        self.allow_failure = allow_failure
        self.path = Path("build/lesson14") / name
        self.master, slave = pty.openpty()
        tty.setraw(slave, termios.TCSANOW)
        self.process = subprocess.Popen(options or command(disk), stdin=slave, stdout=slave,
                                        stderr=slave, start_new_session=True)
        os.close(slave)
        self.all = b""

    def read(self, seconds=0.1):
        end = time.monotonic() + seconds
        data = b""
        while time.monotonic() < end:
            if select.select([self.master], [], [], min(0.02, max(0, end-time.monotonic())))[0]:
                try:
                    part = os.read(self.master, 65536)
                except OSError as error:
                    if error.errno == errno.EIO:
                        break
                    raise
                if not part:
                    break
                self.all += part
                data += part
        self.path.write_bytes(self.all)
        assert self.allow_failure or b"FAIL:" not in data, data.decode(errors="replace")
        return data.decode(errors="replace").replace("\r\r\n", "\r\n")

    def until(self, text, seconds=5):
        data = ""
        end = time.monotonic() + seconds
        while text not in data:
            assert time.monotonic() < end, ("timeout FAIL", text, data[-2000:])
            data += self.read()
        return data + self.read(0.05)

    def send(self, text):
        os.write(self.master, text if isinstance(text, bytes) else text.encode())

    def cmd(self, text, expected=None, seconds=10):
        self.send(text + "\r")
        data = self.until("\r\n13> ", seconds)
        if expected is not None:
            assert expected in data, (expected, data)
        return data

    def shutdown(self, failure=False):
        self.send("shutdown\r")
        self.process.wait(timeout=8)
        self.read(0.1)
        assert self.process.returncode == (1 if failure else 0), self.all[-3000:]
        if not failure:
            assert b"shutdown: explicit user request" in self.all

    def close(self):
        # Every guest starts its own process group, including make/launcher children.
        try:
            os.killpg(self.process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        self.process.wait(timeout=2)
        os.close(self.master)
        self.path.write_bytes(self.all)
