# RISC-V Bare Metal Lessons

This is the clean, cumulative teaching repository. The earlier OS prototype
stays separate as reference material. Each lesson adds one reviewable step;
annotated tags such as `lesson-01`, `lesson-02`, and `lesson-03` pin the exact
state used by the matching blog post.

The current `main` contains seven experiments:

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

Lessons01–06 remain unchanged. There is still no filesystem or address-space
isolation: PMP grants flat physical access and there are no page tables.
Lesson07 owns its scheduler/runtime and keeps lesson03's real disk boot chain.
Run `make lesson07` / `make test-lesson07`; optional `make test-lesson07-gdb`
checks A's timer trap through restoration of B's actual SP/sepc before `sret`.
See the chapter README for ABI, scope, direct QEMU commands and log oracles.
Run `make lesson04` / `make test-lesson04`, `make lesson05` /
`make test-lesson05`, or `make lesson06` / `make test-lesson06` for earlier steps;
full `make test` keeps all earlier regressions. Guest logs are under
`build/lesson04/` through `build/lesson07/`.
Lessons06–07 explicitly use QEMU `-cpu rv64,sstc=true`; they do not use OpenSBI,
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
