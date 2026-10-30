# Verification receipt convention

The writer's command exits and exact candidate SHA are recorded in the final
scratch receipt, not asserted by a copied older lesson's PASS. Run the documented
public make targets on your own checkout; reports under build/lesson15 are
per-run evidence and invalidated before the next outer gate begins.

The ordinary gate covers typed native binary64 and integer closure, strict
runtime15 producer/kernel negatives, full-byte preservation, cold read-first,
actual dynamic rebind, helper ABI/IEEE oracles, legacy ABI1/2, storage, raw UART,
actual virtio IOERR and semantic mutants. GDB and evidence attacks are separate
public gates. Parent SPEC/QUALITY/fresh-archive review is not performed by the
writer and is not implied by these execution reports.

A new directive-recognition ordering regression (`##` intercepted as a malformed
preprocessor directive) was isolated with the identical `frontend-test.py
--class operators` before and after its fix. The fix retains maximal munch
BEFORE directive recognition; all46 class-specific negative compiles and three
valid recoveries pass after the change. Scratch logs preserve the actual old
failure and new result; no older published lesson was edited.

A second actual regression was observed when digit-by-digit integer output
interleaved with the other hart's shell admission/prompt. The GDB test now
requires a single exact `33333+LF` WRITE, and was run fail-first on the old
byte-write runtime (length1, byte `3`) before the buffer-write fix. Exact-bit
observation lines are likewise one WRITE. printf fragments are explicitly not
a console transaction. Runtime-address breakpoints are scoped to the actual
native image lifetime so overlaid cc code cannot satisfy or spuriously trip a
runtime checkpoint; generated argc/argv checks now launch explicit copied args
rather than incorrectly expecting argv from the documented zero/zero call.

The Q1 six-decimal formatter regression (`formatter-test.py`, included in the
ordinary gate) compares full ordered input bits and output against an independent
exact-rational oracle. Its 216 finite vectors include all four reported Q1 inputs,
both signs of all three magnitudes, decimal midpoint neighbors, genuine binary
ties, carry boundaries, signed zeros, tiny/subnormal values, the range limit and
128 deterministic wide-exponent random inputs. Three nonfinite cases and two
fail-closed format/type rejection attempts are separate. This is a bounded
sample, not exhaustive binary64 verification. Inputs use exact integer conversion
and power-of-two division so the staged decimal parser is not the oracle.

The identical regression was executed first against an archive of
`60558eb137378c841b831ddf1526e824bd39ab49`, with unchanged compiler/runtime
sources and their whole-file hashes recorded. All valid programs compiled and
executed with status0 and were WAIT/reaped, but the full-output oracle exited1
on three batches, including the four reported Q1 cases. Exact integer scaling of
the decoded binary64 significand repairs the manufactured-midpoint defect;
it does not change the frozen tie-away, range, NaN, infinity or negative-zero
policies, runtime ABI or resource budgets. Old/new transcripts, hashes and the
new exact-SHA full-gate receipt live in the writer's scratch evidence, not here.
