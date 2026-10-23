# Lesson 09 — U-mode interactive shell, UART RX IRQ and blocking reads

This milestone boots **both harts through lesson08's disk chain**, then runs
an interactive shell from the disk-loaded user payload. No host command
emulation, filesystem, arbitrary ELF loader or OpenSBI is involved.
Lessons01–08 are unchanged. This lesson owns its boot/runtime/shell files and
reuses lesson03's unmodified C/virtio loader and lesson02's UART TX helper.

## Build, run, inspect

From the repository directory:

```sh
make lesson09
make run-lesson09
# At the guest prompt: help; explicit shutdown exits QEMU.
make test-lesson09
make test-lesson09-gdb       # optional gdb-multiarch
make inspect-lesson09
make clean all
make test inspect
```

`run.py` contains the actual invocation. It uses `-smp 2`,
`-accel tcg,thread=multi`, `-cpu rv64,sstc=true`, `-bios none`,
`-kernel build/lesson09/bootloader.elf`, and a **read-only** virtio-block drive
`build/lesson09/disk.img`. The only `-kernel` is the bootloader, not the new
kernel. `run.py` uses serial stdio without QEMU's Ctrl-A multiplexer.

The session persists indefinitely without input. There is no production demo
watchdog or automatic completion syscall. `shutdown` is an explicit guest
request to the QEMU test finisher, not a real-board power controller.

## Small command contract

Commands are case-sensitive, space-delimited, with no quoting, pipelines,
redirection, environment expansion, path lookup or filesystem access. One
builtin name plus one optional unsigned decimal argument is accepted by `run`.

| Command | Actual behavior |
|---|---|
| `help` | List the command vocabulary |
| `echo text` | Print `echo: text` (no expansion) |
| `ps`, `jobs` | Same snapshot: occupied PID/state, timer hits and spinner progress |
| `run spin [arg]` | Launch disk-resident assembly increment/store loop; optional 0–255 arg ignored |
| `run sleep [ticks]` | Launch worker, block 1–1000 ticks (default10), exit23 |
| `run exit [status]` | Launch worker, exit0–255 (default0) |
| `kill pid` | Parent-only; synchronous result0 or remote RUNNING request result1 |
| `wait pid` | Parent-only; block for that exact child, return its status and reap it |
| `sleep ticks` | Block shell 1–1000 ticks; other tasks and IRQ delivery continue |
| `stats` | Print RX IRQ/bytes, queued/dropped, read blocks/wakes, wraps/consumed and hart timers |
| `shutdown` | Explicit exit0 through QEMU finisher; does not implicitly wait children |

Tick = 100000 shared time units at the DTB's 10MHz timebase, nominally10ms.
`run`, `kill`, `wait`, `sleep` print decimal `target=… result=…`; kernel audit
records use hexadecimal `pid=… value=…`. `job` state values are FREE0,
READY1, RUNNING2, SLEEPING3, WAITING4, ZOMBIE5, READING6. FREE entries are not
listed. A listing is a locked snapshot, not a promise that a process remains
in that state after output. Progress samples are observational aligned loads
of the worker's volatile per-instance counter, not a synchronized user transaction.

Errors: nonexistent/stale PID `-1`, wrong owner `-2`, occupied table `-3`,
invalid argument `-4`. Shell is slot0/PID16 and cannot exit or be killed by
its children. Seven child slots are independent of two execution harts.
PID = generation×16 + slot, never wrapping a generation. An exited child
remains an occupied zombie until **its own** parent waits it; no reuse before
reap. Slots remain pinned to `slot & 1`. Spawning is shell-only; no orphan
policy or descendants are claimed.

`kill` of a remote RUNNING child returns1, **not completion**: the owner saves
its entire frame at its next trap, acknowledges `kill_pending`, then publishes
zombie137. Parent must `wait` before slot reuse. READY/sleeping child kill
publishes zombie137 synchronously. Killing an existing zombie returns `-4`.

The editor has a95-byte line and four history entries. Up/Down traverse history
and restore the draft; Left/Right move the insertion cursor. Printable input
inserts, Backspace/ASCII DEL(127) delete before cursor, CSI `3~` deletes at
cursor. Tab completes a **unique command-name prefix** only (not arguments).
Redraw uses ANSI CSI erase/cursor-left. CR and LF submit; CRLF is one submit,
even when split across blocking reads. Additional printable bytes at a full
line are ignored. No Unicode, multiline input, terminal-size discovery or
loss-free bulk paste protocol is claimed.

