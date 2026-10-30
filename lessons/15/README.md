# 15 — guest compiler, software binary64 and runtime-linked math

The real closure is raw UART source → ordinary guest file → separate U-mode
`cc` lexer/typed AST/native RV64 emitter → atomic saved executable → compiler
exit/WAIT/reap → independent EXEC → actual PIC `math.dll` resolution/call →
new QEMU cold read of WHOLE source/executable before any writes → execution
without cc. This is host-built/guest-running, not self-hosting or ISO C.

## Reader commands

Dependencies: cross GCC/binutils `riscv64-linux-gnu-`, host C compiler, Python3
stdlib, QEMU system/user emulators, `gdb-multiarch` for debugger gates. The
licensed pinned compiler-rt sources are already vendored: no libgcc/libc link,
Python packages, network dependency, F/D extension or floating register context.

```sh
make lesson15
make run-lesson15
```

At `15>`, paste a whole source body (including standalone end marker):

```text
fappend hello.c <<END
#include <stdio.h>
#include <math.h>
int main(void) {
    int n = 5;
    int sum = 0;
    while (n > 0) {
        sum = sum + n;
        n = n - 1;
    }
    double x = 3.25;
    printf("sum=%d ceil=%f average=%f\n", sum, ceil(x), sum / 5.0);
    print_bits(min(ceil(x), max(2.0, 3.5)));
    return 23;
}
END
./cc hello.c hello
```

Wait the ACTUAL compiler PID printed by the shell (`wait PID`), then execute
`./hello` and wait its NEW PID. Expected full output is `sum=15 ceil=4.000000
average=3.000000` on one line, then `0x400c000000000000`; native exit23.
No filename/source recognition selects that result. `demo.c` contains the full
original-style demo: sum1..5, double3.25, ceil/floor/max/min/nested math, average,
and deterministic checks ending `DEMO_PASS`. Paste its actual contents the
same way; the automated float gate does this over a real PTY/UART.

`fappend` APPENDS; remove a prior source explicitly before replacement. Raw
body8192 bytes, exact standalone delimiter1..31 bytes, CR/LF/CRLF normalized to
LF; quotes, backslashes, tabs and UTF8 preserved. Cancellation/invalid controls/
overflow/RX loss reject without opening the file and STILL require the delimiter
for draining. RX loss disables raw publication until reboot. This is buffering,
not flow control. Ordinary command editing/workers/lifecycle remain available.

For cold proof: `shutdown`, launch `make run-lesson15` again, FIRST `cat hello.c`
and `cat hello` (binary bytes), then `./hello`/wait WITHOUT running cc or writing.
The tests compare the entire source and binary, not just names/header/exit8 bits.

## Explicit contracts

- [LANGUAGE.md](LANGUAGE.md): int64/double types, bounded staged decimal literal
  rounding (NOT correctly rounded strtod), conversions/traps, truth/NaNs, strict
  literal-format printf, supported includes (NOT a preprocessor), all limits.
- [RUNTIME.md](RUNTIME.md): RVEXEC1 ABI3, exact versioned ordinary-file template,
  fixed prefix/code/strings/BSS, typed APIs and dynamic module lifetime.
- [FORMAT.md](FORMAT.md): executable/DLL admission. ABI1 math_test and old integer
  ABI2 still execute. Runtime-requiring new files are unambiguously ABI3.
- [CONTRACT.md](CONTRACT.md): ownership-before-pointer, fully copied arguments,
  reserved file region through ZOMBIE/reap, stack/workspace and atomic publication.
- [softfloat/SOURCE.md](softfloat/SOURCE.md): exact LLVM19.1.7 commit, hashes,
  Apache-2.0 WITH LLVM-exception license, source list and header isolation flags.

