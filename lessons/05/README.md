# 05 — 给应用一套最小接口：syscall、mini-libc 与 heap

## What changes

Separate `kernel.c`, `user.c`, `user-start.S` and `libc.c` build a new pair of
payloads. This lesson **reuses, does not replace**, lesson04's M/S entry,
integer trap frame, supervisor trap assembly, kernel linker and user linker.
It also retains lesson03's bootloader and disk generator unchanged. The disk
format's `shell` slot now holds the user application at `0x80400000`.

The fixed memory layout and security caveats in [04](../04/README.md) still
apply. User startup clears its own linker-defined BSS before C runs; NOLOAD
sections are not present in the raw disk payload. Its stack was set by S.
All code is freestanding RV64IMAC with soft-float LP64, small-data addressing
disabled; neither libc nor an OS is linked from the host. No task scheduling,
interrupts, timers or files are introduced.

## Syscall ABI (not Linux and not SBI)

`ecall` from U enters S through delegated **cause 8**. `a7` is the syscall
number; arguments are in `a0..a5` (these calls use only a0/a1). A signed 64-bit
result is returned in `a0`; other integer registers are preserved by the
shared trap frame. There is no errno global. Unused arguments are ignored.

| a7 | Operation | Inputs | Result |
| --- | --- | --- | --- |
| 1 | console write | a0=pointer, a1=byte count | count, -14 EFAULT, -22 EINVAL |
| 2 | exit | a0=status | never returns |
| other | unsupported | ignored | -38 ENOSYS |

The C `syscall(number,arg0,arg1)` function first moves its ordinary C-ABI
arguments to this syscall ABI; the sole ecall is at **`0x8040001c`**. The
supervisor independently checks cause=8, this exact sepc and SPP=0 on **every**
call, not just the first reported one. It skips exactly that 32-bit ecall;
unexpected faults are fatal rather than silently skipped. `mini_exit` has a
noreturn fallback spin should the kernel violate its contract. Returning from
`user_main` is converted to exit by startup. Exit zero lets S print success
and write the QEMU finisher; nonzero prints failure and exits QEMU with 1.
This is whole-demo termination, not process reclamation or wait/reaping.

### Write validation contract

1. Length >256 returns -22, before checking the pointer, so SIZE_MAX also
   returns -22. No bytes are read or written on error.
2. Pointer must be in inclusive `[0x80400000,0x80410000]`, and length must be
   at most `0x80410000-pointer`. The subtraction is evaluated only after the
   pointer comparison passes; no overflowing pointer+length is ever formed.
3. Zero length is accepted at both endpoints, but an out-of-range pointer is
   still rejected even for zero length. One-past-end with nonzero length is
   rejected. Validation finishes before the output loop starts.
4. Accepted bytes are written verbatim, not as a NUL-terminated string.

This is **API validation within a flat RAM policy**, not page permission
validation, fault-safe copyin or a sandbox. The allowed range includes all
user text/data/BSS/heap/stack plus unused gaps. PMP permits all physical
addresses; malicious U code can bypass this interface, overwrite S memory
and touch MMIO. There is one hart, no concurrent mutation or page unmapping.
Real protection/copyin requires a later memory-isolation design.

## mini-libc and bounded heap

`strlen` counts bytes before NUL. `memcpy` copies a byte count and requires
nonoverlapping valid ranges. `memset` repeats the low eight bits of its int
value. All return the usual destination/length results; no hosted libc
behavior beyond these simple contracts is claimed. Invalid pointers in these
user functions are the application's responsibility, unlike syscall inputs.

`mini_alloc(size)` is a **user-local bump allocator**, not a kernel syscall:

- Linker reserves 16 KiB `[0x80408000,0x8040c000)` separately from the 16 KiB
  user stack. ELF/disassembly inspection shows the actual ranges.
- Alignment is 16 bytes. A one-byte request consumes 16; 17 consumes 32.
- Zero size returns NULL without consumption. Allocation is uninitialized.
- Check `size > SIZE_MAX-15` before rounding up, then compare rounded size
  with `end-next` before advancing the pointer.
