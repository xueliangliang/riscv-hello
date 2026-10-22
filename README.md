# RISC-V Bare Metal: Lesson 01

This repository starts a new, clean teaching implementation. The earlier OS
prototype is kept separately as a reference; this codebase is rebuilt one small,
reviewable, tested step at a time.

Lesson 01 builds a freestanding RV64 ELF, checks its architecture and entry
address, then runs it on QEMU's `virt` board. The guest writes one line directly
to the emulated UART and exits through QEMU's test device. It has no C runtime,
kernel, interrupts, scheduler, or filesystem yet.

## Reproduce

On the documented Ubuntu environment, install the packages listed in the first
blog post, then run:

```sh
make clean all
make inspect
make test
```

Expected final line:

```text
PASS: RISC-V ELF entry and UART output verified.
```

Generated files are kept under `build/` and are ignored by Git. The ELF is for
inspection/debugging; `lesson01.bin` is a raw byte dump without ELF metadata.
