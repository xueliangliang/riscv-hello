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
from decode import decode, report
import hashlib
import json
import shutil
import signal
import struct
import tempfile
from run import disk_lock



class Guest:
    def __init__(self, name, disk="build/lesson10/disk.img", allow_failure=False, options=None):
        self.allow_failure = allow_failure
        self.path = Path("build/lesson10") / name
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

    def cmd(self, text, expected=None):
        self.send(text + "\r")
        data = self.until("\r\n10> ")
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
    match = re.search(r"\r\n(.*?)\r\ncat target=0 result=0\r\n10> ", normalized, re.S)
    assert match, ("missing cat content/status/EOF", normalized[-500:])
    return match[1].encode("ascii")


def assert_cat(text, expected):
    assert cat_content(text) == expected, "cat exact byte/EOF mismatch"


def assert_write(text, size):
    assert f"\r\nfwrite target=0 result={size}\r\n10> " in text, "write return mismatch"


def assert_rm(text, result=0):
    assert f"\r\nrm target=0 result={result}\r\n10> " in text, "rm result mismatch"


def listing_files(text):
    """Name -> reported size parsed from one real `ls` transcript."""
    found = {name: int(size, 16)
             for name, size in re.findall(r"file: ([A-Za-z0-9_.-]+) size=0x([0-9a-f]{16})", text)}
    assert found, ("missing listing lines", text[-500:])
    return found


def assert_listing(text, expected):
    """Exact reported names and sizes, so a wrong size alone is caught."""
    assert listing_files(text) == {name: len(content) for name, content in expected.items()}, \
        "listing name/size mismatch"


def fs_stats(text):
    match = re.search(r"fsinfo: reads=0x([0-9a-f]+) writes=0x([0-9a-f]+) flushes=0x([0-9a-f]+) healthy=0x([0-9a-f]+)", text)
    assert match, text
    return tuple(int(n, 16) for n in match.groups())


def raw_check(disk, expected, protected):
    raw = Path(disk).read_bytes()
    assert raw[:257 * 512] == protected, "boot-reserved bytes changed"
    files = decode(disk)
    assert set(files) == set(expected), (set(files), set(expected))
    for name, content in expected.items():
        entry = files[name]
        assert entry["size"] == len(content), (name, "logical size")
        assert entry["content"] == content, (name, "raw exact bytes")
        # Every successful write zero-pads its whole 4096-byte extent, so the
        # bytes between logical size and extent end must be zero for ALL files.
        start = entry["lba"] * 512 + entry["size"]
        tail = raw[start:(entry["lba"] + 8) * 512]
        assert len(tail) == 4096 - len(content), (name, "extent tail length")
        assert not any(tail), (name, "padding beyond logical size not zero")
    # Slot0 rewrite to three bytes must not expose any old suffix on disk.
    if "gamma" in files:
        assert files["gamma"]["slot"] == 1, "deleted middle slot not reused"
    if "reused" in files:
        assert files["reused"]["slot"] == 6, "deleted extent not reused"
    return report(files)


def negative(name, disk, options=None):
    before = hashlib.sha256(Path(disk).read_bytes()).hexdigest()
    g = Guest(f"negative-{name}.log", str(disk), True, options)
    try:
        g.until("FAIL: filesystem mount rejected", 8)
        g.process.wait(timeout=3)
        assert g.process.returncode == 1, g.all
        assert b"10> " not in g.all and b"shutdown: explicit" not in g.all
    finally:
        g.close()
    assert hashlib.sha256(Path(disk).read_bytes()).hexdigest() == before, name
    return bytes(g.all)


