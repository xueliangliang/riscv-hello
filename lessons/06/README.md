# 06 — 中断：保存现场，再回到原来的程序流

## Result and boundary

One hart, one user instruction stream, three **asynchronous supervisor timer
interrupts**, then that same user checks its registers/stack and calls exit.
There is **no scheduler, task switch, second process or yield**. A timer can
interrupt a running program without choosing a different program afterward.

The unchanged lesson03 M bootloader still reads both payloads from its raw
virtio-block disk and jumps to `0x80200000`. Its `shell` payload slot contains
this lesson's U program at `0x80400000`. QEMU loads **only the bootloader** with
`-kernel`, never the lesson06 kernel directly. Lessons01–05 and their tags are
unchanged. Lesson06 owns new `start.S` and `trap.S`; it reuses lesson04's frame
layout, runtime helpers and user linker, lesson03's kernel linker, lesson02's
UART and the existing disk generator. This is not an extension of the 05
application: a deliberately small assembly probe makes every live register
and every instruction in the interrupted loop visible.

## Exact timer route: direct Sstc, not a firmware relay

Tested command-line CPU: **`-machine virt -cpu rv64,sstc=true -smp 1`** with
`-bios none`. No OpenSBI, SBI timer ecall, M-mode MTIP handler, software-interrupt
relay, PLIC claim/complete or CLINT `mtimecmp` programming is involved.

1. The disk-loaded M entry installs emergency M trap handling and the same
   all-address RWX PMP policy as 04. It sets `mcounteren.TM=1` (bit 1), enabling
   S to read `time`; `scounteren` stays zero, so U is not given timer CSR access.
2. It sets **`menvcfg.STCE=1` (bit 63)** and checks that the bit reads back set.
   This enables S access to the 64-bit **`stimecmp` CSR (`0x14d`)**. The numeric
   CSR spelling lets the existing assembler ISA flags remain unchanged.
3. It parks `stimecmp=UINT64_MAX`, sets **`mideleg=0x20`** (STIP, interrupt 5),
   keeps `mie=0` initially, and delegates exceptions 2/8 as in 04. `mret` enters
   S; S installs direct `stvec` and enters U with STIE masked.
4. U initializes its live integer registers and stack canary, then executes
   one START ecall. This is setup, **not the source of any timer interrupt**.
   S sets `stimecmp=time+100000` and `sie.STIE=1`, and returns to the loop.
5. Sstc compares the time counter against `stimecmp`. When `time>=stimecmp`,
   **STIP becomes pending**. With STIE enabled, execution in U can trap to S
   even though `sstatus.SIE=0`: SIE masks S-mode execution, not lower-privilege
   U execution. The cause is **`0x8000000000000005`**, not exception cause 5.
6. S rearms the comparator in the future for ticks 1/2. Tick 3 masks STIE,
   parks the comparator and publishes the completion flag before returning.
   Writing `sip` is not this timer's acknowledgement. The architecture permits
   delayed STIP deassertion: an early/spurious entry before the current deadline
   returns unchanged, without counting another tick or printing a tick line.

The tested QEMU-generated DTB reports `/cpus/timebase-frequency=10000000`.
Thus 100000 counter ticks are nominally 10 ms of that emulated timebase, **not
an assertion about host wall-clock spacing, real-board clocks or throughput**.
This three-tick demonstration does not implement clock wraparound handling,
periodic catch-up accounting or a generic timer queue.

## Hardware saves a little; software saves the rest

On U-to-S trap entry, hardware records `sepc` (the interrupted instruction's
address), `scause`, `stval`, sets SPP=0, copies SIE to SPIE, clears SIE and
redirects PC to `stvec`. It does **not** push integer registers, choose a stack,
call C, acknowledge the timer or decide to schedule another task.

Software swaps U sp with the trusted S stack top in `sscratch`, allocates the
same 288-byte/16-byte-aligned frame as 04, and saves x1–x31 plus four trap CSRs.
The saved x2 is U's original sp. During S handling `sscratch=0`, SIE remains
zero and no nested interrupts are enabled. S-origin exceptions are fatal,
not a supported reentrant kernel path. Initial S calls are abandoned when
entering U, allowing the trap stack to reuse its top.

