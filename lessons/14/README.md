# 14 — paste C source, compile in U mode, execute saved RV64 code

This milestone is **host-built / guest-running**, not compiler self-hosting.
The separate ordinary-file `cc` application reads the actual guest source,
lexes/parses/type-checks it, emits native RV64 instructions, then publishes a
complete custom executable through one filesystem transaction. It exits and
must be reaped before the independently loaded generated program can execute.
A fresh QEMU process can run that saved file without recompilation.

## Run from the repository root

Dependencies: RV64 cross GCC/binutils (`riscv64-linux-gnu-`), host C compiler,
Python3 standard library, QEMU system emulator and `gdb-multiarch` for debugger
checks. No downloaded compiler library or Python package is needed.

```sh
make lesson14
make run-lesson14
```

Paste this **whole block**, including its standalone end marker:

```text
fappend demo.c <<END
int main(void) {
    int n = 8;
    int total = 0;
    while (n > 0) {
        total = total + n * n;
        n = n - 1;
    }
    puts("native RV64 result:");
    print_int(total * 1234567);
    return 23;
}
END
./cc demo.c demo
```

The shell prints the actual compiler PID. Use `wait PID` with that exact PID,
then `./demo` and `wait NEW_PID`. The printed full integer result is 251851668;
its exit status is 23. Reboot with `shutdown`, then `make run-lesson14`, and run
`cat demo.c`, `./demo` and `wait PID` **without running cc again**.
`exec cc demo.c demo` is equivalent. PIDs carry generation and slot, not hart
number; do not reuse example numbers after other launches.

`fappend` appends, including on an existing file. Remove an old source explicitly
if replacement is intended. Raw bodies preserve tabs, quotes, backslashes and
UTF-8; CR/LF/CRLF normalize to LF. The terminator must match the entire line.
Empty bodies do not create files. Invalid controls, cancellation, overflow or
RX loss reject the entire body without opening the file, then drain through
its terminator. **Ctrl-C/D still require the terminator to resynchronize.**
RX losses are sticky for raw publication until reboot; a later baseline must
not hide losses from a command that was already queued. Buffering is not flow
control. See [the contracts](CONTRACT.md) for actual bounds and ownership.

## What is supported

[LANGUAGE.md](LANGUAGE.md) defines the bounded integer teaching language:
64-bit `int`, locals and lexical blocks, assignment, unary and arithmetic /
comparison operators, if/else, while, return, comments, string escapes,
`puts("literal")` and `print_int(integer)`. `print_int` is a typed builtin, not
ISO printf. Unsupported syntax is diagnosed, not skipped. Literal overflow,
EOF, parse/code/stack/workspace limits all fail before output publication.
Syntax errors and missing sources preserve the entire old output or absence.
Parenthesized locals are assignable; unary plus produces a value, not an lvalue.
Unsupported `++`/`--` and other C multi-character punctuators are rejected with
maximal munch, never silently split into different valid arithmetic. Whitespace
and comments still separate supported unary/binary operators. Each `int x;`
declaration resets its local to zero; references to a declaring local in its own
initializer (including assignment and shadowing) are rejected explicitly.
The compiler refuses identical source/output names; the kernel publication
API additionally protects `cc`, `math_test` and `math.dll`.

No floating arithmetic, full C preprocessor, pointers, structures, general
functions or floating/dynamic-math compiler runtime is introduced here. Those
are later scope. The inherited ABI1 `./math_test` and PIC `math.dll` behavior
remain available; executable ABI2 arguments do not change the DLL ABI1 table.

## Integration and bounded memory

- Boot remains the lesson03 disk loader, with the secondary-hart wrapper and
  both real harts. No direct-kernel boot shortcut or runtime reseeding.
- File bytes and READFILE staging remain <=65536. Only ABI2 **memory** may reach
  1 MiB at 0x80500000; its large compiler buffers are static BSS, not heap growth.
- ABI2 uses one exclusive 64 KiB stack, 0x80410000–0x80420000. Eight old 4 KiB
  worker/ABI1 stacks and per-slot argument data remain in their original ranges.
- Raw bytes and shell BSS live in a shell-only NOLOAD workspace at
  0x80420000–0x80424000. This relocation avoids the inherited shell's near-full
  low-BSS region. Link-time and measured checks assert all boundaries.
- Arguments are fully copied and owned before READY, BSS/stack are initialized,
  and shared application memory remains reserved through ZOMBIE until reap.
  Release/acquire publication precedes the receiving hart's own `fence.i`.
- `fs_store` composes private create/truncate and chunk writes under **one** redo
  transaction. Deterministic failures restore disk, metadata and handles.
  Real I/O errors are uncertain, poison the FS and require recovery.
