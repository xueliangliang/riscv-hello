# 04 — 从 M-mode 到 S-mode，再到 U-mode

## Result and scope

One hart runs the **unchanged lesson03 disk boot chain**. The boot record still
calls the second payload `shell`, but here it contains `user.bin`: this is a
repurposed slot, not an interactive shell. No filesystem, scheduler or timer.

| Physical range | Owner / purpose |
| --- | --- |
| `0x80000000` | lesson03 M bootloader, lesson02 startup/UART |
| `0x80200000` | lesson04 M entry, S kernel and supervisor stack |
| `0x80400000..0x80408000` | user text/rodata/data/BSS (link-time bound) |
| `0x80408000..0x8040c000` | reserved user heap, used in 05 |
| `0x8040c000..0x80410000` | 16 KiB descending user stack |

The disk generator retains its 64 KiB **file** limit per payload; NOLOAD BSS,
heap and stack are not file bytes. Kernel uses lesson03's linker and a separate
4 KiB emergency M trap stack within BSS plus its 16 KiB main/trap stack.

## Architectural contract

`start.S` clears kernel BSS, installs an emergency M trap handler, sets
`pmpaddr0=-1`, `pmpcfg0=0x1f` (NAPOT RWX), delegates exception bits 2 and 8
(`medeleg=0x104`), leaves interrupts disabled and `satp=Bare`, then executes
`mret` with MPP=S and SXL=UXL=64. S installs direct `stvec`, leaves `sie=0`, sets
SPP=0, `sepc=0x80400000`, the user stack and `sscratch`, and executes `sret`.
SIE alone would NOT disable interrupts while running U; `sie=0` matters.

U's `ecall` causes **8**, not S ecall cause 9. U's read of supervisor CSR
`sstatus` is an illegal instruction (**2**). SPP=0 independently records the
origin. In 04 the handler checks the cause AND exact PC at every phase before
advancing `sepc` by 4. This skip is valid only for these `.option norvc` probes;
it is not a general variable-length instruction decoder. `stval` is saved but
not assumed to contain instruction bits (implementations may report zero).

`trap.S` swaps the U stack for the trusted S stack via `sscratch`, then saves
all 31 writable integer registers and `sepc/sstatus/scause/stval` in a 288-byte,
16-byte-aligned frame. The saved x2 is the original U sp, never a pointer used
as the kernel stack. While in S, `sscratch=0`; a synchronous S-origin fault
keeps the S stack and is rejected by the C handler. Interrupts remain off;
this is not a general reentrant/nested-trap runtime. The initial S call chain
is intentionally abandoned on `enter_user`, so the trap stack can reuse its
top. No floating-point/vector state is enabled or saved. User self-checks
verify returned a0 and preserved t0/t1/s1/a3 after the first trap. The CSR
fault then returns to U; a final U ecall terminates **in S**, not by returning
to the M bootloader or running a privileged instruction in U.

**This is real instruction privilege, NOT memory isolation.** The all-address
PMP entry deliberately permits S/U loads, stores and execution everywhere;
there are no page tables. Malicious U code can overwrite the kernel/stack or
access UART/test MMIO directly. ELF RX/RW flags are descriptive only for this
raw loader. Do not run untrusted applications or call this a secure sandbox.

Normative references (RISC-V Privileged Architecture 1.13, 20260120 library):
- Machine-Level ISA: MPP/MRET, trap delegation and PMP address matching:
  <https://docs.riscv.org/reference/isa/v20260120/priv/machine.html>
- Supervisor-Level ISA: SPP/SRET, sscratch, sepc and scause:
  <https://docs.riscv.org/reference/isa/v20260120/priv/supervisor.html>
- CSR privilege encoding and illegal-access exceptions:
  <https://docs.riscv.org/reference/isa/v20260120/priv/priv-csrs.html>

## Reproduce and exact oracle

```sh
make clean all test inspect
make test-lesson04
script -q -e -c 'make test' build/pty.log
```

The positive guest transcript is exactly (UART uses CRLF):

```text
Lesson 03: M-mode bootloader started.
Boot record validated; loading kernel and shell from disk.
Bootloader: both images loaded; jumping to kernel at 0x80200000.
Lesson 04: supervisor entered after mret.
trap: scause=0x0000000000000008 sepc=0x0000000080400010 SPP=0
trap: scause=0x0000000000000002 sepc=0x0000000080400020 SPP=0
trap: scause=0x0000000000000008 sepc=0x0000000080400030 SPP=0
PASS: M -> S -> U, ecall, CSR fault, context, S recovery.
```

`BAD_CAUSE` changes the second probe to ecall (cause 8 at `0x80400020`),
requiring `FAIL: unexpected scause`. `BAD_PC` moves the CSR read one instruction
later (cause 2 at `0x80400024`), requiring `FAIL: unexpected sepc`.
Both real QEMU runs must exit 1; the positive run must exit 0 through the
finisher. The host compares the entire ordered transcript, not just PASS.
Every missing, duplicated or extra line and wrong exit code fails. A 10-second
timeout raises an error, including negative tests. Oracle self-tests reject
truncated transcripts, appended failures and timeout/failure statuses.
Per-image guest transcripts are written to `build/lesson04/disk*.img.log`.
The prior lesson03 malformed-disk test still runs in `make test`.

## GDB: observe, do not infer from a printed label

Terminal one, from the repository root (stop before the reset stub):

```sh
qemu-system-riscv64 -machine virt -global virtio-mmio.force-legacy=false \
  -smp 1 -m 128M -display none -serial stdio -monitor none -bios none \
  -kernel build/lesson03/bootloader.elf \
  -drive file=build/lesson04/disk.img,if=none,format=raw,id=disk,readonly=on \
  -device virtio-blk-device,drive=disk -S -gdb tcp::1234
```

Terminal two:

```text
gdb-multiarch build/lesson04/kernel.elf
(gdb) target remote :1234
(gdb) add-symbol-file build/lesson04/user.elf
(gdb) hbreak supervisor_main
(gdb) continue
(gdb) p/x $priv
(gdb) hbreak *0x80400010
(gdb) continue
(gdb) p/x $priv
(gdb) hbreak supervisor_trap
(gdb) continue
(gdb) info registers scause sepc sstatus sscratch sp
(gdb) p/x $priv
(gdb) continue
```

Expect priv=1 at supervisor_main, priv=0 before U ecall and priv=1 in the
handler; first trap has scause=8, sepc=0x80400010, sstatus.SPP=0. Inspect
`sscratch` before the entry swap (user sp) versus after (S stack top during U).
At the second trap cause=2 and sepc=0x80400020. Use hardware breakpoints because
payload RAM has not been loaded when GDB first attaches. `p $priv` availability
is QEMU/GDB-specific; scause/SPP/illegal-CSR behavior remains the architectural
proof. Single-step the entry to inspect the 288-byte frame. QEMU execution
validates software/architectural behavior, not RTL, FPGA or physical hardware.
