# RISC-V Bare Metal Lessons

This is the clean, cumulative teaching repository. The earlier OS prototype
stays separate as reference material. Each lesson adds one reviewable step;
annotated tags such as `lesson-01`, `lesson-02`, and `lesson-03` pin the exact
state used by the matching blog post.

The current `main` contains three experiments:

- Lesson 01 builds a freestanding RV64 ELF and reaches `_start` on QEMU `virt`.
  The guest writes directly to UART and exits through QEMU's test device.
- Lesson 02 adds startup code for `gp`/stack/BSS, a small C `main`, and a polled
  UART driver. It checks BSS, initialized data, stack bounds, and serial output.
- Lesson 03 starts a small M-mode bootloader with QEMU's modern virtio-mmio
  block device, validates a boot record, loads separate raw kernel and shell
  payloads, and jumps to the kernel. The kernel calls the tiny shell payload;
  this is a loading demo, not an interactive shell. A malformed boot-record
  test checks the rejection path.

These are still boot/bring-up exercises, not an operating system: there is no
privilege transition, interrupt handling, scheduler, or filesystem.

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
