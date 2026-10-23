# FlatFS10 disk format and user ABI

This specification is independent of native C structure layouts. It is **not**
compatible with the earlier prototype's LBA80 filesystem. All integers below
are unsigned, fixed-width, **little endian**. A sector is 512 bytes.

## Physical layout

| Region | Inclusive LBAs | Bytes / purpose |
| --- | --- | --- |
| Reserved boot area | 0–256 | boot record, at most 128 kernel + 128 user sectors |
| Unused gap | 257–511 | must not be allocated by FlatFS10 |
| Metadata | 512–514 | one header sector + sixteen 64-byte directory records |
| Unused gap | 515–1023 | not allocated |
| File extents | 1024–1151 | sixteen fixed 4096-byte extents |
| Unused disk tail | 1152–4095 | not allocated |

The fixture is exactly 4096 sectors / 2 MiB. The driver accepts a device with
at least this capacity; all filesystem offsets remain in the defined range.
`format.py` deliberately creates a fresh fixture by invoking the unmodified
lesson03 boot packer, asserting its maximum end before extending to 2 MiB.
Compile-time assertions in `fs.c` separately check the regions do not overlap.
The kernel **never formats** an unrecognized or malformed disk.

### Header sector at LBA512

| Byte offset | Width | Value |
| --- | --- | --- |
| 0 | 8 | ASCII `FLATFS10` |
| 8 | 4 | version = 1 |
| 12 | 4 | directory slots = 16 |
| 16 | 4 | directory record size = 64 |
| 20 | 4 | extent bytes = 4096 |
| 24 | 4 | data start LBA = 1024 |
| 28 | 4 | disk sector budget = 4096 |
| 32–511 | 480 | zero; reserved |

### Directory record i, at LBA513 + byte offset i × 64

| Byte offset | Width | Meaning |
| --- | --- | --- |
| 0 | 32 | NUL-terminated ASCII name, all bytes after NUL zero |
| 32 | 4 | used: exactly 0 or 1 |
| 36 | 4 | logical size: 0–4096 |
| 40 | 4 | absolute extent start LBA: **exactly 1024 + i × 8** |
| 44–63 | 20 | zero; reserved |

A used name has 1–31 characters, from `[A-Za-z0-9_.-]`, and is unique across
all live records. This is a flat namespace: `.` is an ordinary name, not a
path component. An unused record is **64 zero bytes**, including size/offset.
Mount validates the complete header and **every** record before admitting any
mutation: used flag, NUL/padding, name alphabet, size, exact per-slot extent,
reserved bytes, zero unused records, and duplicate names. There are no host
pointers, checksums, allocation chains, timestamps or native C padding on disk.

The payload begins at `extent_lba × 512`. Only `size` bytes belong to a logical
file. A successful write replaces the entire payload, writes zero padding to
the end of that extent, and truncates the logical size to the new byte count.
Delete clears the entire record; it **does not securely erase** old payload.
Reusing a slot reuses its fixed extent; no bump allocator or fragmentation
accounting is needed.

## File syscall ABI (U ecall → checked S dispatcher)

`a7` = syscall number, `a0/a1/a2` = arguments, signed `a0` = result. See
`fs.h` for protocol constants and `syscall.h` for user `file_open/read/write/flush/close/remove` wrappers (implemented with `syscall2/3` in `syscall.c`). Console WRITE remains syscall **1**, max
256 bytes: it is not file WRITE.

All file operations are deliberately **shell-only** (`current == 0`, PID16).
Workers receive `E_OWNER = -2` before file pointers are dereferenced; there is
no handle inheritance or worker cleanup policy in this lesson. At most four
live handles; token = `generation × 4 + slot`. Tokens are positive signed
values, generations never wrap (admission fails before exhaustion), stale
handles are rejected after close/reuse. Only one open handle per file is
allowed; opening/replacing or deleting an open file returns busy.

| Number | Operation | Arguments | Success |
| --- | --- | --- | --- |
| 17 | open | name pointer, mode | generation-safe handle ≥4 |
| 18 | read | handle, writable buffer pointer, count | actual bytes, **0 at EOF** |
| 19 | write | handle, readable buffer pointer, count | replacement byte count |
| 20 | flush | handle | 0 after real device FLUSH completion |
| 21 | close | handle | 0 after real FLUSH; invalidates token even on I/O failure |
| 22 | remove | name pointer, 0 | 0 after metadata write + FLUSH |
| 23 | list | 0, 0 | 0, listing on console; I/O error if poisoned |
| 24 | info | 0, 0 | 0, diagnostic completed-request counts and health |

