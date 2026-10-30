# RISC-V Bare Metal Lessons

This is the clean, cumulative teaching repository. The earlier OS prototype
stays separate as reference material. Each lesson adds one reviewable step;
annotated tags such as `lesson-01`, `lesson-02`, and `lesson-03` pin the exact
state used by the matching blog post.

The cumulative repository contains twelve experiments:

- Lesson 01 builds a freestanding RV64 ELF and reaches `_start` on QEMU `virt`.
  The guest writes directly to UART and exits through QEMU's test device.
- Lesson 02 adds startup code for `gp`/stack/BSS, a small C `main`, and a polled
  UART driver. It checks BSS, initialized data, stack bounds, and serial output.
- Lesson 03 starts a small M-mode bootloader with QEMU's modern virtio-mmio
  block device, validates a boot record, loads separate raw kernel and shell
  payloads, and jumps to the kernel. The kernel calls the tiny shell payload;
  this is a loading demo, not an interactive shell. A malformed boot-record
  test checks the rejection path.

- [Lesson 04 — 从 M-mode 到 S-mode，再到 U-mode](lessons/04/README.md)
  reuses that disk loader, enters S then U, and proves U origin with delegated
  ecall/illegal-CSR traps, exact cause/PC checks and context restoration.
- [Lesson 05 — 给应用一套最小接口：syscall、mini-libc 与 heap](lessons/05/README.md)
  adds checked console write/exit syscalls, a freestanding user libc and a
  bounded aligned bump allocator, retaining the lesson03/04 loading/runtime.

- [Lesson 06 — 中断：保存现场，再回到原来的程序流](lessons/06/README.md)
  retains the disk loader and adds three asynchronous Sstc timer interrupts
  during ordinary U instructions, exact integer-context/PC restoration and
  user self-checks. This is **not** scheduling or a task switch.

- [Lesson 07 — 保存 A 的现场，恢复 B：抢占式调度与进程生命周期](lessons/07/README.md)
  adds timer-preemptive round-robin user contexts, independent stacks/data blocks,
  blocking sleep and spawn/exit/kill/wait/reap/relaunch. A real U-mode controller
  tests eight-slot exhaustion, unreaped zombies, ownership and generation PIDs.

- [Lesson 08 — 两个 hart 真正执行用户进程：启动顺序、锁与生命周期](lessons/08/README.md)
  adds a hart-filtering disk-boot wrapper, per-hart M/S stacks and Sstc setup,
  globally locked lifecycle/scheduling with explicit pinned affinity, and safe
  remote RUNNING kill. Real U workers on both harts contend on a shared lock
  and verify an exact 8000-update counter; broken locking/restoration fail.

- [Lesson 09 — Interactive U shell and interrupt-driven serial input](lessons/09/README.md)
  retains dual-hart disk boot, routes UART RX through hart0's S PLIC context,
  blocks reads atomically with IRQ wakeup, and uses genuine U idle contexts
  so delayed input arrives even when every application is blocked. Includes
  cursor/history editing, concurrent builtins and exact owned wait/reap tests.

- [Lesson 10 — 块设备到最小文件系统：先把数据放对位置](lessons/10/README.md)
  adds modern virtio-blk READ/WRITE/FLUSH, a validated sixteen-file fixed-extent
  filesystem, shell-only checked file handles/ecalls, exact EOF and cold-boot
  persistence. Its fresh build fixture is separate from the ignored writable
  `state/lesson10/disk.img`; ordinary builds and `make clean` preserve files.
  Run `make run-lesson10`, `make test-lesson10`, or optional
  `make test-lesson10-gdb`. **`make reset-lesson10` destroys saved files.**

- [Lesson 11 — 有边界的 B+ 树文件系统](lessons/11/README.md)
  adds an independent little-endian B+ tree backend with real multilevel splits,
  separate node/data bitmaps, chained payload, bounded U-mode paged listing,
  seek/append/truncate, deletion/reuse and actual data-block defragmentation.
  Independent raw decoding and repeated writable-image cold boots verify contents.
  Run `make run-lesson11`, `make test-lesson11`, or optional
  `make test-lesson11-gdb`. **`make reset-lesson11` destroys saved lesson11 files.**
  No journal, directories, full deletion rebalancing or production guarantees.

