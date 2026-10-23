# Lesson 07 — 保存 A 的现场，恢复 B：抢占式调度与进程生命周期

The result is a **single-hart, timer-preemptive round-robin scheduler**, not a
cooperative coroutine example. Two U-mode workers execute an infinite instruction
loop with no ecall, sleep, or yield. Timer traps save each worker's integer state;
C selects another process's saved frame; assembly restores that frame and `sret`
continues the other instruction stream. A real U-mode controller tests the complete
bounded lifecycle described below. Lessons01–06 are unchanged.

## Build and run

From the repository root, with `riscv64-linux-gnu-gcc`, binutils, Python3 and
`qemu-system-riscv64` installed:

```sh
make clean all
make test
make inspect
# Just this chapter (includes three ordinary boots, one real PTY boot,
# an intentionally broken restore boot, and timeout/oracle rejection):
make test-lesson07
# Optional checked debugger exercise; requires gdb-multiarch:
make test-lesson07-gdb
```

A manual run uses the **unmodified lesson03 bootloader as the ONLY `-kernel`**:

```sh
qemu-system-riscv64 \
  -machine virt -cpu rv64,sstc=true -smp 1 -m 128M \
  -global virtio-mmio.force-legacy=false \
  -display none -serial stdio -monitor none -bios none \
  -kernel build/lesson03/bootloader.elf \
  -drive file=build/lesson07/disk.img,if=none,format=raw,id=disk,readonly=on \
  -device virtio-blk-device,drive=disk -no-reboot
```

The loader reads the ordinary lesson03 boot record and copies the raw kernel to
`0x80200000` and the raw user image (the boot record still calls it “shell”) to
`0x80400000`. There is no direct `-kernel lesson07/kernel.elf` shortcut and no SBI.
Successful execution shuts QEMU down with status **0** via the test finisher.
A guest assertion/fault shuts it down with status **1**. A timeout is always a
failure, including the deliberately stopped `-S` timeout test.

The stable ordered checkpoints are:

```text
Lesson 03: M-mode bootloader started.
Boot record validated; loading kernel and shell from disk.
Bootloader: both images loaded; jumping to kernel at 0x80200000.
Lesson 07: single-hart preemptive processes, flat memory.
controller: start
check: invalid inputs rejected
check: preemption sleep kill statuses
check: wait ownership generation stacks
check: live and zombie exhaustion
check: reap relaunch complete
PASS: lesson07 preemptive scheduler and lifecycle.
```

Additional `spawn`, `sleep`, `wake`, `preempt-loop pc=... pid=... value=...`,
`timer-switch`, `kill`, `zombie`, `wait-block`, `wait-return` and `reap` events occur
between checkpoints. All numeric event fields are 16-digit hexadecimal. For
`preempt-loop`, value is the saved `s0` progress count; `timer-switch` value is the
selected PID; `kill` value is the victim's previous state; exit/reap/wait-return
values are statuses. Instruction PCs and progress counts, timer-event counts,
and incidental timer switches vary with QEMU/host timing. They are **not** golden
strings. Tests verify PCs against actual ELF loop bounds and disassemble that
loop to ensure it contains only increment/store/jump, not an ecall. They require
both workers to advance through multiple timer preemptions, including A→B and
B→A, while the third worker sleeps. A killed worker's counter and timer-hit count
must stay frozen while its sibling continues; the killed sleeper never prints
`worker: woke`. A later short sleeper does wake and returns status 23.

`test.py` parses the entire log with a separate lifecycle model: no extra unknown
lines, failure suffixes, duplicated PASS, unreaped slot reuse, non-increasing PID
generations, progress after kill, lost statuses, or leaked children are admitted.
It checks an eight-slot high-water mark and seven simultaneous zombies. Guest
assertions independently exercise failed calls and exact return values. These
are simulator/software checks, not an independent formal proof or RTL validation.
Logs stay under `build/lesson07/`: `positive-0.log` through `positive-2.log`,
`pty.log`, `bad-context.log`, `timeout-rejected.log`, and optional `gdb.log` /
`gdb-uart.log`.

## Where to read

| File | Responsibility |
|---|---|
| `start.S` | Disk-loaded M entry, PMP, Sstc permissions/delegation, S entry |
| `runtime.h`, `trap.S` | Exact 288-byte integer frame ABI, kernel-stack entry, selected-frame restoration |
| `process.h` | Persistent per-process frame, PID generation, parent/state/wait/deadline data |
| `kernel.c` | Table allocation, round-robin selection, timer/syscall dispatch, sleep and lifecycle |
| `abi.h` | Syscall/state/error/entry IDs, memory budgets, explicit `UserData` layout |
| `syscall.h`, `syscall.c` | Tiny U-mode ecall interface; no kernel headers or libc dependency |
| `user.c` | Real U-mode lifecycle controller and failure assertions |
| `workers.c`, `user-start.S` | Sleep/exit/ownership programs and noncooperative assembly spinner |
| `user.ld`, `symbols.py` | Linker budgets and kernel's generated built-in entry addresses |
| `test.py`, `switch.gdb`, `gdb-test.py` | Log model, real-QEMU negatives/PTY/timeout and checked GDB switch |

