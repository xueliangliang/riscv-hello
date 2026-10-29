# Lesson 12 — Bounded full-data redo journal

This lesson keeps lesson11's B+ tree, chained file payloads and real disk-loaded,
dual-hart U-mode shell. It adds a redo journal around **one mutating filesystem
API call**, including data, chain links, nodes, bitmaps and the superblock.
It is not a new executable loader, compiler, directory hierarchy or production
filesystem. Lessons01–11 are preserved.

## Build, run and verify

From the repository root, with the preceding lessons' RV64 cross-toolchain,
QEMU with Sstc and modern virtio-mmio, Python 3 and a native C compiler:

```sh
make lesson12
make run-lesson12
make test-lesson12
make inspect-lesson12
make test-lesson12-gdb       # additionally needs gdb-multiarch
python3 lessons/12/gate-evidence-test.py  # after a passing lesson12 gate
make all test inspect       # cumulative lessons01–12
```

The native model uses `HOSTCC` (default `cc`); target code uses `CC`, and the
runners accept `QEMU` and `GDB`. Tests use disposable copies, not saved disks.
Try `fwrite note durable`, `cat note`, `fsinfo`, then `shutdown`; restart and
read `note` again. Use `help` for file, process and serial-editor commands.
`run`/`kill`/`wait` still exercise real U processes, not host-side substitutes.

### Persistent state is not a build fixture

`build/lesson12/disk.img` is the reproducible fresh fixture. The first
`make run-lesson12` copies it once to ignored `state/lesson12/disk.img`.
Later runs reuse that disk; rebuilding or `make clean` does not replace it.
The launcher holds an exclusive nonblocking host lock for installation and the
whole QEMU run. Installation uses a flushed sibling temporary file, atomic
rename and directory fsync. An existing disk is never silently upgraded.

**`make reset-lesson12` destroys saved lesson12 files**, installs the current
fixture, then exits. For a disposable explicit path use
`make run-lesson12 LESSON12_ARGS='--disk path/to/disposable.img'`.
Do not pass a valuable image to tests or reset. BPTFS11 has a different identity
and is rejected without writes; this lesson does not migrate it.

## Format and commit protocol

[FORMAT.md](FORMAT.md) is the exact little-endian format and failure contract.
The 8 MiB device has 16384 atomic 512-byte sectors:

| LBA range | Purpose |
| --- | --- |
| 0–256 | Existing boot record, kernel and U-image slots; never journal targets |
| 512–1026 | Superblock, two bitmaps, 512 B+ tree node pages |
| 2048–10239 | 1024 chained 4096-byte data blocks; 4092 payload bytes per block |
| 12288 | Commit header, or all zero for clean |
| 12289–12304 | 1024 descriptors: target LBA and image CRC |
| 12305–13328 | Up to 1024 full-sector after-images |

Other sectors are reserved. The new `BPTFS12` superblock includes a CRC at
byte508. CRC-32/ISO-HDLC protects each image, the full descriptor area and the
commit header. CRC is accidental-corruption detection, not authentication.

`journal_io` stages unique target sectors, overwrites duplicate entries and
returns staged bytes to reads. No home WRITE occurs during staging. Commit is:

1. WRITE images and descriptors, then FLUSH.
2. WRITE the commit header, then FLUSH.
3. WRITE all home after-images, then FLUSH.
4. WRITE a zero header, then FLUSH; only then may the log be reused.

On mount, identity/geometry/superblock CRC are checked first, without requiring
a consistent home tree. Recovery validates the **entire** header, descriptors,
unique whitelisted targets and all image CRCs before any home write. It redoes
all images, flushes, clears and flushes the header, then validates the full home
filesystem. This ordering permits replay of a partially checkpointed tree.
Replay can itself be interrupted and repeated. A clean second boot writes
nothing. Empty transactions issue no device requests.

## Atomicity, capacity and errors

- The unit is one successful mutator API, not a whole shell command.
  `FS_REPLACE` open and subsequent writes are independent commits; a crash
  between them may leave a valid empty file. A multi-chunk command is not one
  transaction.
- Capacity is **1024 unique sectors**, not 1024 calls. Oversize operations return
  `F_LIMIT=-17`, restore cached tree/root/files/epoch/bitmaps and handle/cursor
  state, leave the entire disk unchanged and keep the filesystem usable.
  Large defrag is rejected, not silently split into weaker transactions.
  Small defrag really moves blocks and preserves file contents.
  Aborting a capacity rejection clears its transaction-local error, so an
  immediate sync/shutdown still issues a real FLUSH without another open.
- Device I/O failure returns `F_IO=-14` and poisons the mounted filesystem until
  recovery. A failed WRITE or FLUSH may already have persisted. In particular,
  once commit-header WRITE has been attempted, an error does **not** promise
  rollback to PRE. Reboot/remount resolves durable PRE or POST.
  Same-runtime `fs_mount()` resets and reinitializes the real driver before
  replay. Static DMA storage remains quarantined until reset acknowledgement;
  requests resume only after complete queue/feature/geometry validation.
  Missing device, reset timeout or failed reinitialization retains quarantine.
- File limits remain 512 files, 64 KiB per file and four generation-checked
  handles, with one open per file. File ecalls remain shell-owned; ownership is
  checked before user pointers. Whole buffers must fit one allowed region;
  reserved syscall arguments must be zero and paged listing output/cursor
  must not overlap. Zero-length write/append retain normal validation but do
  not move offsets or exhaust an already-maximum persistent epoch.