- Generated files contain native instructions, a small versioned integer-output
  helper and string data, not source text or an interpreter. `integer-runtime.S`
  only prints full signed integers through SYS_WRITE. There are no unresolved
  imports or F/D instructions. These custom containers are not ELF/PE.

The actual measured sizes, BSS endpoints, all stack/workspace bounds and static
stack-usage accounting are generated in `build/lesson14/resource-results.json`.

## Persistence and launch selection

The new ignored `state/lesson14/disk.img` is copied once from a freshly built
fixture. Builds, clean and reboot preserve it. Existing missing/corrupt files
are not self-healed. Run/reset share a nonblocking host lock.

```sh
make run-lesson14 LESSON14_ARGS='--disk state/lesson14/demo.img'
# Explicitly destructive, replacing only the selected disk:
python3 lessons/14/run.py --disk state/lesson14/demo.img --reset
```

`make reset-lesson14` destructively resets the default lesson14 disk. No earlier
lesson or prototype disk is migrated or rewritten. BPTFS12 geometry, 1024-sector
redo and four-FLUSH protocol are unchanged.

## Verification

```sh
make test-lesson14
make inspect-lesson14
make test-lesson14-gdb
make test-lesson14-evidence
python3 lessons/14/frontend-fail-first.py
make all test inspect
make test-lesson07-gdb test-lesson08-gdb test-lesson09-gdb
make test-lesson10-gdb test-lesson11-gdb test-lesson12-gdb
make test-lesson13-gdb test-lesson14-gdb
```

The ordinary gate invalidates old logs/results before build or imports. Its
real PTY tests paste multiple unrelated programs and verify actual cc launch,
full native bytes, exact PID exit/wait/reap, full-width results and cold read-first
source/output execution with no recompilation. Operators include negative signed
division/remainder, zero divisors, INT64_MIN/-1 and wrapping arithmetic; independent
expectations use exact integers, never float division. Larger programs emit over
a page of code. Scope, spelling, precedence, branch and string variations are
covered, alongside negative compiler output preservation and raw input boundaries.

`frontend-test.py` is included in the ordinary gate: 80 invalid real U-mode
compilations across lvalues, increment, decrement, initializers and other
unsupported punctuators check exact line/type/token diagnostics, nonzero exit,
no success banner, full old executable/source preservation and missing-output
absence. Fifteen valid compile/execute/reap recovery runs check parenthesized
assignment, spaced/comment-separated unary signs, right-associative assignment,
scope, per-iteration zero initialization and full-width integers. Boot bytes,
clean journal and raw filesystem invariants are checked independently. Thirty-five
mutations of captured evidence attack the new rejection oracle.
`frontend-fail-first.py` builds the unchanged `dba51e6` archive in scratch and
runs the identical regression separately for lvalue, increment, decrement and
self-initializer defects; all four must fail with actual old compiler status0,
old-file overwrite and missing-file creation, not just changed diagnostic text.
Its receipt/logs remain in the printed scratch archive. No old history is edited.

Native tests exercise actual C store/append, deterministic rollback, all journal
cut phases and both persisted/nonpersisted I/O-error outcomes. A reduced-capacity
native build exercises defensive J_LIMIT rollback; production geometry remains
1024. Real QEMU blkdebug tests separately report virtio status1 for compiler
READ/WRITE/FLUSH failures, exact exit/reap and sticky failure/cold recovery.
Actual broken subtraction/branch/local-store compilers are cross-built only as
mutants, run in U mode, and rejected by the same full-result oracle. Captured
PID/status/header/code/source/cold byte mutations are also rejected.

GDB checks compiler AND emitted-program U entry, complete bytes against the
persisted files, copied argv, actual native instructions and both receiving harts'
local fence. UART continues after detach. This is QEMU architectural evidence,
not a physical instruction-cache or power-cut certification. Flat PMP still
permits RAM access; syscall admission is not a security sandbox.

Artifacts under `build/lesson14/`: `results.json`, `runtime-results.json`,
`resource-results.json`, `store-results.json`, `mutation-results.json`,
`compiler-uart.log`, `compiler-cold.log`, `compiler-verified.img`, `raw-loss.log`,
`io-compiler-*.log`, `gdb-loader.log`, and launcher/mutant transcripts.
`frontend-all-results.json` and `frontend-all-uart.log` record the focused
regressions; the outer `results.json` also includes their results.
The evidence gate rejects wrong CC, early debugger setup and fake GDB, retains
partial/timeout child output, reaps children, then restores actual runtime/GDB
checks. Attack transcripts are retained in `$TMPDIR/lesson14-evidence/`.
