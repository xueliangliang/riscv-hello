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