The handler checks the exact interrupt cause, SPP=0, SIE=0, original U SP,
and that saved PC is an instruction boundary inside the known four-instruction
loop. It prints the tick, cause, interrupted PC and U's progress counter.
There is **no `epc += 4` on the timer path**. Only the explicitly uncompressed
START ecall is skipped by 4; final exit never returns.

Before returning from a counted timer, C deliberately clears the *live* `sepc`
CSR, leaving `frame->epc` untouched. This diagnostic forces the assembly to
actually restore it rather than accidentally relying on its hardware entry
value. The epilogue writes saved `sepc`, independently reads it back and checks
it equals the frame PC, restores `sstatus`/all integer registers/U sp, and
executes `sret`. `sret` returns to the privilege recorded in SPP, at `sepc`;
it does not restore the integer frame for us. The demonstration's readback
guard is an assertion, not a general security boundary.

### U is doing normal instructions when interrupted

`interrupt_loop..interrupt_loop_end` is exactly:

```asm
addi s0, s0, 1
addi s1, s1, 1
ld   t0, 0(t1)
beqz t0, interrupt_loop
```

There is **no ecall, CSR access, WFI, yield or function call in this loop**.
The load observes a normal RAM completion flag, only so the application knows
when to stop. It neither checks the timer nor requests/triggers delivery.
QEMU's asynchronous timer interrupt arrives while U executes these instructions.
The S handler also checks that U progress increased between counted interrupts;
no exact instruction count or interrupted PC is assumed.

After the flag is set, U completes that iteration and checks s0=s1>0, exact sp,
the stack canary and all fixed sentinel registers, including caller-saved
ra/a*/t* as well as gp/tp/s*. The loop's t0/t1 and s0/s1 are deliberately live
working registers rather than fixed sentinels. The exercised GDB check below
compares **all 31 writable integer registers**, including these dynamic ones,
against their saved values before returning. U's final exit ecall carries its
self-test status; S validates the exit PC, number and three-tick phase before
successfully terminating the demo through QEMU's test device.

## Reproduce and oracle

```sh
make clean all test inspect
make test-lesson06
script -q -e -c 'make test' build/pty.log
```

Verified tool versions: `riscv64-linux-gnu-gcc` **15.2.0**
(Ubuntu 15.2.0-16ubuntu1), GNU binutils **2.46**, QEMU **10.2.1**
(Debian 1:10.2.1+ds-1ubuntu3.2), Python **3.14.7**, GDB multiarch **17.1**
(Ubuntu 17.1-2ubuntu1), on Linux. The code's ISA/ABI flags remain
`rv64imac_zicsr_zifencei` / `lp64`; no FP/vector state is enabled or saved.

One actual positive transcript is below. **Only the three `resume` and
`progress` values are variable**; these are captured values, not golden timing
constants. The oracle reads the actual user ELF symbols, requires each PC to
lie at a 4-byte instruction boundary in the loop, and requires strictly
increasing progress. It compares every other ordered line and QEMU exit status.

```text
Lesson 03: M-mode bootloader started.
Boot record validated; loading kernel and shell from disk.
Bootloader: both images loaded; jumping to kernel at 0x80200000.
Lesson 06: direct Sstc timer, one user stream, no scheduler.
user: before interrupts; entering normal instruction loop.
timer: tick=0x0000000000000001 scause=0x8000000000000005 SPP=0 resume=0x000000008040008c progress=0x00000000006b96d4
timer: tick=0x0000000000000002 scause=0x8000000000000005 SPP=0 resume=0x000000008040008c progress=0x0000000000f071d5
timer: tick=0x0000000000000003 scause=0x8000000000000005 SPP=0 resume=0x000000008040008c progress=0x0000000001764643
user: after interrupts; registers, SP, stack and progress verified.
PASS: three asynchronous timers returned to the same user stream.
```

Actual fault-injection disk boots, all requiring **guest failure and QEMU
status 1**, never a timeout:

| Variant | Injected defect | Required output |
| --- | --- | --- |
| `bad-context` | Timer epilogue restores a3 then corrupts it by +1 | Three ticks, then `FAIL: user register/stack self-check` |
| `bad-pc` | Timer epilogue writes saved PC+4 | One tick, then `FAIL: resume PC restore` |
| `omit-pc` | Timer epilogue omits the sepc write | One tick, then `FAIL: resume PC restore` |