## Why delayed input still works when every application blocks

Lesson08's S-mode polling idle kept SIE clear; merely adding `sie.SEIE` would
not let UART IRQs interrupt that idle loop. This lesson deliberately chooses
**genuine U-mode idle contexts**, not an S-origin nested trap path:

1. Each hart has an immutable288-byte idle frame, its own aligned256-byte idle
   stack, and a real disk-resident `idle_loop: j idle_loop` entry. These are
   scheduler housekeeping contexts, not process slots or user jobs.
2. No READY process: record `Hart.slot=-1`, arm local Sstc, release scheduler
   lock, restore that hart's idle frame, `sret` to U. User tp is sentinel0x1d1e.
3. UART can now cause U-origin supervisor external interrupt, even with shell
   READING and no worker. The ordinary trap entry switches using `sscratch`,
   saves all integer registers including user tp, then loads trusted `Hart*`
   from the top of **that hart's** S stack. `sscratch=0` throughout S.
4. Dispatcher detects slot−1; accepts only idle PC/U origin and timer/external
   causes, services IRQ under the global lock and selects newly READY shell.
   It does not treat idle as a process, index process[−1], recursively return
   into a live S scheduling C stack, or poll the UART RX register.
5. Selected process remains exclusively RUNNING/owned before unlocking;
   restore reestablishes `sscratch=hart.stack_top`, restores user's tp/SP and
   returns to U. SIE is **never** enabled in S or while a lock is held.

Both harts keep using independent trusted16KiB S stacks and4KiB M stacks.
The inherited assembly rejects unexpected S-origin traps; it is not presented
as a general S-origin interrupt handler. Idle is an ordinary U busy loop,
**not low-power WFI**. Remote READY publication needs no IPI here: periodic
local timers bound the next scheduling scan; a UART IRQ directly rescans hart0.
Tasks are pinned and every executing hart performs `fence.i` after disk loading.

## UART, PLIC and atomic wait registration

`board.py` independently dumps/decodes the exact QEMU DTB and requires:
`ns16550a` at0x10000000/size0x100, interrupt10, PLIC0x0c000000, matching
interrupt-parent, context order hart0 M/S then hart1 M/S,10MHz timebase.
`platform.json` records QEMU version and DTB SHA256. This is not board discovery
inside the kernel; the kernel intentionally targets that verified map.

Primary-source references used for the register meanings:

- QEMU tag `v10.2.1`, `hw/riscv/virt.c`, `include/hw/riscv/virt.h`: UART source10,
  bases, PLIC priority/enable/context offsets and strides; generated FDT order.
- Same tag `hw/char/serial.c`: LCR.DLAB0x80, IER.RDI0x01, LSR.DR0x01,
  byte-wide registers, RX FIFO behavior and read-to-remove receive bytes.
- Same tag `hw/intc/sifive_plic.c` and RISC-V PLIC specification
  `riscv/riscv-plic-spec/riscv-plic.adoc`, Interrupt Claim/Completion and
  memory map: read claim obtains/clears pending ID; write same ID completes.

Boot sets UART LCR3 (DLABclear,8N1), FCR7 (FIFO on/reset, one-byte trigger),
IER1 (RX only); source10 priority1; hart0 S enable0x0c002080 bit10;
threshold0x0c201000=0; claim/complete0x0c201004. Both harts delegate SEIP and
STIP (`mideleg=0x220`) and enable those causes (`sie=0x220`), but only hart0's
S PLIC context enables source10. No PLIC operation acknowledges Sstc.

`console_interrupt` is the **only** consumer of UART receive data: claim10,
drain currently available FIFO bytes while LSR.DR, enqueue/count drops,
wake reader if appropriate, I/O fence, complete10. Claim0 is a permissible
spurious/no-source return and does not increase the actual source10 counter.
There is no wait for a future character inside that handler or any syscall.
TX remains polled and serialized by the kernel lock.

