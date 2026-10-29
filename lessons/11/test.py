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
    def __init__(self, name, disk="build/lesson11/disk.img", allow_failure=False, options=None):
        self.allow_failure = allow_failure
        self.path = Path("build/lesson11") / name
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
        data = self.until("\r\n11> ", seconds)
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



def cat_content(text):
    """Only command output between submitted CR and actual EOF/status line."""
    normalized = text.replace("\r\r\n", "\r\n")
    match = re.search(r"\r\n(.*?)\r\ncat target=0 result=0\r\n11> ", normalized, re.S)
    assert match, ("missing cat content/status/EOF", normalized[-500:])
    return match[1].encode("ascii")


def assert_cat(text, expected):
    assert cat_content(text) == expected, "cat exact byte/EOF mismatch"


def assert_write(text, size):
    assert f"\r\nfwrite target=0 result={size}\r\n11> " in text, "write return mismatch"


def assert_rm(text, result=0):
    assert f"\r\nrm target=0 result={result}\r\n11> " in text, "rm result mismatch"



def launcher(directory):
    disk = directory / "launcher.img"
    # Exercise the real make run target, not only test.py's QEMU command helper.
    g = Guest("launcher-first.log", str(disk), options=["make", "--no-print-directory", "run-lesson11", f"LESSON11_ARGS=--disk {disk}"])
    try:
        g.until("11> ")
        g.cmd("fwrite saved launcher-persistent", "fwrite target=0 result=19")
        for reset in (False, True):
            args = ["python3", "lessons/11/run.py", "--disk", str(disk)]
            if reset:
                args += ["--reset"]
            other = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=4)
            assert other.returncode != 0 and b"disk busy:" in other.stdout, other.stdout
        # Separate target: launcher's lock is held for all of QEMU's lifetime.
        g.shutdown()
    finally:
        g.close()
    assert decode(disk)["saved"]["content"] == b"launcher-persistent"
    digest = hashlib.sha256(disk.read_bytes()).hexdigest()
    subprocess.run(["make", "--no-print-directory", "lesson11"], check=True, stdout=subprocess.PIPE, timeout=20)
    assert hashlib.sha256(disk.read_bytes()).hexdigest() == digest
    g = Guest("launcher-second.log", str(disk), options=["python3", "lessons/11/run.py", "--disk", str(disk)])
    try:
        g.until("11> ")
        assert_cat(g.cmd("cat saved"), b"launcher-persistent")
        g.shutdown()
    finally:
        g.close()
    assert hashlib.sha256(disk.read_bytes()).hexdigest() == digest
    subprocess.run(["python3", "lessons/11/run.py", "--disk", str(disk), "--reset"], check=True, stdout=subprocess.PIPE, timeout=5)
    assert disk.read_bytes() == Path("build/lesson11/disk.img").read_bytes()
    corrupt = bytearray(disk.read_bytes())
    corrupt[512 * 512] ^= 1
    disk.write_bytes(corrupt)
    digest = hashlib.sha256(corrupt).hexdigest()
    g = Guest("launcher-corrupt.log", str(disk), True, ["python3", "lessons/11/run.py", "--disk", str(disk)])
    try:
        g.until("FAIL: filesystem mount rejected")
        g.process.wait(timeout=3)
        assert g.process.returncode == 1
    finally:
        g.close()
    assert hashlib.sha256(disk.read_bytes()).hexdigest() == digest, "launcher reformatted existing corrupt image"
    Path("build/lesson11/launcher-result.log").write_text("PASS: actual make run, copy once, two locks rejected, build/restart persistence, explicit reset, corrupt existing input untouched\n")


from oracle import stats
from scenarios import run_scenarios, malformed, negative, pressure, node_pressure