The positive guest must exit 0. PC defects are caught by the explicit epilogue
assertion before `sret`, not by assuming every skipped loop instruction would
necessarily make a final sentinel wrong. Logs are `build/lesson06/disk*.img.log`.
Oracle self-tests mutate genuinely captured output: extra/truncated lines,
missing interrupt bit, SPP=1, out-of-range PC and failed/timeout statuses must
be rejected. A separate **real QEMU started with `-S`** exercises the timeout
exception path (0.2-second host watchdog); timeout is failure, never a guest
negative-test success. Ordinary guest runs have a 10-second host watchdog,
not an assertion about exact emulated timing. All prior lesson tests remain
part of `make test`. The host also disassembles the built U ELF and requires
exactly those four normal instructions in the loop; an inserted ecall/WFI or
changed branch cannot silently become a cooperative-delivery demonstration.
`make inspect` includes both lesson06 ELF headers, load segments and disassembly;
inspect the four loop instructions yourself.

## GDB procedure actually exercised

Build first. Terminal one:

```sh
qemu-system-riscv64 -machine virt -cpu rv64,sstc=true \
  -global virtio-mmio.force-legacy=false -smp 1 -m 128M \
  -display none -serial stdio -monitor none -bios none \
  -kernel build/lesson03/bootloader.elf \
  -drive file=build/lesson06/disk.img,if=none,format=raw,id=disk,readonly=on \
  -device virtio-blk-device,drive=disk -no-reboot \
  -S -gdb tcp:127.0.0.1:12346
```

Terminal two:

```sh
gdb-multiarch -q -batch -x lessons/06/gdb-check.gdb
```

The checked-in script uses hardware breakpoints because the disk payload has
not yet been copied into RAM when GDB attaches. It stops in `timer_interrupt`,
asserts cause=`0x8000000000000005`, priv=1, SPP/SIE=0, `sscratch=0`, and snapshots
the full frame. It then stops at `restore_user_return` immediately before
`sret`, compares every live x1–x31 with the saved frame and checks restored
`sepc`. Finally it sets a hardware breakpoint at **that captured `sepc`**,
continues through `sret`, and asserts priv=0, exact PC and SP. Using a breakpoint
rather than remote `stepi` avoids a tested QEMU/GDB combination running through
SRET without stopping. It removes breakpoints and lets the guest exit normally.

Observed check output included:

```text
GDB: captured asynchronous U frame at PC=0x8040008c, SP=0x80410000
GDB: all 31 writable integer registers restored exactly before sret
GDB PASS: sret resumed U at the exact interrupted PC, no +4
```

At C entry, the observed S stack pointer was `0x80206ec0`, saved U SP was
`0x80410000`; before `sret`, sp was again `0x80410000` and `sscratch` held S's
stack top (`0x80207020` in this build). Stack addresses can change with linking;
the checks use relationships/symbols, not those illustrative S addresses.

## References and limits

Primary references consulted for this implementation:

- RISC-V 20260120 library, Privileged Architecture Supervisor-Level ISA 1.13:
  `sstatus`, `sie/sip`, `sscratch`, `sepc`, `scause`, supervisor timer comparator
  and delayed/spurious STIP behavior:
  <https://docs.riscv.org/reference/isa/v20260120/priv/supervisor.html>
- Sstc 1.0 and M configuration/delegation/counter access:
  <https://docs.riscv.org/reference/isa/v20260120/priv/sstc.html>
  <https://docs.riscv.org/reference/isa/v20260120/priv/machine.html>
- QEMU virt machine and the **v10.2.1** implementation of Sstc and CPU properties:
  <https://www.qemu.org/docs/master/system/riscv/virt.html>
  <https://github.com/qemu/qemu/blob/v10.2.1/target/riscv/time_helper.c>
  <https://github.com/qemu/qemu/blob/v10.2.1/target/riscv/cpu.c>

This validates software/privileged-ISA behavior on QEMU, **not RTL, FPGA,
physical timers or board bring-up**. It is not a memory-isolated OS: the flat
all-address PMP entry permits malicious U code to overwrite S memory or access
MMIO directly. ELF permissions are descriptive, not enforced W^X. The shared
flag is intentional single-hart RAM communication, not a protected syscall or
a multiprocessor synchronization protocol. No nested/reentrant trap handling,
FP/vector context, scheduler, preemptive task switching or process lifecycle is
claimed. The next chapter may build scheduling on this mechanism; timer
interrupts alone do not imply a scheduler.