Open mode **0** reads an existing file only, never creates; **1** explicitly
creates or replaces (immediately truncating to empty), grants writes, and
persists the empty metadata before returning. Other modes fail. Each write
replaces the entire file, irrespective of the read cursor, then resets that
cursor to zero; **there is no seek or append**. Reads advance the handle cursor
and copy exactly `min(count, size-cursor)` bytes, without touching the rest of
the user buffer. Zero-length reads/writes work with an admitted buffer pointer.

Names are copied byte-by-byte into a 32-byte kernel buffer after range checks;
an unterminated 32-byte name fails. I/O counts are at most 4096. Subtraction-
based range checks admit the shared user image/data, the caller's own 256-byte
data block, or its own 4096-byte stack; ranges crossing a boundary, null/kernel
pointers, address wrap and counts above 4096 fail **before mutation**. As in
lesson09 these are ABI checks, **not memory protection**: there are no page
tables, and PMP allows flat physical access.

Errors: `-4` argument/name/pointer/count/mode, `-10` missing, `-11` directory
or handle capacity, `-12` bad/stale handle, `-13` file busy, `-14` I/O/poisoned,
`-15` non-writable handle, `-16` generation exhausted. Errors are returned,
not converted into successful byte counts. Replacement's open and write are
separate operations: an invalid/failed write does **not** undo a preceding
successful truncating open.

## Device ownership, completion and durability

The bootloader and kernel use the **same modern virtio-mmio block device**.
After the loader completes, the kernel resets status to zero and waits for
acknowledgement with a bounded `rdtime` deadline, then independently negotiates
VERSION_1 (feature bit32) and FLUSH (bit9), rejects read-only (bit5), installs
its own static queue/DMA storage, and sets FEATURES_OK / DRIVER_OK. None of the
bootloader's queue addresses is reused. This driver intentionally supports
only explicitly negotiated FLUSH: a device without FLUSH can still offer
writethrough durability under the specification, but that is **outside this
lesson's chosen policy**, not a claim that such devices cannot persist.

One serialized request is in flight. READ is type0, WRITE type1, with a
16-byte header → 512-byte data → one-byte writable status chain. FLUSH type4
is **header descriptor0 → status descriptor2, with NO data descriptor**.
Descriptor1 is unreachable for FLUSH. The available/used indices wrap as
uint16_t and select ring entries modulo8; only a single next completion,
head id0, expected used length (513 for READ, 1 for WRITE/FLUSH), status0,
stable config generation, queue-ready and healthy device status are accepted.
CPU `fence` instructions order publication/DMA visibility; **they are not a
durability barrier**. Successful `block_reads/writes/flushes` are counted only
after validated device completion.

Requests poll for at most 10,000,000 `rdtime` ticks (one second on this QEMU
virt 10 MHz timebase). A file call can issue multiple requests (for example,
write uses eight data, three metadata, one flush), so this bounds each device
wait rather than promising subsecond total syscall latency. File syscalls
hold the existing global scheduler lock with SIE clear. Thus timer handling,
other-hart scheduling and UART RX are delayed during I/O; hardware FIFO/RX
capacity can overrun under input floods. There is **no wait for human input**
under that lock. The existing atomic IRQ-reader wait still releases the lock
before user idle.

All descriptors, request header, status and the DMA bounce buffer have static
lifetime. On timeout, bad status/id/length/index, device reset-needed, or
configuration change, the driver sets FAILED and the filesystem is poisoned.
It does not recycle outstanding storage or pretend the timed-out DMA stopped.
A fresh boot resets the device before queue reuse. No caller's stack/user
buffer is ever left as a DMA target.

Normal successful write: **data sectors → metadata sectors → negotiated
FLUSH completion**. Open-replace/remove also flush changed metadata;
flush/close/shutdown always submit a real FLUSH even without cached changes.
This establishes the API's successful normal-boot/close/poweroff persistence
contract with a conforming backend. It provides **no power-loss atomicity,
rollback, journal, sector-tearing protection or corruption detection checksum**.
A failed request may already have changed the medium; errors poison the mount
rather than claiming rollback. Shutdown after a failed flush prints failure
and exits QEMU with failure, never the successful shutdown banner.

The test `NO_FLUSH` build explicitly filters feature bit9 in the driver:
**negative injection**, not a stock QEMU device property. Actual readonly
backend and QEMU blkdebug read/write/flush EIO are separate negative tests.
