#!/usr/bin/env python3
"""Disk boots plus an independent lifecycle/log oracle; timeouts always fail."""
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

PASS = "PASS: lesson07 preemptive scheduler and lifecycle."
BOOT = [
    "Lesson 03: M-mode bootloader started.",
    "Boot record validated; loading kernel and shell from disk.",
    "Bootloader: both images loaded; jumping to kernel at 0x80200000.",
    "Lesson 07: single-hart preemptive processes, flat memory.",
]
CHECKS = [
    "check: invalid inputs rejected",
    "check: preemption sleep kill statuses",
    "check: wait ownership generation stacks",
    "check: live and zombie exhaustion",
    "check: reap relaunch complete",
]
EVENT = re.compile(r"(spawn|zombie|reap|sleep|wake|kill|wait-block|wait-return|timer-switch) "
                   r"pid=0x([0-9a-f]{16}) value=0x([0-9a-f]{16})")
PREEMPT = re.compile(r"preempt-loop pc=0x([0-9a-f]{16}) "
                     r"pid=0x([0-9a-f]{16}) value=0x([0-9a-f]{16})")


def command(disk):
    return [os.environ.get("QEMU", "qemu-system-riscv64"),
            "-machine", "virt", "-cpu", "rv64,sstc=true",
            "-global", "virtio-mmio.force-legacy=false", "-smp", "1",
            "-m", "128M", "-display", "none", "-serial", "stdio",
            "-monitor", "none", "-bios", "none",
            "-kernel", "build/lesson03/bootloader.elf",
            "-drive", f"file={disk},if=none,format=raw,id=disk,readonly=on",
            "-device", "virtio-blk-device,drive=disk", "-no-reboot"]