def scenario(directory):
    disk = directory / "persistent.img"
    shutil.copyfile("build/lesson10/disk.img", disk)
    protected = disk.read_bytes()[:257 * 512]
    expected = {}
    transcripts = {}
    g = Guest("cold-boot1.log", str(disk))
    try:
        boot = g.until("10> ")
        assert "both images loaded" in boot and "fs: mounted" in boot
        assert "hart-online pid=0x0000000000000001" in boot
        # Idle IRQ wake is real, with both harts out of runnable user work.
        first = g.cmd("stats")
        assert g.read(1.2) == "" and g.process.poll() is None
        g.cmd("echo delayed", "echo: delayed\r\n")
        after = g.cmd("stats")
        def counter(text, name):
            return tuple(int(v, 16) for v in re.search(rf"{name} pid=0x([0-9a-f]+) value=0x([0-9a-f]+)", text).groups())
        assert counter(after, "rx-irq")[0] > counter(first, "rx-irq")[0]
        assert counter(after, "rx-wait")[1] > counter(first, "rx-wait")[1]
        g.cmd("ec\t complete", "echo: complete\r\n")
        g.cmd("echo old", "echo: old\r\n")
        g.cmd("\x1b[A\x7f\x7f\x7fnew", "echo: new\r\n")
        g.cmd("echo ac\x1b[Db\x1b[C", "echo: abc\r\n")
        g.cmd("ps", "job pid=0x0000000000000010")
        output = g.cmd("run sleep 20")
        pid = int(re.search(r"run target=2 result=(\d+)", output)[1])
        g.cmd(f"wait {pid}", f"wait target={pid} result=23\r\n")
        output = g.cmd("run exit 31")
        pid = int(re.search(r"run target=3 result=(\d+)", output)[1])
        g.cmd(f"wait {pid}", f"wait target={pid} result=31\r\n")
        for name, value in [("alpha", "longer-original-value"), ("beta", "distinct-second-file")]:
            result = g.cmd(f"fwrite {name} {value}")
            assert_write(result, len(value))
            expected[name] = value.encode()
            output = g.cmd(f"cat {name}")
            assert_cat(output, expected[name])
            transcripts[name] = output
        # Reopen replacement truncates, but read-existing does not create.
        result = g.cmd("fwrite alpha xyz")
        assert_write(result, 3)
        expected["alpha"] = b"xyz"
        transcripts["short"] = g.cmd("cat alpha")
        assert_cat(transcripts["short"], b"xyz")
        g.cmd("cat no-such-file", "cat target=0 result=-10")
        removed = g.cmd("rm beta", "rm target=0 result=0")
        assert_rm(removed)
        del expected["beta"]
        g.cmd("cat beta", "cat target=0 result=-10")
        g.cmd("fwrite gamma replacement", "fwrite target=0 result=11")
        expected["gamma"] = b"replacement"
        g.cmd("ls", "file: alpha size=0x0000000000000003")
        listing = g.cmd("ls")
        assert_listing(listing, expected)
        stats = fs_stats(g.cmd("fsinfo"))
        assert stats[0] >= 3 and stats[1] > 0 and stats[2] > 0 and stats[3] == 1
        g.shutdown()
    finally:
        g.close()
    raw_check(disk, expected, protected)
    # fstest has a fresh 16-slot budget: preserve shell disk separately.
    patterns_disk = directory / "patterns.img"
    shutil.copyfile("build/lesson10/disk.img", patterns_disk)
    pattern = bytes(33 + (i * 17 + 7) % 90 for i in range(4096))
    patterns = {f"b{n}": pattern[:n] for n in (511, 512, 513, 1024, 4096)}
    patterns.update(short=pattern[:3], reused=pattern[:513])
    g = Guest("api-patterns.log", str(patterns_disk))
    try:
        g.until("10> ")
        g.cmd("fstest", "fstest: exact bytes, bounds, EOF, handles, capacity PASS")
        for name, content in patterns.items():
            output = g.cmd(f"cat {name}")
            assert_cat(output, content)
        assert fs_stats(g.cmd("fsinfo"))[2] >= 60
        g.shutdown()
    finally:
        g.close()
    raw_check(patterns_disk, patterns, protected)
    # TWO more independent QEMU processes read the SAME writable disk.
    for boot_number in (2, 3):
        before = disk.read_bytes()
        g = Guest(f"cold-boot{boot_number}.log", str(disk))
        try:
            g.until("10> ")
            for name, content in expected.items():
                output = g.cmd(f"cat {name}")
                assert_cat(output, content)
                if boot_number == 3:
                    transcripts["cold"] = output
            assert fs_stats(g.cmd("fsinfo"))[2] >= 2
            g.shutdown()
        finally:
            g.close()
        assert disk.read_bytes() == before, "read-only API session altered disk"
        raw_check(disk, expected, protected)
    g = Guest("cold-api-verify.log", str(patterns_disk))
    try:
        g.until("10> ")
        g.cmd("fsverify", "fsverify: persisted exact patterns PASS")
        for name, content in patterns.items():
            assert_cat(g.cmd(f"cat {name}"), content)
        g.shutdown()
    finally:
        g.close()
    report_data = {"shell": raw_check(disk, expected, protected),
                   "patterns": raw_check(patterns_disk, patterns, protected)}
    Path("build/lesson10/raw-decoder.json").write_text(json.dumps(report_data, indent=2) + "\n")
    # Oracle mutations use actual captured successful outputs, not invented logs.
    def rejects(fn):
        try:
            fn()
        except AssertionError:
            return
        raise AssertionError("oracle accepted corrupted evidence")
    rejects(lambda: assert_cat(transcripts["alpha"].replace("longer-original-value", "longer-original-valuf"), b"longer-original-value"))
    rejects(lambda: assert_cat(transcripts["short"].replace("xyz\r\ncat", "xyzSTALE\r\ncat"), b"xyz"))
    rejects(lambda: assert_cat(transcripts["short"].replace("result=0", "result=-14"), b"xyz"))
    rejects(lambda: assert_cat(transcripts["cold"].replace("replacement", "replacemenX"), b"replacement"))
    rejects(lambda: assert_write(result.replace("result=3", "result=2"), 3))
    # Only the reported size text changes; the transcript is otherwise the real one.
    rejects(lambda: assert_listing(listing.replace("size=0x0000000000000003", "size=0x0000000000000004"), expected))
    rejects(lambda: assert_rm(removed.replace("result=0", "result=-14")))
    rejects(lambda: raw_check(disk, dict(expected, alpha=b"bad"), protected))
    Path("build/lesson10/oracle-mutations.log").write_text("PASS: exact-content/status/EOF/listing-size/rm-status/cross-boot/write-count/raw-content mutations rejected\n")
    # Keep only disposable snapshots as evidence; fixture and live state are untouched.
    shutil.copyfile(disk, "build/lesson10/evidence-shell.img")
    shutil.copyfile(patterns_disk, "build/lesson10/evidence-patterns.img")