Runtime template is read from `c_runtime` BEFORE publication; kernel and cc use
strict shared structural validation; packer/linker and runtime guards also check.
STORE/APPEND protect cc/math_test/math.dll/c_runtime. Missing/corrupt existing
files never heal. Math exports resolve lazily from ACTUAL math.dll, not from
compiler/runtime math replacements. Cache use requires a live module handle;
BSS resets on reexecution. Dynamic-rebind test replaces the actual module via
the real C filesystem on a disposable disk, keeps WHOLE executable SHA unchanged,
then cold-runs it and observes ceil42 instead of4.0 without recompilation.

Architecture remains RV64IMAC+Zicsr+Zifencei/lp64; run.py explicitly disables
F/D/Zfa in QEMU. Double arguments/results use a0/a1, not FP registers. Release/
acquire publication precedes receiver-local fence.i on BOTH pinned execution
harts; the module copy is fenced on its own receiving U hart. No page tables,
W^X security or process isolation is implied by descriptive ELF segment flags.

File/staging/READFILE limit65536 is distinct from1MiB mapped application memory.
ABI2 compiler and ABI3 programs use a private64KiB stack. Runtime prefix20KiB,
generated code32KiB, strings8KiB fit the file cap; runtime-only BSS begins beyond
payload at80510000. Compiler AST/workspaces are static, not a growing heap.
`resource-results.json` records actual maps, undefineds, vendor hashes and
pessimistic bounded static stack accounting including runtime/helper frames.

## Persistent launcher

`state/lesson15/disk.img` is copy-once outside build and survives build/clean/
reboot. Existing missing/corrupt files are not reseeded. Run/reset use the same
nonblocking host lock; uppercase `LESSON15_ARGS` is the actual selector:

```sh
make run-lesson15 LESSON15_ARGS='--disk state/lesson15/demo.img'
# DESTRUCTIVE replacement of ONLY the selected disk:
make reset-lesson15 LESSON15_ARGS='--disk state/lesson15/demo.img'
```

No prior lesson or prototype disk is migrated/modified. Boot is still lesson03's
real disk loading path with both harts. BPTFS12 geometry,1024 redo after-images
and four-FLUSH ordering remain unchanged. Deterministic store failures roll
back RAM/handles/cursors/disk; real I/O errors are uncertain and poison the FS
until recovery. Native volatile/durable model, QEMU blkdebug status1 and physical
power loss are different things; no physical durability/cache certification.

## Verification

```sh
make test-lesson15 inspect-lesson15 test-lesson15-gdb
make test-lesson15-evidence
make all test inspect
make test-lesson07-gdb test-lesson08-gdb test-lesson09-gdb
make test-lesson10-gdb test-lesson11-gdb test-lesson12-gdb
make test-lesson13-gdb test-lesson14-gdb test-lesson15-gdb
```

The ordinary gate invalidates evidence before build/import/setup. It runs:
independent full-int and Python IEEE full-bit results; NaN classification,
signed-zero/subnormal/infinity/overflow/underflow cases; native helper tests
with F/D disabled; actual unchanged integer14 ABI2 output; full demo/cold/rebind;
strict template mutants through real guest cc and ABI3 admission; full old
output/source/absence preservation; inherited lexer/resource/raw/atomic-store
regressions; source AND template READ, publication WRITE/FLUSH and late runtime
DLL READ actual virtio IOERR status1; malformed/missing DLL/no healing; actual
broken float emitter/conversion/dispatch/runtime API plus integer emitters.

Real GDB stops U cc and emitted entry on both harts, checks whole payload,
argv/native instructions, both local application fences, runtime module fences
and actual relocated DLL export execution. Six malformed admissions compare the
entire1MiB app arena and all process states before/after rejection. UART and
shutdown continue after detach. Evidence attacks run real nonzero/timeout/early
children and fake GDB/wrong CC, retain binary partial output, kill/drain/reap,
then restore actual gates. No stale PASS may survive an early failed run.

Per-run machine reports/logs are under `build/lesson15/` (ignored). Final scratch
receipt names exact candidate SHA and command exits; parent SPEC/QUALITY/fresh
archive review is separate from writer execution evidence. No CI/tag/push/cloud
or publication is part of this implementation.
