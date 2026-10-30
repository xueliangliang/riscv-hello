# Lesson14 additional execution/persistence contract

Retain lesson13 RVEXEC1 48-byte little-endian header and ABI1 admission unchanged.
Header offset 32 selects ABI: 1 legacy; 2 argument-enabled. ABI2 memory may extend
to 0x80600000 (1 MiB); file bytes still at most 65536. Unknown ABI and reserved
fields are rejected. Header version at offset 8 remains 1. Code/payload/entry
checks otherwise remain unchanged. Executable formats are custom, not ELF.

EXEC(30, name, argc, argv) remains shell-only. Zero/zero preserves old calls.
Otherwise argc is 1..4, argv is a contiguous, aligned array of argc+1 RV64
pointers terminated by NULL. Each argument is a nonempty, contiguous NUL-terminated
prefix at most 48 bytes including NUL; the vector and every complete string must
belong to the caller's admitted region. All strings are copied before app memory
is overwritten. ABI1 rejects nonzero argc. ABI2 enters with a0=argc, a1=argv,
argv points into that process's 256-byte data slot; strings follow the 40-byte
vector. Those bytes belong to the process until reap. The copied vector and strings occupy
the leading bytes of that 256-byte per-slot region, so they replace the worker
`counter`/`canary` values there; no ABI2 code depends on those fields, and ABI1
calls keep the original values. No EXEC until previous
file application is reaped, even after exit/kill. No recursive compiler EXEC.

ABI2 uses the exclusive 64 KiB stack [0x80410000,0x80420000); ABI1/workers keep
individual 4 KiB stacks [0x80408000,0x80410000). Shell raw workspace is NOLOAD
[0x80420000,0x80424000), explicitly cleared before launch. Only shell pointers
are admitted there. App BSS and selected stack are cleared before READY; actual
memory bound is checked by linker. Scheduler release/acquire publishes payload,
then the receiving hart executes local fence.i. This is QEMU architectural
verification, not physical cache coherency proof. No runtime memory isolation.

STORE(32,name,bytes,count) admits only designated file application, protects
cc/math_test/math.dll, validates entire intervals, count <=65536. APPEND(33,...)
is shell-only and uses the same atomic whole-operation filesystem transaction.
All chunks use internal mutators under one transaction, never nested wrappers.
Deterministic errors leave whole disk and RAM unchanged; real I/O errors poison
filesystem and may have committed, requiring recovery. BPTFS12 format, 1024-sector
redo and four FLUSH protocol unchanged.

Raw input: `fappend NAME <<DELIMITER` with 1..31 printable nonspace bytes.
Body <=8192 bytes excluding standalone terminator line; CR/LF/CRLF become LF
using shared normalization across editor/raw mode. Tabs, quotes, backslashes and
UTF-8 bytes preserved. Empty is no-op/no create. Invalid controls (including ESC,
Ctrl-C/D), overflow and any observed RX losses reject without opening file and
drain until exact delimiter; even cancellation REQUIRES delimiter for resync.
Delimiter lookahead is separate from the body bound. RX ring is 16384 bytes,
not flow control; supported burst must include command and delimiter framing.
Loss baseline is boot's zero counter, predating even already-queued commands;
any RX loss disables raw publication until reboot. Drain/editor recovery still
works, but a later paste cannot silently acknowledge hidden earlier losses.