RX ring capacity128, FIFO order, modulo indices, **drop newest** on full,
monotonic drop/received/consumed/wrap counters. No unread byte is overwritten.
A hardware FIFO overrun is distinct from the software ring's counted drops;
the tests establish the ring policy under QEMU, not a loss-free physical UART.
Overflow can truncate input, including a delimiter: send a fresh newline to
finish/discard the retained line, then enter a new command. Buffering is not
flow control. Tests intentionally recover this way, rather than pretend that
an overflowing arbitrary paste is atomic.

`SYS_READ` holds the same acquire/release scheduler lock as IRQ enqueue:
nonempty → dequeue one unsigned byte; empty → set shell READING and return
through scheduler. IRQ supplies the first retained byte in saved a0 and
publishes READY atomically. Thus IRQ enqueue cannot occur between an unlocked
empty check and waiter registration. One reader (shell only) avoids an
unstated multi-consumer policy. No input spin/wait while holding global lock.

## ABI and memory

`a7` number, `a0/a1` arguments, `a0` result; only U ecall advances PC4.
Asynchronous PCs are untouched. Integer-only288-byte frames, no FPU/vector
support. Syscalls1–8,10–11 retain WRITE/SPAWN/SLEEP/EXIT/KILL/WAIT/STATE/HITS,
FAIL/HART;9 now means explicit shell shutdown. New14=READ byte,15=PS,
16=STATS. Lesson08 test-only12/13 are reserved/unimplemented (`-4`).
READ/SHUTDOWN/SPAWN are shell-only. PS/STATS are pointer-free diagnostics.
WRITE remains ≤256bytes in shared image or caller's own stack/data. Unknown
syscalls return `-4`. This is validation, **not memory isolation**.

Kernel at0x80200000, user image at0x80400000, code/data/BSS below0x80407000;
eight256-byte instance blocks at0x80407000; eight4096-byte stacks at
0x80408000–0x80410000. User .data/.bss are deliberately shared, not relocated
per process; editor history is shell-only. Two extra idle stacks/frames are
kernel BSS, not stolen child slots. Linker assertions protect the ranges;
raw disk kernel/user payload budgets remain64KiB each. ELF RX/R/RW flags are
inspectable but flat PMP grants all physical memory: no W^X/security claim.

## Evidence and limits

`test.py` uses actual serial PTYs and readonly generated disks. Timeouts fail.
`pty.log` exercises every command, unknown recovery, Tab, recalled edited
command **execution**, insertion/backspace/forward delete, Up/Down and CRLF;
blocks shell with no workers before delayed input and checks actual IRQ/wake
counter increases; observes spinner progress while shell blocks in wait;
checks remote deferred kill/status137, all seven unreaped zombies, exhaustion,
exact wait status for each PID, stale/invalid IDs, reap/relaunch, wrap/drop
conservation and recovery after an800-byte burst while shell sleeps.
`concurrent.log` separately runs seven spinner instances together (eight live
process slots), observes every instance's increasing counter across shell
sleeps, tests live exhaustion, then kills/waits each exact PID.

`oracle.py` independently correlates spawn/generation, exact
wait-call(parent,target), wait-block, that child's zombie/status, return and
reap, then matches actual shell `wait target=… result=…` output. It also checks
executed echo results, not echoed edit input. Mutations change target/status,
remove all wait blocks or command execution/results, and append a late fault;
all must be rejected. `timeout-rejected.log` records a real stopped-VM timeout.
`disk-bad-irq.img` disables UART IER.RDI: after shell blocks, a **negative-image
only** timer watchdog emits explicit `FAIL: UART IRQ delivery disabled: blocked
reader watchdog` and exits1; timeout or normal success is not accepted.

`test-lesson09-gdb` waits until disk loading, then catches a real delayed-byte
external IRQ while slot−1 and shell READING. It checks U-origin/idle PC,
saved user tp, trusted hart metadata, `sscratch=0`, actual IRQ/wake increment,
byte101 (`e`), owner/lock release and actual restored SP/tp/sscratch before
`sret`. After detach it sends `cho gdb-woke`, requires actual `echo: gdb-woke`,
then explicit shutdown0. Logs: `gdb.log`, `gdb-uart.log`.

These are QEMU software/architectural observations. They do not prove physical
UART timing/electrical behavior, device FIFO overrun absence, RTL correctness,
FPGA behavior, real-board interrupt routing/power management, isolation,
scalable/fair locking or real-time latency. No hardware was tested.