## Explain the switch

1. A is executing U instructions with A's `sp`. Sstc raises supervisor timer
   cause `0x8000000000000005`. Hardware records `sepc/scause/stval`, records SPP
   and SPIE and clears SIE; **it does not save general registers or switch sp**.
2. `supervisor_trap` swaps `sp` with `sscratch`. `sscratch` held the **hart's
   kernel stack top**, not a user pointer. Assembly saves x0–x31 and four CSRs
   on that kernel stack and leaves `sscratch=0` in S mode. S interrupts stay
   disabled throughout the C handler and restoration; nested S traps fail.
3. `trap_dispatch` validates U origin and the current slot's stack range, then
   copies the temporary frame into `processes[current].frame`. This copy remains
   valid after the kernel entry stack is reused by another process.
4. On an actual timer deadline, `schedule(1)` makes A READY, wakes eligible
   sleepers, and scans slots circularly after A. It marks B RUNNING, updates
   `current`, rearms `stimecmp` and **returns `&processes[B].frame` in a0**.
5. `restore_frame` executes `mv sp,a0`. From this point its loads refer to B's
   frame, not A's temporary entry frame. It writes B's `sepc/sstatus`, resets
   `sscratch` to the fixed kernel stack top, restores B's registers and user SP,
   then `sret` returns to B's U-mode instruction stream. It must NOT derive the
   next kernel stack from `frame+288`: process frames live in the process table!

Timer traps keep the interrupted PC unchanged. Only a 32-bit synchronous U ecall
advances the saved PC by 4. Integer contexts include caller-saved registers;
there is no F/D/vector context (build ISA is RV64IMAC plus CSR/fence.i). Spinner
checks cover saved caller/callee registers, increasing progress, its data pointer,
per-instance data canary/counter and an independent stack canary. `BAD_CONTEXT`
actually adds one to restored a3 in assembly; the negative QEMU boot must report
`FAIL: spin context restore`, exit 1 and never print PASS.

The timer route is the lesson06 direct-Sstc route: M grants `mcounteren.TM` and
`menvcfg.STCE`, delegates STIP bit 5 in `mideleg`, and S enables `sie.STIE`.
S writes the RV64 `stimecmp` CSR (`0x14d`) to `time+100000` (10 ms on QEMU virt's
10 MHz timer). There is no M timer relay or PLIC claim/complete for this source.
An early delivery while `time < deadline` is a permitted delayed-deassertion
case and restores the same frame without counting another timer tick.

`make test-lesson07-gdb` starts a disposable stopped QEMU, attaches a checked
batch GDB script, and stops at A's timer trap **after B has already run**. It
checks that C returns B's process-owned frame, A/B SPs differ, and the actual
registers at `restore_user_return` contain B's SP and sepc with SPP=0. It then
detaches and requires the guest's entire controller to finish successfully.
The test uses a dynamically selected localhost GDB port and a hard timeout.

## Lifecycle, ownership and PID contract

Eight process slots are independent of the number of harts: slot 0 is the
non-exiting controller; slots 1–7 are workers. `pid = generation*16 + slot`.
Generations begin at one, survive reaping and increment on allocation. Lookup
checks slot bounds, allocation state and the **whole** PID. A stale PID cannot
refer to a replacement occupying the same slot. Generations never wrap to a
previous PID; allocation fails if the positive signed-PID budget is exhausted.

```text
FREE --spawn--> READY --selected--> RUNNING --timer--> READY
                                      | sleep        | wait(live child)
                                      v              v
                                   SLEEPING        WAITING
                                      | deadline     | child's exit
                                      +--> READY <---+
RUNNING --exit--> ZOMBIE --parent wait/reap--> FREE
READY/SLEEPING --parent kill--> ZOMBIE --parent wait/reap--> FREE
```

`ZOMBIE` means exited-but-not-yet-reaped, **not FREE**. It preserves PID and
status and consumes a slot. A waiting parent is awakened with the child's status
and the matching child is reaped once; waiting on an existing zombie reaps it
immediately. Errors do not change ownership/state or consume a PID generation.
No wait status is written through a user pointer: it is the scalar a0 result.

For a deliberately small, explicit orphan policy, only the controller may spawn
workers, and it cannot call exit. Workers have no descendants; there is no fork,
exec, reparenting, wait-any, arbitrary entry-PC spawn, or signal framework.
Kill is allowed only for one's own live child; normal exit statuses are 0–255,
and kill returns synthetic status **137**, not a POSIX signal implementation.
A zombie cannot be killed again. On one hart the caller and victim cannot both
be executing: “kill a running worker” means kill a formerly executing,
timer-preempted runnable worker; its table state is READY when the controller
issues kill. Killing a simultaneously RUNNING process is an SMP concern.

Sleep blocks only the caller until an absolute `rdtime` deadline. It returns 0
on wake, not on each intervening interrupt. When no process is READY and there
are sleepers, S code polls deadlines with interrupts masked; it does not restore
a fake U frame or busy-wait inside a user's sleep syscall while other users are
runnable. No READY process and no sleeper is an explicit fatal deadlock.
This is a small uniprocessor idle policy, not a power-efficient `wfi` idle thread.

