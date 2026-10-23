# Lesson 10 — 块设备到最小文件系统：先把数据放对位置

Disk-loaded U shell → checked file ecall → sixteen-entry flat directory →
modern virtio-blk READ/WRITE/**FLUSH** → independent cold boot → exact named
file contents. This is a bounded filesystem, not the old prototype's B+tree.

```sh
make lesson10
make run-lesson10
# At 10>:
fwrite first hello persistent disk
fwrite second a different file
ls
cat first
fwrite first short
cat first
rm second
fsinfo
shutdown
# Start again: first remains, second does not.
make run-lesson10
```

The 95-byte shell command limit is intentional. `fwrite NAME TEXT` explicitly
creates/replaces; `cat NAME` never creates. Names use 1–31 characters from
`[A-Za-z0-9_.-]`. Each of sixteen files owns a fixed 4096-byte extent; four
generation-safe handles, shell-only ownership, bounded 4096-byte I/O, exact
logical EOF. `fsinfo` reports successfully completed READ/WRITE/FLUSH counts.
`fstest` runs destructive bounded syscall tests **on a fresh disposable
filesystem**; `fsverify` reads the resulting patterns without replacing them.
Both are real U-mode programs using the same ecalls as interactive commands.

[FORMAT.md](FORMAT.md) defines every disk field, syscall number/argument/error,
name/pointer validation, truncation, timeout and durability boundary. There is
no on-disk compatibility with the older prototype, no B+tree, seek, append,
journal, rollback or power-loss atomicity. Those are deliberately not smuggled
into this first storage lesson. A failed write may have modified sectors.

## Boot and interrupt continuity

Only the hart-filtering bootloader wrapper is supplied to QEMU `-kernel`.
The unchanged lesson03 C loader reads the boot record and both payloads from
the actual disk, then enters this lesson's M→S→U runtime. The kernel resets
and re-negotiates the **same** virtio device, with its own static queue and
bounce buffer, rather than retaining bootloader queue addresses.

The lesson09 files were copied into `lessons/10/`; lessons01–09 are unchanged.
Two harts, eight process slots, pinned worker affinities, generation PIDs,
run/kill/wait/reap, real PLIC UART RX, user idle, bounded history/cursor/Tab
editing and console WRITE all remain. File WRITE is a distinct syscall.
The new commands participate in completion via the array's actual count.

Synchronous device polling is serialized by the existing global scheduler
lock with SIE off. Each request has a one-second `rdtime` timeout on QEMU;
multiple requests can occur per file call. Timer/UART service is delayed,
not magically concurrent with disk polling, and input floods may overflow
the hardware FIFO. No human input is awaited under the lock. A device error
poisons the mount and causes subsequent file operations/shutdown to fail;
DMA buffers remain static even after a timeout. A CPU fence is not FLUSH.

## Do not destroy the reader's disk during ordinary builds

- `build/lesson10/disk.img` is a **fresh build fixture**, never the default run
  disk. Rebuilding it is harmless to the persistent image.
- First `make run-lesson10` atomically installs a copy at
  `state/lesson10/disk.img`; subsequent runs/builds do **not** refresh or copy
  that disk. `make clean` removes `build/`, **not** `state/lesson10/`.
- Persistent images are ignored by Git. Launcher copying, reset and QEMU
  lifetime hold the same nonblocking advisory host lock `<disk>.lock`.
- `make reset-lesson10` is an **explicit destructive reset**: it discards all
  files and reinstalls the current kernel/user/empty FS fixture, then exits.
  Rebuilds do not silently update a persistent disk's embedded kernel/user.
- An alternative independent disk can be selected explicitly:

  ```sh
  python3 lessons/10/run.py --disk state/lesson10/alternate.img
  # Explicit data loss on that selected disk:
  python3 lessons/10/run.py --disk state/lesson10/alternate.img --reset
  # Or through make:
  make run-lesson10 LESSON10_ARGS='--disk state/lesson10/alternate.img'
  ```

An existing damaged or unrecognized filesystem fails mount; it is never
silently reformatted. Do not pass a valuable disk to the explicit reset or
fresh fixture formatter. Raw direct QEMU invocations bypass the Python
advisory lock and are unsupported concurrently with the launcher.

## Executable verification

```sh
make test-lesson10
make test-lesson10-gdb       # optional; gdb-multiarch
make inspect-lesson10
make clean all test inspect # cumulative lessons01–10
```

Tests use serial PTYs and real guest ecalls; they never emulate filesystem
commands on the host. All working images are disposable under `$TMPDIR`
(the configured scratch directory), and both protected fixture hashes are
checked in `finally`. QEMU timeouts fail the test; every process is reaped.
The suite checks:

- distinct shell-created names, exact `cat` contents and return values,
  shorter overwrite, missing reads, delete/recreate and distinct listings;
- U syscall patterns of **511/512/513/1024/4096** bytes, repeated unaligned
  257-byte reads, transient 4096-byte NUL/high-bit binary pattern, logical EOF and untouched EOF output, empty files,
  directory/handle exhaustion, bad/stale tokens, busy files, 31/32-byte and
  unsafe names, null/wrapped pointers, invalid mode, reserved remove/list/info
  arguments and 4097-byte rejection;
- three independent QEMU processes on the same writable shell disk and two
  on a pattern disk, exact named reads after reboot, no re-seeding;
- a separately implemented Python decoder of raw header/records/payload,
  exact logical sizes/content, zero unused records, per-slot offsets, zero
  padding from **every** file's logical size to the end of its 4096-byte
  extent, and unchanged **all LBA0–256** protected boot bytes;
- malformed header/used/name/padding/reserved/size/offset/duplicate records,
  real readonly feature rejection, labeled missing-FLUSH feature injection;
- actual QEMU **blkdebug EIO** on metadata READ, payload WRITE and FLUSH,
  including the driver-visible `request-type`/`status` line for the READ,
  sticky poison and failure rather than a successful shutdown;
- real IRQ wake from idle, run/sleep/wait and existing editor semantics;
- mutation checks rejecting lies in captured successful content, EOF,
  listing name/size, returned write and rm count/status, cross-boot content
  and raw-image expectations;
- launcher one-time install, host-lock exclusion, alternate-disk persistence,
  explicit reset, and refusal to overwrite an existing malformed image.

Key evidence under `build/lesson10/`:

| Artifact | What to inspect |
| --- | --- |
| `cold-boot1.log` … `cold-boot3.log` | real shell writes and exact cold named reads |
| `api-patterns.log`, `cold-api-verify.log` | real syscall boundary patterns and reboot checks |
| `raw-decoder.json` | independent file slots/LBAs/logical sizes/payload hashes |
| `evidence-shell.img`, `evidence-patterns.img` | disposable snapshots for separate raw inspection |
| `negative-*.log`, `io-error-*.log` | explicit rejection/device errors, no timeout-success |
| `oracle-mutations.log`, `test-result.json` | oracle checks and protected base hashes |
| `launcher*.log` | actual launcher/lock/persistence checks |
| `gdb-flush.log`, `gdb-uart.log` | actual type4 header→status chain, used id/length/status, detach/echo/shutdown |

```sh
python3 lessons/10/decode.py build/lesson10/evidence-patterns.img
```

`make test-lesson10-gdb` runs real-child logging regressions (success,
nonzero, timeout, early guest assertion and launch failure). Its first recipe
command truncates `build/lesson10/gdb-flush.log` through
`lessons/10/fresh-log.py` — before the lesson itself is built, before the
runner regression step, and before any launch or guest wait — and `gdb-test.py`
repeats that truncation idempotently for direct invocations. A failure in any
of those steps therefore never leaves a previous run's PASS behind; e.g. a
deliberately broken source file, or
`TMPDIR=/nonexistent/definitely-not-here make test-lesson10-gdb`, fails in the
runner regression and the log is empty, containing no PASS. The runner
regressions also assert that the helper clears a file containing a fake PASS
and reports a truncation error. Failures retain partial combined stdout/stderr,
append a failure diagnostic, kill/drain/reap any debugger, and still fail the
gate.

The optional GDB gate stops at `block_completion_observed` after validation,
asserts type4, a 16-byte header→one-byte status with no data descriptor,
used id0/length1/status0, detaches, then executes an IRQ-driven echo and clean
shutdown. It does **not** break a shared `sret` epilogue or step another hart
through an unlocked restore window. This is functional evidence on QEMU,
not board/RTL signoff or a physical power-loss test.

Protocol reference: OASIS Virtio 1.2, block device §5.2 (feature bit9 FLUSH,
bit32 VERSION_1, request type4), and QEMU 10.2.1 virtio-blk implementation.
Requiring explicit FLUSH is this driver's deliberate policy; a compliant
writethrough device without that optional feature can still persist data.
Stock QEMU has `write-cache=on/off/auto`, **not** a `flush=` property.
