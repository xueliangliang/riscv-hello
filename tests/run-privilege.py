#!/usr/bin/env python3
"""Strict transcript + finisher-status oracle; timeout is never success."""
import os
from pathlib import Path
import subprocess
import sys

BOOT = [
    "Lesson 03: M-mode bootloader started.",
    "Boot record validated; loading kernel and shell from disk.",
    "Bootloader: both images loaded; jumping to kernel at 0x80200000.",
]
TRAPS04 = [
    "trap: scause=0x0000000000000008 sepc=0x0000000080400010 SPP=0",
    "trap: scause=0x0000000000000002 sepc=0x0000000080400020 SPP=0",
    "trap: scause=0x0000000000000008 sepc=0x0000000080400030 SPP=0",
]
PASS04 = "PASS: M -> S -> U, ecall, CSR fault, context, S recovery."


def check(result, expected, status):
    actual = result.stdout.replace("\r\n", "\n").splitlines()
    if result.returncode != status or actual != expected:
        raise AssertionError(
            f"expected status={status}, lines={expected!r}; "
            f"got status={result.returncode}, lines={actual!r}"
        )


def run(disk, expected, status):
    command = [
        os.environ.get("QEMU", "qemu-system-riscv64"),
        "-machine", "virt", "-global", "virtio-mmio.force-legacy=false",
        "-smp", "1", "-m", "128M", "-display", "none",
        "-serial", "stdio", "-monitor", "none", "-bios", "none",
        "-kernel", "build/lesson03/bootloader.elf",
        "-drive", f"file={disk},if=none,format=raw,id=disk,readonly=on",
        "-device", "virtio-blk-device,drive=disk", "-no-reboot",
    ]
    try:
        result = subprocess.run(command, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, timeout=10, check=False)
    except subprocess.TimeoutExpired as error:
        Path(str(disk) + ".log").write_bytes(error.stdout or b"")
        raise AssertionError(f"QEMU timeout: {disk}") from error
    Path(str(disk) + ".log").write_text(result.stdout)
    print(result.stdout, end="")
    check(result, expected, status)


def test_oracle():
    # Demonstrate that a PASS suffix alone, extra output, bad status and missing
    # trap evidence cannot pass. Timeouts are rejected before reaching check().
    expected = BOOT + ["Lesson 04: supervisor entered after mret."] + TRAPS04 + [PASS04]
    invalid = [expected[-1:], expected + ["FAIL: late failure"], expected[:-2] + [PASS04]]
    for lines in invalid:
        try:
            check(subprocess.CompletedProcess([], 0, "\n".join(lines)), expected, 0)
        except AssertionError:
            continue
        raise AssertionError("oracle admitted malformed transcript")
    for status in (1, 124, -9):
        try:
            check(subprocess.CompletedProcess([], status, "\n".join(expected)), expected, 0)
        except AssertionError:
            continue
        raise AssertionError("oracle admitted failed/timeout status")


def lesson04():
    prefix = BOOT + ["Lesson 04: supervisor entered after mret."]
    run("build/lesson04/disk.img", prefix + TRAPS04 + [PASS04], 0)
    run("build/lesson04/disk-bad-cause.img", prefix + TRAPS04[:1] + [
        "trap: scause=0x0000000000000008 sepc=0x0000000080400020 SPP=0",
        "FAIL: unexpected scause",
    ], 1)
    run("build/lesson04/disk-bad-pc.img", prefix + TRAPS04[:1] + [
        "trap: scause=0x0000000000000002 sepc=0x0000000080400024 SPP=0",
        "FAIL: unexpected sepc",
    ], 1)
    print("PASS: lesson04 exact cause/PC/context and negative QEMU cases.")


def lesson05():
    prefix = BOOT + ["Lesson 05: supervisor ready for syscall ABI."]
    body = [
        "trap: scause=0x0000000000000008 sepc=0x000000008040001c SPP=0",
        "user: hello via syscall.",
        "user: write bounds and unknown syscall rejected.",
        "user: libc, aligned heap, overflow and exhaustion verified.",
        "user: exiting.",
    ]
    run("build/lesson05/disk.img", prefix + body + [
        "PASS: user exit(0) recovered to supervisor.",
    ], 0)
    run("build/lesson05/disk-bad-exit.img", prefix + body + [
        "FAIL: user exit status",
    ], 1)
    run("build/lesson05/disk-bad-trap.img", prefix + [
        "trap: scause=0x0000000000000002 sepc=0x0000000080400030 SPP=0",
        "FAIL: unexpected scause",
    ], 1)
    print("PASS: lesson05 ABI, write rejection, libc, heap and negative QEMU cases.")


if __name__ == "__main__":
    test_oracle()
    if sys.argv[1:] == ["04"]:
        lesson04()
    elif sys.argv[1:] == ["05"]:
        lesson05()
    else:
        raise SystemExit("usage: run-privilege.py 04|05")
