# Frozen runtime15 contract

RV64IMAC_Zicsr_Zifencei, lp64: binary64 arguments/results occupy integer a0/a1,
never floating registers. Host-built guest compiler, not self-hosting or ISO C.

RVEXEC1 version1 keeps its 48-byte header and zero reserved words. ABI1 and ABI2
retain their lesson14 semantics. ABI3 alone requires the runtime15 prefix, ABI2
argument copying and private 64KiB stack; executable/staging/READFILE <=65536
remain distinct from the 1MiB application memory interval 80500000..80600000.

Payload: 20KiB runtime prefix, 32KiB generated native code region, 8KiB strings.
Runtime metadata is 64 bytes: magic RVRT15\0\0; fourteen little-endian u32 words:
version=1, exact prefix bytes=20480, API count, table offset=64, function begin,
function end, BSS begin offset=65536, BSS end offset, generated code base=20480,
string base=53248, API version=1, three reserved zero words. Table entries are
u32 target offset + u32 signature. Exact ordered API/signature definitions live
in runtime-api.h; function targets must be aligned and inside function region,
not metadata, table, rodata or padding. Runtime BSS starts at 80510000 and ends
below80600000. The linked map, packer, compiler, kernel and runtime check these
bounds. ABI3 entry must be in generated code, not inside runtime or strings.
The kernel validates before any shared app copy or child publication. Runtime
validates at entry and helper dispatch. Existing files are never healed/reseeded.

Math calls resolve actual RVDLL01 ABI1 typed exports, lazily, via READFILE and
checked module banks. Cached symbols are used only with a live module handle.
Compiler exit/reap precedes separate generated EXEC; process reservation lasts
through ZOMBIE. Release/acquire publication and receiver-local fence.i remain.

IEEE binary64 helpers: default nearest/ties-even, no dynamic fenv guarantee.
Double to int is truncation toward zero only for finite [-2^63,2^63); other
values diagnose and exit nonzero before conversion. Floating truth: both zeros
false, every other bit pattern including NaN true. Comparisons follow unordered
semantics. No libc, mismatched libgcc or F/D ISA extension is permitted.

This is a frozen design contract, NOT a claim that acceptance gates passed.