- Deletion is lazy; there is no full B+ deletion rebalancing. The implementation
  caches the complete bounded metadata and snapshots it in static BSS. These
  choices favor inspectable teaching code, not throughput or scale.

The linker enforces kernel BSS below shell base `0x80400000`, and U code/data/BSS
below `0x80407000`. Per-instance data and eight independent stacks occupy their
separate fixed ranges through `0x80410000`. Boot slots admit at most 64 KiB each. Journal buffers and
snapshots are static storage, not an expanded heap. Inspect ELF symbols and raw
binary sizes after changing the layout.

## Evidence and its boundaries

`make test-lesson12` invalidates all lesson12 JSON/log evidence **before** any
recursive build. It then runs:

- `model-test.py`: the actual `fs.c` + `journal.c`, compiled natively against a
  separate volatile/durable sector backend, not a Python filesystem mirror.
  Eight mutators cover split/create, overwrite, append, shrink, delete, real
  defrag, replace-open and growth. The matrix has 176 crash/error outcomes,
  plus eight recovery-error outcomes, interrupted replay and second-boot
  idempotence. Reported I/O errors exercise both persisted/nonpersisted fates.
- The independent raw decoder checks the entire tree, leaf chain, allocation
  bitmaps, chains, contents, zero tails and boot bytes. Thirteen malformed logs
  include CRC-correct duplicate/invalid targets and count errors; all must
  reject before any WRITE or FLUSH. Direct journal tests stage 1024 distinct
  sectors, overwrite one repeatedly, read it back and reject the 1025th.
  Empty-transaction no-I/O and large-defrag rollback are real assertions.
- The FFI declares argument and return types explicitly. Native trace counts
  replace sentinel scans; trace overflow is sticky and fails every checked
  call and evidence read. Tests retain a late WRITE beyond the former 32768
  limit and deliberately saturate the bounded trace to prove rejection.
- `protocol-mutation-test.py` runs isolated broken copies: missing commit
  FLUSH, suppressed native trace-overflow reporting and a signed trace FFI
  return must each fail for the expected reason. Three additional mutations
  reject ungated initialization, early poison release and pre-reset ring reuse.
- `recovery-test.py` checks immediate native type4 sync after oversized defrag
  and direct journal abort, RAM enumeration/cursor/epoch rollback and exact
  whole-image nonmutation. The real dual-hart U shell rejects defrag at capacity
  and immediately shuts down successfully without an intervening FS open.
  Two real MMIO/QEMU once-only WRITE IOERR probes cover pre-commit log payload
  and post-commit checkpoint errors: poison remains sticky before reset, then
  same-runtime remount yields exact PRE/POST respectively, permits a new
  mutation and survives a read-only cold boot without changing any disk bytes.
- `block-reset-test.py` compiles the actual driver control flow with only
  native time/fence/MMIO substitutions. Canary DMA objects must not change
  before reset ACK; missing device, reset timeout, missing FLUSH, queue setup
  and capacity failures must retain poison. Only a fully initialized new
  queue may submit a FLUSH. These are transport-shim fault tests, not claims
  that stock QEMU simulates delayed reset ACK or real outstanding hardware DMA.
- `test.py` and `epoch-test.py` exercise real U ecalls, B+ splits, full capacity,
  defrag, cold boots, pointer/ownership checks, maximum epoch and actual device
  READ/WRITE/FLUSH IOERR with sticky poison. A dirty operation precedes FLUSH
  fault injection because a clean backend may elide FLUSH.
- `crash-test.py` exercises 64 actual RISC-V software interruption boundaries,
  malformed recovery, interrupted replay, then the real dual-hart disk-loaded
  U shell repairing a partially checkpointed filesystem and reading exact
  binary bytes. Runtime gates also exercise IRQ editing and run/kill/wait.
- The GDB gate observes the full image/descriptor → FLUSH → commit → FLUSH →
  checkpoint → FLUSH → clear → FLUSH sequence, including real type4 header16
  to writable status1 descriptors and completion. After detach, a live IRQ
  echo and shutdown must work. Runner regressions retain partial binary logs,
  kill/drain/reap failed children and reject timeouts and early guest failures.

Evidence is under `build/lesson12/`: `results.json`, `model-results.json`,
`crash-results.json`, `recovery-all-results.json`, `protocol-mutation.json`,
`block-reset-test.log`, per-stage/per-guest logs and
`gdb-flush.log`. A PASS from an earlier invocation is not current evidence.
`gate-evidence-test.py` copies actual successful JSON/log evidence into isolated
source trees, then runs bad-compiler and early-setup failures through the real
outer gate; neither may retain any stale PASS. It also checks that `make clean`
preserves a saved disk in that disposable tree, never cleaning the working tree.

Assumptions: sector writes are atomic and successful FLUSH is honest and ordered.
QEMU finisher exit is **software interruption**, not device power loss; host
cache behavior may preserve unflushed writes. The native backend separately
models their loss. Neither test proves sector-tearing tolerance, dishonest
firmware behavior, physical board timing or real power-cut safety. The system
still has flat physical access, not address-space isolation. There is no new
ELF/DLL loader, guest compiler or future-lesson runtime in this lesson.
