# Lesson14 verification receipt

This is implementer evidence, **not** the parent's independent SPEC / QUALITY
review or archive reproduction, and not authorization to tag or publish.

## Executed public gates

| Gate | Actual exit |
|---|---:|
| `make all test inspect` (after a real `make clean`) | 0 |
| `make test-lesson07-gdb ... test-lesson14-gdb` (every lesson 07–14) | 0 |
| `make test-lesson14-evidence` | 0 |
| Public `run-lesson14 LESSON14_ARGS='--disk ...'`, competing run/reset and selected reset | 0 / expected lock rejection |
| Cold guest read of saved file after clean, full rebuild and relaunch | 0 |

The initial expanded shell exceeded its old low-BSS boundary; shell-only BSS
and raw buffers now occupy their explicitly cleared NOLOAD workspace. Testing
also exposed asynchronous prompt/output interleaving and an inspect prerequisite
being passed to readelf. The final checks distinguish editor redraws from actual
prompts, puts includes LF in its bounded output chunk, and inspect filters ELF
prerequisites. The receipt does not treat those failed attempts as passes.

The final lesson14 runtime gate exercises 14 independently expected native
programs, including negative full-width division, wraparound, branches/loops,
shadowing, string escapes/UTF-8, source capacity and a 6180-byte-code example.
It separately exercises 50 syntax/type/resource failure compilations preserving
full old output / absence, plus usage, missing/oversized read, same-source/output
and protected-output errors. The focused frontend gate adds 80 invalid actual
U-mode compiler invocations (40 sources, existing and missing output each),
15 independently expected valid recovery runs and 35 captured-evidence oracle
mutations. It checks exact line/type/token diagnostics, no success banner,
full old executable/source bytes and missing-output absence; valid recovery
covers lvalue categories, separated unary signs, assignments, scope, repeated
zero initialization and full-width arithmetic. Both read-first cold source/output bytes and saved
native execution are checked with no recompilation or reseeding.

Actual C storage checks cover 44 crash/error outcomes across replacement and
append, binary shorter/longer/empty/create paths, full/epoch/busy rollback and
immediate sync. A separate reduced-capacity native journal build verifies the
otherwise defensive J_LIMIT path without changing production geometry. Actual
QEMU READ/WRITE/FLUSH IOERR status1 tests verify compiler exit/reap, sticky poison
and cold recovery. Three genuine broken compilers (subtraction, branch, store)
are cross-built and run in U mode; the full-result oracle rejects their outputs.

GDB verifies compiler AND newly emitted native U entries, complete persisted
payload bytes, safe argv, actual instructions and receiving `fence.i` on harts
1 and 0. Captured hart/privilege/entry/size mutations fail its oracle. This is
architectural QEMU evidence, not physical cache or real power-cut certification.

## Measured resources

| Artifact | File bytes |
|---|---:|
| kernel | 28676 |
| shell | 22584 |
| compiler RVEXEC1 file | 12736 |
| embedded integer helper prefix | 144 |
| inherited ABI1 math_test | 5120 |
| inherited math.dll | 486 |
| generated loop executable | 32816 |
| generated loop instruction extent (including prefix) | 744 |

Compiler linked memory: 237072 bytes. Its BSS is
`[0x80503190,0x80539e10)`, below the ABI2 memory cap `0x80600000`.
Kernel BSS is `[0x80207010,0x8032cad0)`, below shell `0x80400000`.
Shell low BSS is empty at `0x80406000`; shell-only workspace actually ends at
`0x80423400`, below its `0x80424000` limit. Original user data occupies
`[0x80407000,0x80407800)`, eight old stacks occupy
`[0x80408000,0x80410000)`, ABI2 private stack is
`[0x80410000,0x80420000)`.

The compiled per-function stack-usage maximum is 112 bytes. A deliberately
pessimistic static sum across parser, statement and code-generation depth caps
plus 4096 bytes of margin is 32768 bytes; this is a conservative static bound,
not a claimed measured dynamic high-water mark. Generated locals/evaluation/
integer helper use a bounded 4144 bytes. No heap is enlarged.

`resource-results.json` additionally records boot BSS/stack, both M and S trusted
stacks, both U idle stacks, every per-slot stack, file-staging/RX ranges,
legacy module BSS/banks and the complete compiler frame table.

## Reproducible evidence paths

All ordinary artifacts are ignored, regenerated files under `build/lesson14/`:

- `results.json`, `runtime-results.json`, `resource-results.json`
- `store-results.json`, `mutation-results.json`, `evidence-results.json`
- `compiler-uart.log`, `compiler-cold.log`, `compiler-verified.img`
- `frontend-all-results.json`, `frontend-all-uart.log`, `gate-frontend.log`
- `gdb-loader.log`, `gdb-uart.log`
- `io-compiler-*.log`, `raw-loss.log`, `launcher-*.log`, `mutant-*.log`

Evidence attack logs survive outer gate invalidation in
`$TMPDIR/lesson14-evidence/`. Failure/timeout stdout and stderr are retained;
actual children are killed/drained/reaped. Wrong CC, early debugger setup and
fake `/bin/true` GDB are rejected, followed by restored real runtime/GDB gates.

Earlier lessons01–13 and tools are byte-unchanged. The original Makefile,
README and ignore-file bytes remain exact prefixes. All seven separately
protected prototype/filesystem/disk hashes were checked unchanged. No original
source disk, old tag, remote, blog or cloud publication was modified.

## Stage1 SPEC correction evidence

The correction adds an explicit unary-positive value node (parentheses alone
retain local lvalues), maximal-munch rejection of unsupported C punctuators,
and an explicit self-initializer prohibition on the newly scoped binding.
No increment/decrement implementation is added. `int x;` still stores zero
on each declaration execution, and ordinary shadowing remains valid.

`python3 lessons/14/frontend-fail-first.py` builds the exact unchanged
`dba51e699c49278a4fd00d4fb985dff84ac51c76` archive, copies the identical regression
file, and runs all four defect classes independently. The old actual guest
compiler accepts forbidden lvalue/increment/decrement/self-initializer programs,
overwrites full existing executables and creates previously absent outputs.
Each class returns a failing regression exit, then still executes its three
valid recovery programs. Diagnostic-text differences alone are not accepted as
fail-first proof. The printed scratch archive retains old build, complete UART
transcripts, per-class JSON/statuses and `fail-first-results.json`, including
the exact old compiler and regression hashes. This is implementer regression
evidence, not independent SPEC or QUALITY approval.