Lessons01–10 remain unchanged by lesson11. There is still no address-space isolation:
PMP grants flat physical access and there are no page tables.
Lesson07 owns its scheduler/runtime and keeps lesson03's real disk boot chain.
Run `make lesson07` / `make test-lesson07`; optional `make test-lesson07-gdb`
checks A's timer trap through restoration of B's actual SP/sepc before `sret`.
See the chapter README for ABI, scope, direct QEMU commands and log oracles.
Run `make lesson04` / `make test-lesson04`, `make lesson05` /
`make test-lesson05`, or `make lesson06` / `make test-lesson06` for earlier steps;
full `make test` keeps all earlier regressions. Guest logs are under
`build/lesson04/` through `build/lesson12/`.
Run `make run-lesson09` for the persistent shell; only `shutdown` exits it.
`make test-lesson09` drives real serial PTY commands, cursor/history/Tab edits,
owned wait/reap, slot exhaustion and RX overflow recovery. Optional
`make test-lesson09-gdb` checks an idle-origin UART IRQ through reader wakeup
and actual U register restoration, then executes the rest of that input line.
Run `make lesson08` / `make test-lesson08`; optional `make test-lesson08-gdb`
checks actual timer-frame restoration separately on both harts. Lesson08's
persistent lock-aware idle polls with SIE disabled; it is not an interactive
shell or an interrupt-driven console, and its demonstration exits only through
an explicit U controller DONE syscall.
Lessons06–08 explicitly use QEMU `-cpu rv64,sstc=true`; they do not use OpenSBI,
an M-mode timer relay, PLIC timer interrupts or cooperative yielding.

## Reproduce

On the documented Ubuntu environment, install the packages listed in the first
blog post. Lesson 03 additionally uses Python 3's standard library to pack the
boot-record disk image. Then run:

```sh
make clean all
make inspect
make test
```

`make test-lesson02` and `make test-lesson03` run one lesson each. The full test
run prints a PASS line for every lesson, including:

```text
PASS: C runtime, stack, BSS, initialized data, and UART verified.
PASS: disk boot handoff works and a bad boot record is rejected.
```

Use `make lesson02` or `make lesson03` to build a lesson's artifacts. Generated
files stay under `build/` and are ignored by Git. Each lesson's ELF is for
inspection/debugging; its `.bin` file is a raw byte dump without ELF metadata.

## Lesson 12 — Bounded full-data redo journal

[Lesson12](lessons/12/README.md) adds 1024 deduplicated sector after-images,
read-your-writes, ordered device FLUSH and validated cold replay over the B+
tree filesystem. Each mutator API is atomic, not an entire shell command.
Oversized operations fail atomically with `F_LIMIT=-17`; device errors are
sticky and may already have persisted, requiring recovery. The native actual-C
volatile/durable model and independent raw decoder complement 64 QEMU software
interruption boundaries and real dual-hart U-shell cold replay; these are not
real-board power-cut guarantees. Lessons01–11 remain unchanged.

Run `make run-lesson12`, `make test-lesson12`, `make inspect-lesson12` or optional
`make test-lesson12-gdb`; cumulative `make all test inspect` includes lesson12.
The ignored `state/lesson12/disk.img` is copied once and survives builds/clean.
**`make reset-lesson12` destroys saved lesson12 files.** BPTFS11 images are
rejected without modification, not automatically migrated. See the lesson's
[format contract](lessons/12/FORMAT.md) for layout, capacity and error uncertainty.

## Lesson 13: ordinary-file loader and dynamic math.dll

`make run-lesson13` boots the journaled dual-hart shell. `./math_test` loads a
validated custom executable from the filesystem; the application resolves and
calls four soft-float-ABI PIC math exports from the actual `math.dll` file.
See [lesson13 instructions and verification](lessons/13/README.md) and the
[byte-format contracts](lessons/13/FORMAT.md). `make test-lesson13`,
`make test-lesson13-gdb`, and `make test-lesson13-evidence` exercise cold boots,
both receiving harts, typed pointers, unload/reload, alternate-file rebinding
and stale-evidence attacks. This is not ELF/PE loading or process isolation.
The new `state/lesson13/disk.img` is copy-once; only explicit `reset-lesson13`
destroys it. Earlier lesson sources and bootloader remain unchanged.


## Lesson 14: guest-running integer C-subset compiler

[Lesson14](lessons/14/README.md) closes raw UART source paste → actual guest
source file → separate U-mode `cc` → genuine RV64 executable file → compiler
exit/wait/reap → independent native execution → cold reboot/run without cc.
This is host-built/guest-running, not self-hosting or full ISO C. The bounded
integer language and ABI2 argument/memory contract are explicit; inherited
ABI1 math_test/DLL behavior remains available, but floating/compiler dynamic
math runtime integration is later scope. Whole-file output publication is one
journal transaction; deterministic failures preserve old bytes or absence.

Run `make run-lesson14`, `make test-lesson14`, `make inspect-lesson14`,
`make test-lesson14-gdb` and `make test-lesson14-evidence`. Saved lesson14 disks
are copy-once and survive clean/rebuild. **`make reset-lesson14` destroys saved
lesson14 files.** `LESSON14_ARGS='--disk ...'` selects run/reset targets under
the same competing-process lock. Earlier lessons, tools and published tags
remain unchanged. No board/cache/power-cut certification or process isolation
is implied by QEMU functional tests.