## User ABI and failures

`ecall`: a7 = call ID, a0/a1 = arguments, signed a0 = return. The wrapper declares
a memory clobber. All other saved integer registers survive the kernel trap;
normal C caller-saved rules still apply across the C wrapper itself. Initial
entry receives a0 = built-in entry ID, a1 = scalar argument, a2 = own `UserData*`.
The initial SP is 16-byte aligned; every slot has its own zeroed stack and data
block. C programs explicitly exit; there is no return-address exit trampoline.

| ID | Call | Result / restrictions |
|---|---|---|
| 1 | write(pointer, length) | byte count; 0–256 bytes in shared image, own data block, or own stack |
| 2 | spawn(entry, argument) | positive PID; controller only; entries 1 spin, 2 sleep, 3 exit, 4 ownership probe |
| 3 | sleep(ticks) | 0 after wake; ticks 1–1000, units of 100000 timer counts |
| 4 | exit(status) | no successful return; worker only; status 0–255 |
| 5 | kill(pid) | 0; own live child only; leaves zombie status 137 |
| 6 | wait(pid) | status 0–255; blocks for own live child or immediately reaps own zombie |
| 7 | state(pid) | own child's state, including ZOMBIE |
| 8 | hits(pid) | own child's counted timer deliveries; works on unreaped zombie too |
| 9 | done() | controller-only test finish; requires timer switches and every child reaped |
| 10 | fail() | explicit guest-test failure and QEMU status 1 |

States: FREE=0, READY=1, RUNNING=2, SLEEPING=3, WAITING=4, ZOMBIE=5.
Errors: `-1 E_PID` invalid/stale/unallocated PID, `-2 E_OWNER` existing PID not
owned / worker spawn, `-3 E_FULL` no reusable slot (or exhausted generation),
`-4 E_ARG` invalid argument, unknown syscall, invalid pointer, forbidden controller
exit or repeated zombie kill. PID validity is checked before ownership. The tests
exercise both blocking and already-zombie wait, double wait, ownership, stale PID
while a replacement exists, allocated-slot and zombie-slot exhaustion, reaping
all seven workers and successful relaunch with a new generation.

Only write accepts a user pointer. The kernel validates the complete range with
subtraction before reading it; null, kernel addresses, wrapped ranges, crossings,
other slots' data/stacks and oversized writes are rejected. A zero-byte write
still requires its pointer to lie inside an allowed range. Lifecycle calls never
dereference user-selected pointers. Bad U traps are fatal to this teaching guest,
not individually recoverable process faults.

## Memory and scope

| Physical range | Use |
|---|---|
| `0x80200000...` | Kernel text/data, eight process frames, M trap stack and one S trap/C stack |
| `0x80400000..0x80407000` | Shared user text/rodata/compiler .data/.bss; linker asserts upper bound |
| `0x80407000..0x80407800` | Eight explicit 256-byte per-instance data blocks; cleared on launch |
| `0x80407800..0x80408000` | Reserved gap |
| `0x80408000..0x80410000` | Eight 4096-byte user stacks; cleared on launch |

The linker asserts BSS/data cannot overlap per-instance data and the eight-stack
budget fits exactly below `0x80410000`. The raw-image builder retains the old
64 KiB payload limits. Built-ins share code and fixed-address compiler globals;
**ordinary writable globals are NOT automatically private**. Private local data
lives on each stack or in the explicit a2 data block. There is no general ELF
process loader or per-process relocation. The kernel executes local `fence.i`
after the disk-loaded user image is ready and before launching U code.

PMP deliberately grants flat RWX physical access and `satp=0`: **no address-space
isolation, memory protection, guard pages or runtime W^X**. User code can directly
read/write other tasks and kernel memory; validating syscall pointers does not
make untrusted code safe. ELF RX/RW flags are descriptive, not enforced by this
flat raw loader. There is no filesystem, UART IRQ shell, SMP or hardware-board
validation in lesson07.

### Extension seam for lesson08 (not implemented here)

The process table owns frames/lifecycle; a hart owns its current slot, timer,
entry stack and scratch CSR. Lesson07's global `current`, deadline and single
S/M stacks are deliberately uniprocessor. A later lesson must use its own boot
entry to park secondaries **before** shared BSS/stack initialization and release
them after disk load; just adding `-smp 2` to this chapter is unsafe. It must add
per-hart current/timer/kernel and M-trap stacks, scheduler/lifecycle/console locks,
exclusive RUNNING ownership, a lock-aware idle path and cross-hart kill/wakeup
rules. It must execute `fence.i` on every hart that can run loaded code. The
selected-frame-pointer ABI can remain unchanged; derive each return's kernel
stack from hart state, never the process frame or the user SP. Eight process
slots remain a separate resource budget from the hart count. Freeze this lesson
only after independent read-only review and rerunning tests; no tag is implied
by this working-tree implementation.
