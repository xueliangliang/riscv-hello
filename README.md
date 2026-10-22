# RISC-V Bare Metal Lessons

This is the clean, cumulative teaching repository. The earlier OS prototype
stays separate as reference material. Each lesson adds one reviewable step;
annotated tags such as `lesson-01` and `lesson-02` pin the exact state used by
the matching blog post.

The current `main` contains two experiments:

- Lesson 01 builds a freestanding RV64 ELF and reaches `_start` on QEMU `virt`.
  The guest writes directly to UART and exits through QEMU's test device.
- Lesson 02 adds startup code for `gp`/stack/BSS, a small C `main`, and a polled
  UART driver. It checks BSS, initialized data, stack bounds, and serial output.

Neither lesson is an operating system yet: there is no privilege transition,
interrupt handling, scheduler, or filesystem.

## Reproduce

On the documented Ubuntu environment, install the packages listed in the first
blog post, then run:

```sh
make clean all
make inspect
make test
```

`make test-lesson02` runs only the C-runtime experiment. The full test run
prints a PASS line for both lessons, including:

```text
PASS: C runtime, stack, BSS, initialized data, and UART verified.
```

Use `make lesson02` to build only the C-runtime lesson. Generated files stay
under `build/` and are ignored by Git. Each lesson's ELF is for
inspection/debugging; its `.bin` file is a raw byte dump without ELF metadata.