def malformed(directory):
    base = bytearray(Path("build/lesson10/disk.img").read_bytes())
    meta = 512 * 512
    def live(image, slot, name=b"ok", size=1, sector=None):
        start = meta + 512 + slot * 64
        image[start:start + len(name)] = name
        struct.pack_into("<III", image, start + 32, 1, size, 1024 + slot * 8 if sector is None else sector)
        return start
    cases = {}
    for name, offset, value in [("magic", meta, 0), ("version", meta + 8, 2),
                                ("header-reserved", meta + 64, 1),
                                ("unused-record", meta + 512, 1)]:
        image = base.copy()
        image[offset] = value
        cases[name] = image
    for name in ("used", "size", "offset", "reserved", "name-padding", "name-unsafe", "name-empty", "name-unterminated", "duplicate"):
        image = base.copy()
        start = live(image, 0)
        if name == "used":
            struct.pack_into("<I", image, start + 32, 2)
        elif name == "size":
            struct.pack_into("<I", image, start + 36, 4097)
        elif name == "offset":
            struct.pack_into("<I", image, start + 40, 80)
        elif name == "reserved":
            image[start + 63] = 1
        elif name == "name-padding":
            image[start + 4] = 1
        elif name == "name-unsafe":
            image[start] = 47
        elif name == "name-empty":
            image[start:start + 32] = bytes(32)
        elif name == "name-unterminated":
            image[start:start + 32] = b"a" * 32
        else:
            live(image, 1)
        cases[name] = image
    count = len(cases)
    for name, image in cases.items():
        disk = directory / f"bad-{name}.img"
        disk.write_bytes(image)
        try:
            decode(disk)
        except AssertionError:
            pass
        else:
            raise AssertionError(f"independent decoder accepted {name}")
        negative(name, disk)
    disk = directory / "readonly.img"
    shutil.copyfile("build/lesson10/disk.img", disk)
    negative("readonly", disk, command(str(disk), readonly=True))
    disk = directory / "no-flush.img"
    shutil.copyfile("build/lesson10/disk-no-flush.img", disk)
    negative("no-flush-injection", disk)
    return count


