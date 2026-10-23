#!/usr/bin/env python3
"""Real disk boots and a host state-machine oracle. No timeout is a pass.

The expected scenario comes from the lesson contract, not kernel structs.
Every valid wait must identify one exact child; return/reap/status are checked
within that transaction, including both immediate and blocking transitions.
"""
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

PASS = "PASS: lesson08 dual-hart execution, locking and lifecycle."
BOOT = [
    "Lesson 03: M-mode bootloader started.",
    "Boot record validated; loading kernel and shell from disk.",
    "Bootloader: both images loaded; jumping to kernel at 0x80200000.",
    "Lesson 08: dual-hart pinned processes, flat memory.",
]
CHECKS = [
    "check: invalid inputs rejected",
    "check: dual-hart preemption sleep remote-kill completion",
    "check: wait ownership generation stacks idle",
    "check: shared counter 8000, two harts, contention, no overlap",
    "check: live and zombie exhaustion",
    "check: reap relaunch complete",
]
EVENT = re.compile(r"([a-z-]+) pid=0x([0-9a-f]{16}) value=0x([0-9a-f]{16})")
PREEMPT = re.compile(r"preempt-hart=0x([0-9a-f]{16}) preempt-loop pc=0x([0-9a-f]{16}) "
                     r"pid=0x([0-9a-f]{16}) value=0x([0-9a-f]{16})")


def command(disk):
    return [os.environ.get("QEMU", "qemu-system-riscv64"),
            "-machine", "virt", "-accel", "tcg,thread=multi", "-cpu", "rv64,sstc=true",
            "-global", "virtio-mmio.force-legacy=false", "-smp", "2",
            "-m", "128M", "-display", "none", "-serial", "stdio",
            "-monitor", "none", "-bios", "none",
            "-kernel", "build/lesson08/bootloader.elf",
            "-drive", f"file={disk},if=none,format=raw,id=disk,readonly=on",
            "-device", "virtio-blk-device,drive=disk", "-no-reboot"]


def execute(args, log, timeout=15.0, terminal=False):
    if not terminal:
        try:
            result = subprocess.run(args, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired as error:
            Path(log).write_bytes(error.stdout or b"")
            raise AssertionError("QEMU timeout is failure") from error
    else:
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
                                      "-n", "build/lesson08/user.elf"], text=True)
    labels = {fields[2]: int(fields[0], 16) for line in output.splitlines()
              if len(fields := line.split()) == 3}
    start, end = labels["spin_loop"], labels["spin_loop_end"]
    assert end - start == 12
    text = subprocess.check_output([
        os.environ.get("OBJDUMP", "riscv64-linux-gnu-objdump"), "-d", "-M", "no-aliases",
        "--no-show-raw-insn", f"--start-address={start}", f"--stop-address={end}",
        "build/lesson08/user.elf"], text=True)
    instructions = [match.groups() for line in text.splitlines()
                    if (match := re.fullmatch(r"\s*([0-9a-f]+):\s+(\w+)\s+(.+)", line))]
    assert [op for _, op, _ in instructions] == ["addi", "sd", "jal"]
    assert instructions[0][2] == "s0,s0,1"
    assert instructions[1][2] == "s0,0(a2)"
    assert instructions[2][2].startswith(f"zero,{start:x} ")
    return start, end