- Overflow or exhaustion returns NULL and leaves the bump unchanged.
- **No free, realloc, coalescing, growth, brk or sbrk.** Lifetime is this one
  application's run; reboot/user BSS initialization resets the bump.
- Stack/heap bounds are linker/allocator conventions, not hardware protection.
  Stack overflow or malicious writes can still corrupt memory.

The U program verifies BSS/data initialization, checked write return values,
NULL and zero-length policy, lower/out-of-range/end-straddling/wrapping
pointers, 257 and SIZE_MAX lengths, unknown syscall, libc byte behavior and
zero-count operations. Heap tests check zero/rounding overflow/too-large
requests before allocation, exact aligned nonoverlapping addresses, sentinel
preservation, exact exhaustion, and repeated failed allocations.

## Reproduce and expected output

```sh
make clean all test inspect
make test-lesson05
script -q -e -c 'make test' build/pty.log
```

Tested with GCC 15.2.0, binutils 2.46, QEMU 10.2.1, Python 3.14.7 on Linux.
The positive guest output is exactly:

```text
Lesson 03: M-mode bootloader started.
Boot record validated; loading kernel and shell from disk.
Bootloader: both images loaded; jumping to kernel at 0x80200000.
Lesson 05: supervisor ready for syscall ABI.
trap: scause=0x0000000000000008 sepc=0x000000008040001c SPP=0
user: hello via syscall.
user: write bounds and unknown syscall rejected.
user: libc, aligned heap, overflow and exhaustion verified.
user: exiting.
PASS: user exit(0) recovered to supervisor.
```

`BAD_EXIT` runs the same checks, then returns 7: its last line must instead be
`FAIL: user exit status`, with QEMU status 1, not zero or a timeout.
`BAD_TRAP` executes a U read of `sstatus` before any syscall: expected
cause=2, sepc=`0x80400030`, SPP=0 and `FAIL: unexpected scause`, status 1.
The positive run must exit zero. The host oracle compares **all** ordered
lines and status, rejects extra output/truncation/timeouts, and saves each
transcript to `build/lesson05/disk*.img.log`. Full tests still exercise
lessons01–04, including the malformed boot record and independent cause/PC
rejection variants. These are actual QEMU executions, not mocked guest data.

## GDB

Use 04's QEMU `-S -gdb tcp::1234` command, changing only the disk to
`build/lesson05/disk.img`. Load `build/lesson05/kernel.elf` and
`add-symbol-file build/lesson05/user.elf`, and use hardware breakpoints:

```text
(gdb) hbreak *0x8040001c
(gdb) continue
(gdb) info registers a7 a0 a1 sp
(gdb) p/x $priv
(gdb) hbreak supervisor_trap
(gdb) continue
(gdb) info registers scause sepc sstatus sscratch sp
(gdb) p/x $priv
(gdb) hbreak trap_dispatch
(gdb) continue
(gdb) p/x *frame
```

Before ecall, priv=0, a7=1 and a0/a1 describe the greeting. At entry priv=1,
scause=8, sepc=0x8040001c, SPP=0. In C the frame is on S's stack and x[2]
contains U's original sp. Break `mini_alloc` to inspect `heap_next` and use
`p/x &__heap_start`, `p/x &__heap_end`, and `p/x &__user_stack_top` to check
capacity versus stack. The shared M emergency trap remains available for
unexpected nondelegated exceptions; it is not an SBI implementation.

## File ownership / review boundary

- `lessons/05/*`: new S syscall policy, separate U startup/application/libc/ABI.
- `lessons/04/*`: reused low-level runtime and linker, unchanged by 05.
- `lessons/03/*`, `lessons/02/*`, root `start.S`/`linker.ld`: unchanged.
- Root Makefile/README and `tests/run-privilege.py`: cumulative build/docs/test
  integration. No `fs.c`, external prototype or blog source is touched.

Simulator success demonstrates software and privileged-ISA behavior only;
there is no claim of RTL, FPGA, board or hardware-security validation.