def io_errors(directory):
    # Real QEMU blkdebug EIO -> device status=IOERR, not a pretend C return.
    for kind, event, sector in [("read", "read_aio", 512), ("write", "write_aio", 1024), ("flush", "flush_to_disk", None)]:
        disk = directory / f"io-{kind}.img"
        shutil.copyfile("build/lesson10/disk.img", disk)
        config = directory / f"{kind}.conf"
        text = f'[inject-error]\nevent = "{event}"\nerrno = "5"\nonce = "on"\n'
        if sector is not None:
            text += f'sector = "{sector}"\n'
        config.write_text(text)
        opts = command(f"blkdebug:{config}:{disk}", device_extra=",werror=report,rerror=report")
        if kind == "read":
            log = negative("io-read", disk, opts)
            # Mount rejection alone is not enough: the driver must have seen
            # the device's actual IOERR status byte on the type0 READ request.
            failure = re.search(rb"block: fail-closed code=0x[0-9a-f]{16} "
                                rb"request-type=0x0000000000000000 status=0x0000000000000001", log)
            assert failure, log[-2000:]
            continue
        g = Guest(f"io-error-{kind}.log", str(disk), True, opts)
        try:
            g.until("10> ")
            g.cmd("fwrite failure data", "fwrite target=0 result=-14")
            # Driver/filesystem poison is sticky even though once=on fault is spent.
            g.cmd("fwrite cannot succeed", "fwrite target=0 result=-14")
            assert fs_stats(g.cmd("fsinfo"))[3] == 0
            assert b"status=0x0000000000000001" in g.all, "missing actual device IOERR status"
            assert f"request-type=0x{(1 if kind == 'write' else 4):016x}".encode() in g.all
            g.shutdown(failure=True)
            assert b"FAIL: shutdown FLUSH failed" in g.all
            assert b"shutdown: explicit user request" not in g.all
        finally:
            g.close()



def launcher(directory):
    disk = directory / "launcher.img"
    # Exercise the real make run target, not only test.py's QEMU command helper.
    g = Guest("launcher-first.log", str(disk), options=["make", "--no-print-directory", "run-lesson10", f"LESSON10_ARGS=--disk {disk}"])
    try:
        g.until("10> ")
        g.cmd("fwrite saved launcher-persistent", "fwrite target=0 result=19")
        for reset in (False, True):
            args = ["python3", "lessons/10/run.py", "--disk", str(disk)]
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
    subprocess.run(["make", "--no-print-directory", "lesson10"], check=True, stdout=subprocess.PIPE, timeout=20)
    assert hashlib.sha256(disk.read_bytes()).hexdigest() == digest
    g = Guest("launcher-second.log", str(disk), options=["python3", "lessons/10/run.py", "--disk", str(disk)])
    try:
        g.until("10> ")
        assert_cat(g.cmd("cat saved"), b"launcher-persistent")
        g.shutdown()
    finally:
        g.close()
    assert hashlib.sha256(disk.read_bytes()).hexdigest() == digest
    subprocess.run(["python3", "lessons/10/run.py", "--disk", str(disk), "--reset"], check=True, stdout=subprocess.PIPE, timeout=5)
    assert disk.read_bytes() == Path("build/lesson10/disk.img").read_bytes()
    corrupt = bytearray(disk.read_bytes())
    corrupt[512 * 512] ^= 1
    disk.write_bytes(corrupt)
    digest = hashlib.sha256(corrupt).hexdigest()
    g = Guest("launcher-corrupt.log", str(disk), True, ["python3", "lessons/10/run.py", "--disk", str(disk)])
    try:
        g.until("FAIL: filesystem mount rejected")
        g.process.wait(timeout=3)
        assert g.process.returncode == 1
    finally:
        g.close()
    assert hashlib.sha256(disk.read_bytes()).hexdigest() == digest, "launcher reformatted existing corrupt image"
    Path("build/lesson10/launcher-result.log").write_text("PASS: actual make run, copy once, two locks rejected, build/restart persistence, explicit reset, corrupt existing input untouched\n")

def main():
    fixtures = [Path("build/lesson10/disk.img"), Path("build/lesson10/disk-no-flush.img")]
    hashes = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in fixtures}
    try:
        with tempfile.TemporaryDirectory(prefix="lesson10-") as scratch:
            directory = Path(scratch)
            scenario(directory)
            malformed_count = malformed(directory)
            io_errors(directory)
            launcher(directory)
    finally:
        assert all(hashlib.sha256(p.read_bytes()).hexdigest() == h for p, h in hashes.items()), "protected fixture changed"
    Path("build/lesson10/test-result.json").write_text(json.dumps({"result": "PASS", "fixtures_sha256": {str(p): h for p, h in hashes.items()}, "cold_shell_boots": 3, "cold_pattern_boots": 2, "malformed_images": malformed_count, "real_blkdebug_errors": ["read", "write", "flush"]}, indent=2) + "\n")
    print("PASS lesson10: real syscalls/shell, exact patterns/EOF, three cold boots, independent decoder, malformed/RO/no-FLUSH, real device EIO and fail-closed shutdown")


if __name__ == "__main__":
    main()
