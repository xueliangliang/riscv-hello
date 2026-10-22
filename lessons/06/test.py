#!/usr/bin/env python3
"""Real disk boots; full ordered oracle, dynamic PC/progress, no timeout success."""
import os
from pathlib import Path
import re
import subprocess

BOOT = [
    "Lesson 03: M-mode bootloader started.",
    "Boot record validated; loading kernel and shell from disk.",
    "Bootloader: both images loaded; jumping to kernel at 0x80200000.",
    "Lesson 06: direct Sstc timer, one user stream, no scheduler.",
    "user: before interrupts; entering normal instruction loop.",
]
AFTER = [
    "user: after interrupts; registers, SP, stack and progress verified.",
    "PASS: three asynchronous timers returned to the same user stream.",
]
TIMER = re.compile(
    r"timer: tick=0x([0-9a-f]{16}) scause=0x8000000000000005 "
    r"SPP=0 resume=0x([0-9a-f]{16}) progress=0x([0-9a-f]{16})"
)


def command(disk):
    return [
        os.environ.get("QEMU", "qemu-system-riscv64"),
        "-machine", "virt", "-cpu", "rv64,sstc=true",
        "-global", "virtio-mmio.force-legacy=false",
        "-smp", "1", "-m", "128M", "-display", "none",
        "-serial", "stdio", "-monitor", "none", "-bios", "none",
        "-kernel", "build/lesson03/bootloader.elf",
        "-drive", f"file={disk},if=none,format=raw,id=disk,readonly=on",
        "-device", "virtio-blk-device,drive=disk", "-no-reboot",
    ]


def execute(args, timeout, log):
    try:
        result = subprocess.run(args, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as error:
        Path(log).write_bytes(error.stdout or b"")
        raise AssertionError("QEMU timeout is failure") from error
    Path(log).write_text(result.stdout)
    return result


def symbols():
    nm = os.environ.get("NM", "riscv64-linux-gnu-nm")
    output = subprocess.check_output([nm, "-n", "build/lesson06/user.elf"], text=True)
    labels = {parts[2]: int(parts[0], 16) for line in output.splitlines()
              if len(parts := line.split()) == 3}
    start = labels["interrupt_loop"]
    end = labels["interrupt_loop_end"]
    assert end - start == 16, "unexpected interrupt loop length"
    objdump = os.environ.get("OBJDUMP", "riscv64-linux-gnu-objdump")
    disassembly = subprocess.check_output([
        objdump, "-d", "-M", "no-aliases", "--no-show-raw-insn",
        f"--start-address={start}", f"--stop-address={end}",
        "build/lesson06/user.elf",
    ], text=True)
    instructions = [match.groups() for line in disassembly.splitlines()
                    if (match := re.fullmatch(r"\s*([0-9a-f]+):\s+(\w+)\s+(.+)", line))]
    assert [int(address, 16) for address, _, _ in instructions] == list(range(start, end, 4))
    assert [op for _, op, _ in instructions] == ["addi", "addi", "ld", "beq"], instructions
    assert [args for _, _, args in instructions[:3]] == ["s0,s0,1", "s1,s1,1", "t0,0(t1)"]
    assert instructions[3][2].startswith(f"t0,zero,{start:x} "), instructions
    return labels


def check(result, variant, labels):
    lines = result.stdout.replace("\r\n", "\n").splitlines()
    count = 1 if variant in ("bad-pc", "omit-pc") else 3
    suffix = AFTER
    if variant == "bad-context":
        suffix = ["FAIL: user register/stack self-check"]
    elif variant in ("bad-pc", "omit-pc"):
        suffix = ["FAIL: resume PC restore"]
    expected_status = 0 if variant == "positive" else 1
    assert result.returncode == expected_status, (variant, result.returncode, lines)
    assert lines[:len(BOOT)] == BOOT, lines
    assert len(lines) == len(BOOT) + count + len(suffix), lines
    assert lines[len(BOOT) + count:] == suffix, lines
    previous = -1
    for tick, line in enumerate(lines[len(BOOT):len(BOOT) + count], 1):
        match = TIMER.fullmatch(line)
        assert match, line
        actual_tick, pc, progress = (int(value, 16) for value in match.groups())
        assert actual_tick == tick, line
        assert labels["interrupt_loop"] <= pc < labels["interrupt_loop_end"], line
        assert (pc - labels["interrupt_loop"]) % 4 == 0, line
        assert progress > previous, line
        previous = progress


def must_reject(action):
    try:
        action()
    except AssertionError:
        return
    raise AssertionError("oracle admitted invalid result")


def main():
    labels = symbols()
    positive = None
    for variant in ("positive", "bad-context", "bad-pc", "omit-pc"):
        disk = "build/lesson06/disk" + ("" if variant == "positive" else "-" + variant) + ".img"
        result = execute(command(disk), 10, disk + ".log")
        print(result.stdout, end="")
        check(result, variant, labels)
        if variant == "positive":
            positive = result
    assert positive is not None
    # Mutate genuine captured output; these are oracle tests, not guest evidence.
    for output in (positive.stdout + "FAIL: late failure\n",
                   positive.stdout.splitlines()[-1] + "\n",
                   positive.stdout.replace("8000000000000005", "0000000000000005"),
                   positive.stdout.replace("SPP=0", "SPP=1"),
                   positive.stdout.replace("resume=0x000000008040", "resume=0x000000008050")):
        must_reject(lambda: check(subprocess.CompletedProcess([], 0, output), "positive", labels))
    for status in (1, 124, -9):
        must_reject(lambda: check(subprocess.CompletedProcess([], status, positive.stdout), "positive", labels))
    # Exercise the actual timeout path with a stopped real QEMU, not a mocked
    # returncode or a negative guest whose hang is misclassified as success.
    must_reject(lambda: execute(command("build/lesson06/disk.img") + ["-S"], 0.2,
                                "build/lesson06/timeout-rejected.log"))
    print("PASS: lesson06 real timer/context/PC variants and timeout rejection.")


if __name__ == "__main__":
    main()
