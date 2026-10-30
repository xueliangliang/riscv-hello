# 13 — ordinary-file executables and a PIC math.dll

The disk-loaded U shell can now run `math_test` from an **ordinary BPTFS12
file**. That separately linked executable snapshots `math.dll`, validates its
whole export table, resolves four typed symbols, and calls the actual loaded
RISC-V instructions at two different addresses. It then invalidates the handle
and clears each module bank. This is a custom teaching format, not ELF/PE
compatibility, a security boundary, or a compiler milestone.

## Run from the repository root

Prerequisites are the same RV64 cross GCC/binutils, host C compiler, Python3,
QEMU system emulator and `gdb-multiarch` used by the earlier lessons. No Python
packages are required.

```sh
make lesson13
make run-lesson13
```

In a fresh guest:

```text
ls
./math_test
exec math_test
wait 17
./math_test
wait 33
fwrite saved hello-loader
cat saved
shutdown
```

`exec math_test` immediately after the first launch returns `-13` (busy). The
application intentionally sleeps50 timer ticks so the live reservation can be
observed. It subsequently prints exact binary64 call results, `CHECK ... OK`,
and exits37. Even after that exit, another exec remains busy **until `wait 17`
reaps its ZOMBIE**. The next fresh slot1 generation is PID33, not17. Typed export
lookup rejects an absent name, a wrong signature and stale handles. Resolved
raw function pointers must never be called after unload; they cannot be revoked.

`run spin|sleep|exit`, `kill`, `wait`, `ps`, journaled file commands, UART editing
and explicit shutdown remain the inherited shell interface. `run` still selects
compiled workers; **only `exec NAME` or `./NAME` invokes the new file loader**.
To exercise receiving hart0 manually, leave an odd-slot worker unreaped/live,
then launch the file application in the next even slot. PIDs encode generation
and slot; harts are fixed execution affinities, not process identities.

The launcher creates `state/lesson13/disk.img` only if absent, then holds a
nonblocking host lock for the complete VM lifetime. Ordinary build/clean/reboot
does not replace this disk. Existing missing/corrupt files are not reseeded.
For a separate writable disk:

```sh
make run-lesson13 LESSON13_ARGS='--disk state/lesson13/demo.img'
```

**Destructive reset**, only on explicit request:

```sh
make reset-lesson13
# Or reset a selected disposable image, without starting QEMU:
python3 lessons/13/run.py --disk state/lesson13/demo.img --reset
```

Reset installs the current fresh fixture and destroys that target's old files.
The fresh build fixture is `build/lesson13/disk.img`, never a saved prototype
image. `seed.py` formats a new staging file and writes `math_test` and `math.dll`
through the actual C filesystem/journal before atomic fixture installation.
There is no runtime seed pointer or boot-time file repair.

## Trace the layers

1. `boot.S` preserves the secondary-hart parking/release protocol; lesson03's
   unchanged bootloader reads the kernel and shell from their original disk
   slots. No direct-new-kernel boot shortcut is used.
2. The inherited lesson12 `kernel.c:135–169` launched compiled shell/worker entry
   addresses; its `file_syscall:267–354` was shell-only, with no handle ownership
   tags. It was not already an ordinary-file application loader.
3. Lesson13 adds EXEC30, shell-only, with a bounded contiguous filename check.
   `snapshot_read` opens existing/read-only, reads through logical EOF, checks
   capacity and closes on all paths. The staged byte parser runs before any
   application RAM copy or READY publication.
4. Payload copies to0x80500000, BSS is zeroed afresh, and one process owns that
   code region until WAIT/reap. Eight inherited process slots retain distinct
   stacks and generation-bearing PIDs. A failed load publishes no child.
5. READFILE31 is restricted to the **actual designated file process**. It admits
   that process's application memory but not a worker's pointer into it. Old
   handle-based calls remain shell-only. An exact successful snapshot alone is
   copied out; missing files, insufficient capacity and IOERR leave the user
   target untouched. No application file-write syscall is introduced here.
6. The U `module_loader.c` stages the real filesystem file, checks **every**
   export with `formats.c`, copies a checked image into one of two alternating
   4096-byte BSS banks, fences and publishes a generation token. A second load
   cannot change an active image. Unload clears bytes and invalidates lookup.
   Generation saturation refuses further activations rather than wrapping.
7. `math_test.c` does not link `math_dll.o`. It resolves `ceil`, `floor`, `max`,
   `min` and calls typed pointers. The alternate DLL deliberately changes ceil
   to42.0; replacing only that file changes the unchanged application's output.

[FORMAT.md](FORMAT.md) freezes every byte/ABI field and validation rule.
`pack.py` rejects unresolved relocations, GOT, imports, data/BSS and TLS in the
module ELF intermediate. Runtime containers carry no relocation support; they
are not a machine-code verifier. Trusted producers must obey the PIC contract.

## Memory and ABI