def check(result, bounds):
    assert result.returncode == 0, (result.returncode, result.stdout)
    lines = result.stdout.replace("\r\n", "\n").splitlines()
    assert lines[:4] == BOOT
    assert lines[-1] == PASS and lines.count(PASS) == 1
    assert [line for line in lines if line.startswith("check:")] == CHECKS
    live = {}
    entries = {}
    generations = {}
    spawn_order = []
    progress = {}
    preemptions = {}
    online = {}
    timers = {}
    idle = {}
    participants = {}
    killed = set()
    deferred = set()
    completed = set()
    zombies = {}
    reaped = {}
    waits = []
    active_wait = None
    immediate_count = 0
    blocking_count = 0
    expected_next = None
    high_water = 0
    counter_value = counter_invariant = counter_contention = None
    sleep_progress = set()
    for line in lines[4:]:
        match = EVENT.fullmatch(line)
        if expected_next is not None:
            assert match is not None and match[1] == expected_next, (expected_next, line)
            expected_next = None
        if match:
            name = match[1]
            pid, value = int(match[2], 16), int(match[3], 16)
            if name == "spawn":
                slot, generation = pid & 15, pid >> 4
                assert 0 <= slot < 8
                assert all((other & 15) != slot for other in live), "unreaped slot reuse"
                assert generation == generations.get(slot, 0) + 1
                generations[slot] = generation
                live[pid] = "live"
                entries[pid] = value
                spawn_order.append(pid)
                high_water = max(high_water, len(live))
            elif name == "hart-online":
                assert pid in (0, 1) and pid not in online and value % 16 == 0
                online[pid] = value
            elif name == "sleep":
                assert live[pid] == "live"
                live[pid] = "sleep"
            elif name == "wake":
                assert live[pid] == "sleep" and pid not in killed
                live[pid] = "live"
            elif name == "timer-switch":
                assert live[pid] == live[value] == "live"
                assert pid != value and (pid & 1) == (value & 1), "affinity changed"
                assert pid not in completed and value not in killed
            elif name == "kill":
                assert pid not in killed and live[pid] in ("live", "sleep")
                assert value in (1, 2, 3)
                assert (live[pid] == "sleep") == (value == 3)
                killed.add(pid)
                expected_next = "kill-deferred" if value == 2 else "zombie"
            elif name == "kill-deferred":
                assert pid in killed and pid not in deferred and value == 1
                assert live[pid] == "live"
                deferred.add(pid)
            elif name == "kill-complete":
                assert pid in deferred and pid not in completed and value == 1
                assert live[pid] == "live"
                completed.add(pid)
                expected_next = "zombie"
            elif name == "zombie":
                assert live[pid] in ("live", "sleep") and pid not in zombies
                if pid in deferred:
                    assert pid in completed, "freed remote RUNNING context"
                if pid in killed:
                    assert value == 137
                live[pid] = "zombie"
                zombies[pid] = value
                if active_wait is not None and active_wait["target"] == pid:
                    assert active_wait["phase"] == "blocked" and live[16] == "waiting"
                    expected_next = "wait-return"
            elif name == "wait-call":
                assert pid == 16 and live[pid] == "live" and active_wait is None
                assert value in live and value != 16
                active_wait = {"target": value, "phase": "call"}
                if live[value] == "zombie":
                    immediate_count += 1
                    active_wait["phase"] = "immediate"
                    expected_next = "reap"
                else:
                    expected_next = "wait-block"
            elif name == "wait-block":
                assert pid == 16 and active_wait == {"target": value, "phase": "call"}
                assert live[value] in ("live", "sleep") and live[pid] == "live"
                active_wait["phase"] = "blocked"
                live[pid] = "waiting"
                blocking_count += 1
            elif name == "wait-return":
                assert pid == 16 and active_wait is not None
                target = active_wait["target"]
                assert zombies[target] == value, "status from wrong child"
                if active_wait["phase"] == "blocked":
                    assert live[pid] == "waiting" and live[target] == "zombie"
                    live[pid] = "live"
                    active_wait["phase"] = "returned"
                    expected_next = "reap"
                else:
                    assert active_wait["phase"] == "reaped"
                    assert live[pid] == "live" and target not in live
                    waits.append((target, value))
                    active_wait = None
            elif name == "reap":
                assert active_wait is not None and active_wait["target"] == pid
                assert live[pid] == "zombie" and zombies[pid] == value
                assert pid not in reaped
                phase = active_wait["phase"]
                assert phase in ("immediate", "returned")
                del live[pid]
                reaped[pid] = value
                if phase == "immediate":
                    active_wait["phase"] = "reaped"
                    expected_next = "wait-return"
                else:
                    waits.append((pid, value))
                    active_wait = None
            elif name == "counter-participant":
                assert entries[pid] == 5 and live[pid] == "live"
                assert value == (pid & 1) and pid not in participants
                participants[pid] = value
            elif name == "counter-value":
                assert counter_value is None
                counter_value = pid, value
            elif name == "counter-invariant":
                assert counter_invariant is None
                counter_invariant = pid, value
            elif name == "counter-contention":
                assert counter_contention is None
                counter_contention = pid, value
            elif name in ("hart-timers", "hart-idle"):
                table = timers if name == "hart-timers" else idle
                assert pid in (0, 1) and pid not in table
                table[pid] = value
            else:
                raise AssertionError(("unknown event", line))
        elif match := PREEMPT.fullmatch(line):
            hart, pc, pid, value = (int(field, 16) for field in match.groups())
            assert hart == (pid & 1) and hart in online
            assert bounds[0] <= pc < bounds[1] and (pc - bounds[0]) % 4 == 0
            assert entries[pid] == 1 and live[pid] == "live" and pid not in completed
            assert value > progress.get(pid, 0)
            progress[pid] = value
            preemptions[pid] = preemptions.get(pid, 0) + 1
            if live.get(16) == "sleep" and live.get(19) == "sleep":
                sleep_progress.add(hart)
        else:
            assert line in CHECKS + [PASS, "controller: start", "worker: sleeping", "worker: woke"], line
            if line == CHECKS[4]:
                assert len(live) == 8 and list(live.values()).count("zombie") == 7
    assert expected_next is None and active_wait is None
    assert live == {16: "live"} and high_water == 8
    assert len(online) == 2 and online[1] - online[0] == 16384
    assert set(preemptions) == {17, 18} and min(preemptions.values()) >= 2
    assert sleep_progress == {0, 1}, "sleep stalled a hart's worker"
    assert killed == {17, 18, 19} and deferred == completed == {17}
    assert set(participants.values()) == {0, 1} and len(participants) == 2
    assert counter_value == (3, 8000) and counter_invariant == (0, 0)
    assert counter_contention is not None and sum(counter_contention) > 0
    assert set(timers) == {0, 1} and min(timers.values()) >= 2
    assert set(idle) == {0, 1} and min(idle.values()) > 0
    # Exact wait target order, not merely an unrelated status sequence/set.
    children = spawn_order[1:]
    expected_targets = [children[0], children[2], children[1], *children[3:]]
    expected_statuses = [137, 137, 137, 42, 31, 23, 41, 40, *range(60, 67), 77]
    assert waits == list(zip(expected_targets, expected_statuses, strict=True)), waits
    assert dict(waits) == zombies == reaped
    assert immediate_count >= 7 and blocking_count >= 2
    assert lines.count("worker: sleeping") == 2 and lines.count("worker: woke") == 1