def execute(args, log, timeout=10.0, terminal=False):
    if not terminal:
        try:
            result = subprocess.run(args, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired as error:
            Path(log).write_bytes(error.stdout or b"")
            raise AssertionError("QEMU timeout is failure") from error
    else:
        # Exercise an actual tty, not just PIPE. setsid isolates job control;
        # raw mode avoids terminal CRLF processing and serial echo artifacts.
        master, slave = pty.openpty()
        tty.setraw(slave, termios.TCSANOW)
        process = subprocess.Popen(args, stdin=slave, stdout=slave, stderr=slave,
                                   start_new_session=True)
        os.close(slave)
        chunks = []
        end = time.monotonic() + timeout
        try:
            while True:
                if time.monotonic() >= end:
                    raise AssertionError("PTY QEMU timeout is failure")
                ready, _, _ = select.select([master], [], [], 0.05)
                if ready:
                    try:
                        chunk = os.read(master, 65536)
                    except OSError as error:
                        if error.errno != errno.EIO:
                            raise
                        break
                    if not chunk:
                        break
                    chunks.append(chunk)
                elif process.poll() is not None:
                    break
            status = process.wait(timeout=1)
            result = subprocess.CompletedProcess(args, status, b"".join(chunks).decode())
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            os.close(master)
            Path(log).write_bytes(b"".join(chunks))
    Path(log).write_text(result.stdout)
    return result


def symbols():
    output = subprocess.check_output([os.environ.get("NM", "riscv64-linux-gnu-nm"),
                                      "-n", "build/lesson07/user.elf"], text=True)
    labels = {fields[2]: int(fields[0], 16) for line in output.splitlines()
              if len(fields := line.split()) == 3}
    start = labels["spin_loop"]
    end = labels["spin_loop_end"]
    assert end - start == 12
    disassembly = subprocess.check_output([
        os.environ.get("OBJDUMP", "riscv64-linux-gnu-objdump"), "-d", "-M", "no-aliases",
        "--no-show-raw-insn", f"--start-address={start}", f"--stop-address={end}",
        "build/lesson07/user.elf"], text=True)
    instructions = [match.groups() for line in disassembly.splitlines()
                    if (match := re.fullmatch(r"\s*([0-9a-f]+):\s+(\w+)\s+(.+)", line))]
    assert [op for _, op, _ in instructions] == ["addi", "sd", "jal"], instructions
    assert instructions[0][2] == "s0,s0,1"
    assert instructions[1][2] == "s0,0(a2)"
    assert instructions[2][2].startswith(f"zero,{start:x} ")
    return start, end


def check(result, bounds):
    assert result.returncode == 0, (result.returncode, result.stdout)
    lines = result.stdout.replace("\r\n", "\n").splitlines()
    assert lines[:4] == BOOT
    assert lines[-1] == PASS
    assert lines.count(PASS) == 1
    assert [line for line in lines if line.startswith("check:")] == CHECKS
    live = {}
    generations = {}
    progress = {}
    hits = {}
    entries = {}
    killed = set()
    statuses = []
    reaped = []
    wait_statuses = []
    waiting = None
    switches = []
    high_water = 0
    owner_exits = 0
    for line in lines[4:]:
        match = EVENT.fullmatch(line)
        if match:
            name = match[1]
            pid, value = int(match[2], 16), int(match[3], 16)
            if name == "spawn":
                slot = pid & 15
                generation = pid >> 4
                assert 0 <= slot < 8
                assert all((other & 15) != slot for other in live), "reused unreaped slot"
                assert generation == generations.get(slot, 0) + 1
                generations[slot] = generation
                live[pid] = "live"
                entries[pid] = value
                high_water = max(high_water, len(live))
            elif name == "zombie":
                assert live[pid] in ("live", "sleep")
                live[pid] = "zombie"
                statuses.append((pid, value))
                if entries[pid] == 4:
                    owner_exits += 1
                    assert value == 31
            elif name == "reap":
                assert live[pid] == "zombie"
                assert (pid, value) in statuses
                reaped.append((pid, value))
                del live[pid]
            elif name == "sleep":
                assert live[pid] == "live"
                live[pid] = "sleep"
            elif name == "wake":
                assert live[pid] == "sleep" and pid not in killed
                live[pid] = "live"
            elif name == "kill":
                assert pid not in killed
                assert live[pid] in ("live", "sleep")
                assert value == (3 if live[pid] == "sleep" else 1)
                killed.add(pid)
            elif name == "wait-block":
                assert pid == 16 and value in live and live[value] != "zombie"
                assert waiting is None
                waiting = value
            elif name == "wait-return":
                assert pid == 16
                wait_statuses.append(value)
                if waiting is not None:
                    assert (waiting, value) in statuses
                    waiting = None
            elif name == "timer-switch":
                assert pid != value
                assert live[pid] == "live" and live[value] == "live"
                assert pid not in killed and value not in killed
                switches.append((pid, value))
        elif match := PREEMPT.fullmatch(line):
            pc, pid, value = (int(field, 16) for field in match.groups())
            assert bounds[0] <= pc < bounds[1] and (pc - bounds[0]) % 4 == 0
            assert entries[pid] == 1 and live[pid] == "live" and pid not in killed
            assert value > progress.get(pid, 0)
            progress[pid] = value
            hits[pid] = hits.get(pid, 0) + 1
        elif line == CHECKS[3]:
            assert len(live) == 8 and sum(state == "zombie" for state in live.values()) == 7
        else:
            assert line in CHECKS + [PASS, "controller: start", "worker: sleeping", "worker: woke"], line
    assert live == {16: "live"} and waiting is None
    assert high_water == 8 and owner_exits == 1
    assert set(hits) == {17, 18} and min(hits.values()) >= 2
    assert (17, 18) in switches and (18, 17) in switches
    assert killed == {17, 18, 19}
    expected = [137, 137, 137, 42, 31, 23, *range(60, 67), 77]
    assert wait_statuses == expected, wait_statuses
    assert sorted(statuses) == sorted(reaped)
    assert len(reaped) == len(expected)
    # The killed sleeper never reaches its completion message; the short one does.
    assert lines.count("worker: sleeping") == 2
    assert lines.count("worker: woke") == 1


def reject(action):
    try:
        action()
    except AssertionError:
        return
    raise AssertionError("oracle admitted invalid result")


def main():
    bounds = symbols()
    result = None
    for index in range(3):
        result = execute(command("build/lesson07/disk.img"), f"build/lesson07/positive-{index}.log")
        check(result, bounds)
    assert result is not None
    terminal = execute(command("build/lesson07/disk.img"), "build/lesson07/pty.log", terminal=True)
    check(terminal, bounds)
    negative = execute(command("build/lesson07/disk-bad-context.img"),
                       "build/lesson07/bad-context.log")
    assert negative.returncode == 1
    assert negative.stdout.replace("\r\n", "\n").splitlines()[:4] == BOOT
    assert negative.stdout.replace("\r\n", "\n").splitlines()[-1] == "FAIL: spin context restore"
    assert PASS not in negative.stdout
    reject(lambda: check(negative, bounds))
    for output in (result.stdout + "FAIL: late failure\n", PASS + "\n",
                   result.stdout.replace(CHECKS[3], ""),
                   result.stdout.replace("preempt-loop pc=0x000000008040", "preempt-loop pc=0x000000008050")):
        reject(lambda: check(subprocess.CompletedProcess([], 0, output), bounds))
    for status in (1, 124, -9):
        reject(lambda: check(subprocess.CompletedProcess([], status, result.stdout), bounds))
    reject(lambda: execute(command("build/lesson07/disk.img") + ["-S"],
                           "build/lesson07/timeout-rejected.log", timeout=0.2))
    print(result.stdout, end="")
    print("PASS: lesson07 three disk boots, PTY, broken restore and timeout rejection.")


if __name__ == "__main__":
    main()
