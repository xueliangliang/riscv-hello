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
from oracle import verify, mutations
from board import main as verify_board


class Guest:
    def __init__(self, name, disk="build/lesson09/disk.img", allow_failure=False):
        self.allow_failure = allow_failure
        self.path = Path("build/lesson09") / name
        self.master, slave = pty.openpty()
        tty.setraw(slave, termios.TCSANOW)
        self.process = subprocess.Popen(command(disk), stdin=slave, stdout=slave,
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
        data = self.until("\r\n09> ")
        if expected is not None:
            assert expected in data, (expected, data)
        return data

    def close(self):
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait(timeout=2)
        os.close(self.master)
        self.path.write_bytes(self.all)


def run_pid(g, name, arg=0):
    data = g.cmd(f"run {name} {arg}")
    match = re.search(r"run target=\d+ result=(-?\d+)", data)
    assert match, data
    return int(match[1])


def waits(g, pid, status):
    data = g.cmd(f"wait {pid}", f"wait target={pid} result={status}\r\n")
    if status >= 0:
        assert f"wait-call pid=0x0000000000000010 value=0x{pid:016x}" in data
        assert f"reap pid=0x{pid:016x} value=0x{status:016x}" in data
    return data


def stats(g):
    data = g.cmd("stats")
    return {name: (int(a, 16), int(b, 16)) for name, a, b in re.findall(
        r"(rx-[a-z]+) pid=0x([0-9a-f]+) value=0x([0-9a-f]+)", data)}


def scenario():
    g = Guest("pty.log")
    try:
        boot = g.until("09> ")
        assert "both images loaded" in boot and "shell: U-mode" in boot
        first = stats(g)
        # No applications exist: shell blocks in READ and both harts run U idle.
        assert g.read(1.2) == "" and g.process.poll() is None
        g.cmd("echo delayed", "echo: delayed\r\n")
        after = stats(g)
        assert after["rx-irq"][0] > first["rx-irq"][0]
        assert after["rx-wait"][1] > first["rx-wait"][1]
        g.cmd("nonsense", "unknown: nonsense\r\n")
        g.cmd("help", "run spin|sleep|exit [arg]")
        g.cmd("ec\t completed", "echo: completed\r\n")
        g.cmd("echo old", "echo: old\r\n")
        g.cmd("\x1b[A\x7f\x7f\x7fnew", "echo: new\r\n")
        g.cmd("echo draft\x1b[A\x1b[A\x1b[B\x1b[B", "echo: draft\r\n")
        g.cmd("echo ac\x1b[Db\x08b\x1b[C", "echo: abc\r\n")
        g.cmd("echo abxc\x1b[D\x1b[D\x1b[3~", "echo: abc\r\n")
        g.send("echo crlf\r\n")
        g.until("echo: crlf\r\n09> ")
        g.cmd("ps", "job pid=0x0000000000000010")
        g.cmd("jobs", "job pid=0x0000000000000010")
        g.cmd("run absent", "run target=0 result=-4")
        g.cmd("kill 999", "kill target=999 result=-1")
        waits(g, 999, -1)
        spin = run_pid(g, "spin")
        assert spin > 0 and spin & 1
        initial_jobs = g.cmd("jobs")
        initial_progress = int(re.search(rf"job-progress pid=0x{spin:016x} value=0x([0-9a-f]+)", initial_jobs)[1], 16)
        # Shell blocking on remote child must leave its own hart safely idle.
        sleeper = run_pid(g, "sleep", 30)
        output = waits(g, sleeper, 23)
        assert "wait-block" in output
        jobs = g.cmd("jobs")
        hits = re.search(rf"job-hits pid=0x{spin:016x} value=0x([0-9a-f]+)", jobs)
        assert hits and int(hits[1], 16) > 0
        later_progress = int(re.search(rf"job-progress pid=0x{spin:016x} value=0x([0-9a-f]+)", jobs)[1], 16)
        assert later_progress > initial_progress
        g.cmd("sleep 10", "sleep target=10 result=0")
        killed = g.cmd(f"kill {spin}", f"kill target={spin} result=1")
        assert "kill-deferred" in killed
        waits(g, spin, 137)
        waits(g, spin, -1)
        g.cmd(f"kill {spin}", f"kill target={spin} result=-1")
        # Seven EXITED-but-unreaped children consume every non-shell slot.
        children = [(run_pid(g, "exit", 60+i), 60+i) for i in range(7)]
        assert all(pid > 0 for pid, _ in children)
        g.cmd("sleep 5", "sleep target=5 result=0")
        listing = g.cmd("ps")
        for pid, _ in children:
            assert f"job pid=0x{pid:016x} value=0x0000000000000005" in listing
        assert run_pid(g, "exit", 99) == -3
        for pid, status in children:
            waits(g, pid, status)
        replacement = run_pid(g, "exit", 77)
        assert replacement not in [pid for pid, _ in children]
        waits(g, replacement, 77)
        # Shell sleeping prevents consumption but hart0 U idle services IRQs.
        before = stats(g)
        g.send("sleep 100\r")
        g.until("sleep pid=")
        g.send(b"A" * 128 + b"B" * 672)
        time.sleep(0.35)
        g.read(0.1)
        g.until("sleep target=100 result=0", seconds=4)
        g.send("\r")
        g.until("unknown: ")
        g.cmd("echo recovered", "echo: recovered\r\n")
        final = stats(g)
        assert final["rx-ring"][1] > before["rx-ring"][1], (before, final)
        assert final["rx-irq"][1] > 128 * 3 and final["rx-wait"][1] > 0
        assert min(final["rx-wrap"]) > 1
        assert final["rx-irq"][1] == sum(final["rx-ring"]) + final["rx-consumed"][0]
        g.send("shutdown\r")
        g.until("shutdown: explicit user request")
        assert g.process.wait(timeout=3) == 0
    finally:
        g.close()


def concurrent_instances():
    g = Guest("concurrent.log")
    try:
        g.until("09> ")
        children = [run_pid(g, "spin") for _ in range(7)]
        assert children == list(range(17, 24))
        assert run_pid(g, "spin") == -3
        g.cmd("sleep 30", "sleep target=30 result=0")
        first = g.cmd("jobs")
        g.cmd("sleep 30", "sleep target=30 result=0")
        second = g.cmd("jobs")
        for pid in children:
            pattern = rf"job-progress pid=0x{pid:016x} value=0x([0-9a-f]+)"
            before = int(re.search(pattern, first)[1], 16)
            after = int(re.search(pattern, second)[1], 16)
            assert after > before > 0
        for pid in children:
            data = g.cmd(f"kill {pid}")
            assert re.search(rf"kill target={pid} result=[01]\r\n", data)
            waits(g, pid, 137)
        g.cmd("wait 16", "wait target=16 result=-2")
        g.cmd("kill 16", "kill target=16 result=-2")
        g.cmd("run sleep 0", "run target=2 result=-4")
        g.cmd("sleep 0", "sleep target=0 result=-4")
        g.send("shutdown\r")
        g.until("shutdown: explicit user request")
        assert g.process.wait(timeout=3) == 0
    finally:
        g.close()


def main():
    verify_board()
    scenario()
    concurrent_instances()
    transcript = Path("build/lesson09/pty.log").read_bytes().decode()
    verify(transcript)
    Path("build/lesson09/oracle-mutations.log").write_text(mutations(transcript))
    try:
        subprocess.run(command() + ["-S"], input=b"", stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, timeout=0.2)
    except subprocess.TimeoutExpired:
        Path("build/lesson09/timeout-rejected.log").write_text(
            "REJECTED: stopped QEMU timeout is FAIL, not a positive result\n")
    else:
        raise AssertionError("stopped QEMU unexpectedly completed")
    negative = Guest("bad-irq.log", "build/lesson09/disk-bad-irq.img", allow_failure=True)
    try:
        negative.until("09> ")
        assert negative.read(0.15) == ""
        negative.send("echo missing-irq\r")
        fault = negative.until("FAIL: UART IRQ delivery disabled: blocked reader watchdog")
        assert negative.process.wait(timeout=3) == 1
        assert "irq-watchdog pid=0x0000000000000000 value=0x0000000000000006" in fault
        assert "echo: missing-irq" not in fault
    finally:
        negative.close()
    print("PASS: lesson09 real PTY disk shell, idle IRQ wake, exact wait/status, editing execution, exhaustion, overflow recovery; negative IRQ explicit failure")


if __name__ == "__main__":
    main()