def reject(action):
    try:
        action()
    except AssertionError:
        return
    raise AssertionError("oracle admitted invalid result")


def mutation_checks(result, bounds):
    def altered(text):
        return subprocess.CompletedProcess([], 0, text)
    lines = result.stdout.splitlines(keepends=True)
    mutations = {
        "missing-wait-block": "".join(line for line in lines if not line.startswith("wait-block ")),
        "missing-wait-call": "".join(line for line in lines if not line.startswith("wait-call ")),
        "missing-kill-complete": "".join(line for line in lines if not line.startswith("kill-complete ")),
        "late-failure": result.stdout + "FAIL: late failure\n",
        "banner-only": PASS + "\n",
        "missing-exhaustion": result.stdout.replace(CHECKS[4], ""),
        "bad-spin-pc": result.stdout.replace("preempt-loop pc=0x000000008040", "preempt-loop pc=0x000000008050"),
    }
    # Status remains a real status elsewhere: unrelated status sets must not
    # conceal a wrong-child return (31 is another child's legitimate result).
    mutations["wrong-child-status"] = result.stdout.replace(
        "wait-return pid=0x0000000000000010 value=0x000000000000002a",
        "wait-return pid=0x0000000000000010 value=0x000000000000001f", 1)
    # Keep all returns/reaps but swap the first wait's target to another child.
    mutations["wrong-wait-target"] = result.stdout.replace(
        "wait-call pid=0x0000000000000010 value=0x0000000000000011",
        "wait-call pid=0x0000000000000010 value=0x0000000000000013", 1)
    mutations["fake-hart"] = result.stdout.replace("preempt-hart=0x0000000000000001", "preempt-hart=0x0000000000000000")
    for label, text in mutations.items():
        assert text != result.stdout, label
        reject(lambda: check(altered(text), bounds))
    for status in (1, 124, -9):
        reject(lambda: check(subprocess.CompletedProcess([], status, result.stdout), bounds))
    Path("build/lesson08/oracle-mutations.log").write_text(
        "\n".join("REJECTED: " + label for label in mutations) + "\nREJECTED: exit 1, 124, -9\n")


def main():
    bounds = symbols()
    result = None
    for index in range(5):
        result = execute(command("build/lesson08/disk.img"), f"build/lesson08/positive-{index}.log")
        check(result, bounds)
    assert result is not None
    terminal = execute(command("build/lesson08/disk.img"), "build/lesson08/pty.log", terminal=True)
    check(terminal, bounds)
    negative = execute(command("build/lesson08/disk-bad-context.img"), "build/lesson08/bad-context.log")
    assert negative.returncode == 1
    assert negative.stdout.replace("\r\n", "\n").splitlines()[:4] == BOOT
    assert negative.stdout.replace("\r\n", "\n").splitlines()[-1] == "FAIL: spin context restore"
    assert PASS not in negative.stdout
    reject(lambda: check(negative, bounds))
    bad_lock = execute(command("build/lesson08/disk-bad-lock.img"), "build/lesson08/bad-lock.log")
    assert bad_lock.returncode == 1 and PASS not in bad_lock.stdout
    assert "shared counter lost update\nFAIL: user assertion" in bad_lock.stdout.replace("\r\n", "\n")
    assert {int(match[3], 16) for line in bad_lock.stdout.splitlines()
            if (match := EVENT.fullmatch(line)) and match[1] == "counter-participant"} == {0, 1}
    reject(lambda: check(bad_lock, bounds))
    mutation_checks(result, bounds)
    reject(lambda: execute(command("build/lesson08/disk.img") + ["-S"],
                           "build/lesson08/timeout-rejected.log", timeout=0.2))
    print(result.stdout, end="")
    print("PASS: lesson08 five SMP disk boots, PTY, broken restore/lock and strict oracle mutations.")


if __name__ == "__main__":
    main()