- QEMU RAM:0x80000000–0x88000000 (128MiB).
- Boot kernel slot:0x80200000, maximum65536 file bytes. Its large inherited
  journal/FS BSS must end **before shell0x80400000**.
- Shell image/BSS:<0x80407000. Per-slot data:0x80407000–0x80407800.
- Eight separate4096-byte stacks:0x80408000–0x80410000.
- One file application:0x80500000–0x80510000, including payload, zeroed BSS,
  staging and both private module banks. Its stack remains process-owned.

`binary-test.py` records measured ELF/raw sizes and exact BSS/bank addresses in
`build/lesson13/binary-results.json`, and asserts these boundaries. Module
arenas are static application BSS, not a kernel heap increase.

The ISA remains RV64IMAC/Zicsr/Zifencei, **lp64 soft-float ABI**. Doubles travel
in integer argument/return registers. The bit-level binary64 math requires no
soft-float helper library and no floating register context. See FORMAT for
signed-zero/infinity/NaN policy; no ISO libm/fenv/exception conformance is claimed.

The producer publishes copied data and READY under the scheduler's release/
acquire lock. On first scheduling, **the receiving hart** executes its local
`fence.i` after observing publication, before U entry. Fencing only the copying
hart would not synchronize a remote hart's instruction stream. Affinity remains
pinned; the U loader locally fences module copies before its own calls. If
migration is later introduced, this contract must be extended. GDB confirms
these instructions and execution sites; QEMU does not certify physical I-cache
incoherence, and removing a fence need not cause visible stale execution there.

## Reproduce the evidence

```sh
make test-lesson13
make inspect-lesson13
make test-lesson13-gdb
make test-lesson13-evidence
# Full cumulative acceptance, including actual earlier debugger gates:
make all test inspect
make test-lesson07-gdb test-lesson08-gdb test-lesson09-gdb
make test-lesson10-gdb test-lesson11-gdb test-lesson12-gdb test-lesson13-gdb
```

The ordinary lesson13 gate invalidates old evidence **before building**, then
runs:

- Native tests of the actual C parsers (including truncation, versions,
  overflow, EOF, table/target/alignment/name/duplicate/signature failures),
  the U C module lifecycle (including saturation), and the actual FS snapshot
  with strict ctypes signatures and handle cleanup on injected read failure.
- Independent host math expectations, not calls to the implementation's math.
  Exact input/output bits cover positive/negative fractions, exact integers,
  signed zero (including binary ties), subnormals, large exponents, infinities,
  quiet/signaling NaN bits and both-NaN selection.
- Two cold dual-hart VMs on the same image. Real UART commands exercise all
  malformed executable files, actual U malformed module loads, live and ZOMBIE
  busy checks, exact per-PID wait37, BSS/relaunch, both hart affinities, worker
  coexistence, slot pressure, stale PIDs and normal journal writes/shutdown.
- Independent raw tree/bitmap/chain/file decoding. Executable/DLL full bytes,
  boot slots, clean journal and saved cold content are checked after each boot.
  The alternate DLL fixture proves rebinding without changing the application.
- An isolated real QEMU blkdebug error, armed after mount by an actual shell
  write. U READFILE observes device IOERR status1, checks unchanged destination
  bytes and inactive module state, exits43 and is reaped; sticky poisoned FS
  rejects another exec and explicit shutdown fails. This is not a fake printf
  or only a native injected C return.
- Real copy-once launcher, competing run/reset locks, build/reboot persistence,
  deleted executable staying absent, explicit reset and existing corrupt FS
  staying untouched.

`runtime-results.json`, `binary-results.json`, `results.json`, `cold-*.log`,
`variant.log`, `io-U-snapshot.log`, `launcher-*.log` retain the actual evidence
under `build/lesson13/`. `gdb-loader.log` proves receiving harts0/1 fence, U app
entry, U module entry, local U module fence, full copied DLL bytes and exact
`pointer=base+export_offset`; UART continues through shutdown after detach.

The cold-content regression also boots a deliberately wrong persisted file:
the old overwrite-first order admits it, while the new read-before-write gate
rejects its actual guest output. This repairs an oracle gap, not a demonstrated
kernel persistence defect.

The evidence regression mutates name/signature/math/base/PID/status/hart/cold
content and requires oracle rejection. It also runs real partial-output,
nonzero, timeout and pre-collect-error children, verifies reaping, deliberately
fails the public gate with a wrong CC, fails early debugger setup, runs real
GDB then `/bin/true`, and rejects stale PASS. It restores the real runtime and
GDB gates at the end. Attack transcripts survive the next outer gate under
`$TMPDIR/lesson13-evidence/` (or `build/lesson13/lesson13-evidence/` if unset).

All storage mutation fixtures are disposable. The BPTFS12 format, geometry,
1024-sector journal and four-FLUSH protocol are inherited unchanged. This lesson
adds loading, not journal redesign, process isolation, general dynamic linking,
a guest compiler, benchmarks or real-board certification. Flat PMP admits U RAM
access; validation and owner checks are **not** a sandbox or production security.
