# Lesson 15 loading contracts (version 1)

This is neither ELF loading nor PE/Windows DLL compatibility. All integers in
these two file containers are unsigned little-endian, decoded byte by byte.
The ELF files are host inspection/link intermediates only.

## RVEXEC1 ordinary file

48-byte header: magic `RVEXEC1\0` (8 bytes), then ten u32 fields at offsets
8 version=1, 12 exact file bytes, 16 payload bytes, 20 entry offset relative
to payload, 24 load address=0x80500000, 28 memory bytes (payload+BSS),
32 ABI=1 or 2, 36 code bytes, 40 reserved=0, 44 reserved=0.
Payload immediately follows. File bytes must equal 48+payload, with no trailing
bytes, and the whole file must fit 65536 bytes. Code bytes are even and at least 2;
code <= payload <= memory; memory <=65536 for ABI1, <=1048576 for ABI2.
File bytes remain <=65536 in BOTH ABIs. Payload and memory are multiples of 16;
entry is even, with at least one complete 2-byte instruction inside code.
ABI1's executable entry is a startup stub calling `int app_main(void)` with an
inherited process-owned 4096-byte stack. ABI2 enters with a0=argc/a1=argv and
the private 65536-byte stack. See CONTRACT.md for ownership, copying and bounds.
Compiler entry calls cc_main(argc,argv); generated entry is native emitted code,
not a call into the compiler. EXIT status is bounded 0..255.
All bytes from payload end to memory end are zeroed on each exec.
The entire input is staged and validated before copying or publishing READY.
One file application owns the fixed region until WAIT reaps it, including ZOMBIE.
Generation-bearing inherited PIDs and compiled workers remain independent.

## RVDLL01 PIC module

32-byte header: magic `RVDLL01\0`, u32 version=1 at 8, exact image bytes at 12,
exports offset at 16, export count at 20, code offset at 24, ABI version=1 at 28.
Even file/image size <=4096, exports 1..8. Table offset >=32, multiple of 8;
whole 24-byte-per-export table ends <= code offset; code offset is even and
strictly below exact image bytes. No trailing data is permitted outside the
reported image. Export: 16-byte name, u32 image-relative function offset,
u32 signature ID (1 unary `double(double)`, 2 binary `double(double,double)`).
Names are nonempty printable ASCII without spaces, terminated within 16 bytes,
remaining name bytes zero. Duplicate names are rejected. Every function is even
(C extension) and lies in [code offset,image bytes). All exports are validated
before any image becomes active. Names/signatures do not confer trust in code.

Only pure self-contained position-independent text is supported: no module
BSS/data, GOT, TLS, imports or unresolved/dynamic relocations. The packer rejects
such ELF intermediates; the container has no relocation/BSS/import fields.
A malicious producer could hide instructions that violate this contract; this is
not a verifier/sandbox. Unknown versions/ABI are rejected, not relocated.

## Runtime and math ABI

RV64IMAC + Zicsr + Zifencei, **lp64 integer calling convention**. Double bit
patterns travel in a0/a1; no F/D instructions or floating register context.
`ceil`/`floor` preserve signed zero, infinities and all NaN bits. For finite
values they round mathematically toward +infinity/-infinity. `max`/`min` return
the non-NaN operand if one is NaN, the second if both are NaN. At zero ties max
returns +0 and min -0. No ISO libm/fenv/exception/NaN-quieting claims.

READFILE(31,name,buffer,capacity) is an exact existing-only read-only snapshot
for the designated file application. EXEC(30,name,argc,argv) is shell-only,
with zero/zero preserving legacy ABI1 behavior. Old file
handles stay shell-only. Caller ownership is checked before pointer access;
filename including NUL must be a contiguous admitted prefix, at most 31 bytes.
Capacity 1..65536, full destination interval admitted, no partial copy on error.
Kernel closes its private FS handle even after I/O/capacity failure. Filesystem
and scheduler serialization make the snapshot stable. STORE32 is a new bounded
whole-file publication API for the designated application, not arbitrary handles.
APPEND33 is shell-only; both use one outer transaction. See CONTRACT.md.

The U loader has one active module and two alternating aligned 4096-byte BSS
banks, plus staging. A second load while active rejects without changing it.
Handles are integer generations (zero invalid); at ULONG_MAX further activation
is refused, never wrapped. Unload invalidates lookup, clears bank bytes, fences
locally. Raw resolved pointers cannot be revoked: never call after unload.

Tasks remain pinned. The receiving hart executes its own fence.i on initial
application scheduling after copy; a loader-hart fence alone is insufficient.
The pinned U loader executes a local fence.i after copying module bytes. QEMU
functional success is not a hardware instruction-cache-coherence experiment.
Flat PMP permits U access to RAM: admission checks are not process isolation.
Boot still uses lesson03's disk loader for kernel and shell. BPTFS12 geometry,
1024-sector redo journal and four-FLUSH ordering are unchanged; no autoformat,
migration or boot reseed. Only newly generated lesson15 fixtures are seeded.

## Integer runtime prefix (not the DLL ABI)

Generated ABI2 payload begins with the trusted integer-runtime prefix embedded
in cc. `integer-runtime.S` is assembled/linked without relocations or unresolved
symbols. Its 32-byte header is `RVINT14\0`, u32 version 1, exact prefix length,
print_int offset, and three zero reserved fields. The producer validates these
and emits a C constant; cc validates version/length/entry/magic before use.
The generated entry starts after that exact prefix. Native `jal` calls the
integer helper, which accepts signed 64-bit in a0, prints its full decimal value plus
LF using SYS_WRITE, returns zero and preserves callee-saved registers. No source
interpretation, F/D instruction, import table or compiler-process dependency.
String data begins at payload offset 32768; payload includes zero padding and
is aligned to 16. Code bytes end at the actual emitted instruction boundary,
not at the string-data base. Native branches use fixed 32-bit RV64 encodings;
long conditional control flow uses an inverted short skip plus patched JAL.