def io_errors(directory):
    # Real QEMU blkdebug EIO -> device status=IOERR, not a pretend C return.
    for kind, event, sector in [("read", "read_aio", 512),
                                ("read-data", "read_aio", 2048),
                                ("write-metadata", "write_aio", 515),
                                ("write-data", "write_aio", 2048),
                                ("flush", "flush_to_disk", None)]:
        disk = directory / f"io-{kind}.img"
        shutil.copyfile("build/lesson11/disk.img", disk)
        if kind == "read-data":
            # A read_aio injection on an empty image can hit the host's RMW
            # read while servicing a guest WRITE. Seed via real U calls first,
            # then fault mount's payload validation READ in a fresh VM.
            seed = Guest("io-read-data-seed.log", str(disk))
            try:
                seed.until("11> ")
                seed.cmd("fwrite seeded payload", "fwrite target=0 result=7")
                seed.shutdown()
            finally:
                seed.close()
        config = directory / f"{kind}.conf"
        text = f'[inject-error]\nevent = "{event}"\nerrno = "5"\nonce = "on"\n'
        if sector is not None:
            text += f'sector = "{sector}"\n'
        config.write_text(text)
        opts = command(f"blkdebug:{config}:{disk}", device_extra=",werror=report,rerror=report")
        if kind in ("read", "read-data"):
            log = negative(Guest, "io-" + kind, disk, opts)
            # Mount rejection alone is not enough: the driver must have seen
            # the device's actual IOERR status byte on the type0 READ request.
            failure = re.search(rb"block: fail-closed code=0x[0-9a-f]{16} "
                                rb"request-type=0x0000000000000000 status=0x0000000000000001", log)
            assert failure, log[-2000:]
            continue
        g = Guest(f"io-error-{kind}.log", str(disk), True, opts)
        try:
            g.until("11> ")
            g.cmd("fwrite failure data", "fwrite target=0 result=-14")
            # Driver/filesystem poison is sticky even though once=on fault is spent.
            g.cmd("fwrite cannot succeed", "fwrite target=0 result=-14")
            assert stats(g.cmd("fsinfo"))["healthy"] == 0
            assert b"status=0x0000000000000001" in g.all, "missing actual device IOERR status"
            request_type = 1 if kind.startswith('write-') else 4
            assert f"request-type=0x{request_type:016x}".encode() in g.all
            g.shutdown(failure=True)
            assert b"FAIL: shutdown FLUSH failed" in g.all
            assert b"shutdown: explicit user request" not in g.all
        finally:
            g.close()




def main():
    fixtures = [Path('build/lesson11/disk.img'), Path('build/lesson11/disk-no-flush.img')]
    hashes = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in fixtures}
    result = Path('build/lesson11/test-result.json')
    result.unlink(missing_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix='lesson11-') as scratch:
            directory = Path(scratch)
            trees = run_scenarios(Guest, directory, assert_cat, assert_write, assert_rm)
            pressure_tree = pressure(Guest, directory)
            node_tree = node_pressure(Guest, directory)
            malformed_count = malformed(Guest, directory)
            for name, source, readonly in [('readonly', fixtures[0], True), ('no-flush', fixtures[1], False)]:
                disk = directory / (name + '.img')
                shutil.copyfile(source, disk)
                negative(Guest, name, disk, command(str(disk), readonly=readonly))
            # Cross-format rejection in both directions, on disposable copies.
            flat = Path('build/lesson10/disk.img').read_bytes()
            image = bytearray(flat)
            image.extend(bytes(8 * 1024 * 1024 - len(image)))
            image[:257 * 512] = fixtures[0].read_bytes()[:257 * 512]
            disk = directory / 'flat10-with-bpt11-kernel.img'
            disk.write_bytes(image)
            log = negative(Guest, 'bpt11-rejects-flat10', disk)
            assert b'Lesson 11:' in log and b'Lesson 10:' not in log
            image = bytearray(fixtures[0].read_bytes())
            image[:257 * 512] = flat[:257 * 512]
            disk = directory / 'bpt11-with-flat10-kernel.img'
            disk.write_bytes(image)
            opts = command(str(disk))
            opts[opts.index('-kernel') + 1] = 'build/lesson10/bootloader.elf'
            log = negative(Guest, 'flat10-rejects-bpt11', disk, opts)
            assert b'Lesson 10:' in log and b'Lesson 11:' not in log
            # A truncated or oversized device must not be admitted even if
            # metadata would otherwise fit/read successfully.
            for name, length in [('short-device', 6 * 1024 * 1024), ('large-device', 9 * 1024 * 1024)]:
                disk = directory / (name + '.img')
                image = fixtures[0].read_bytes()
                disk.write_bytes(image[:length] + bytes(max(0, length - len(image))))
                negative(Guest, name, disk)
            io_errors(directory)
            launcher(directory)
    finally:
        assert all(hashlib.sha256(p.read_bytes()).hexdigest() == h for p, h in hashes.items()), 'protected fixtures changed'
    result.write_text(json.dumps({'result': 'PASS', 'fixtures_sha256': {str(p): h for p, h in hashes.items()},
                                 'tree_height': trees['create']['height'], 'tree_nodes': len(trees['create']['nodes']),
                                 'ordered_files': len(trees['recreate']['files']), 'malformed_images': malformed_count,
                                 'mass_image_cold_boots': len(trees), 'pressure_files': len(pressure_tree['files']),
                                 'pressure_blocks': pressure_tree['used_blocks'], 'node_pressure_nodes': len(node_tree['nodes']),
                                 'real_blkdebug_errors': ['read-metadata', 'read-data', 'write-metadata', 'write-data', 'flush']}, indent=2) + '\n')
    print('PASS lesson11: real U APIs; multilevel B+ splits; ordered pages; chains/seek/append/truncate; delete/reuse/real defrag; independent raw/cold boots; full capacity; corruption/device errors')


if __name__ == '__main__':
    main()
