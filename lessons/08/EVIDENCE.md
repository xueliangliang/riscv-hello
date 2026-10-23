# Lesson08 implementation evidence

Base integrated by fast-forward cherry-pick: `7c12ab4215ff68b1af39449e3fed28f318e9ef80`
(the reviewed lesson07 wait-oracle correction). No lesson01–07 source changes
are part of the lesson08 implementation commit.

## Executed gate

```sh
make clean
make all test inspect test-lesson07-gdb test-lesson08-gdb
```

The complete command returned **0**. The run rebuilt all lessons01–08, exercised
all positive/negative test targets, inspected ELF headers/program headers and
instruction disassembly, and ran the real lesson07 and lesson08 GDB checks.
The negative guest FAIL lines in the regression log are intentional rejection
cases, not accepted timeouts.

Tools observed in that run:

- QEMU 10.2.1 (`10.2.1+ds-1ubuntu3.2`)
- riscv64-linux-gnu-gcc 15.2.0 (`15.2.0-16ubuntu1`)
- GDB 17.1 (`17.1-2ubuntu1`)

`build/verification.log` is the full gate output. The lesson08 test creates
five positive disk boots, a real PTY boot, broken-context and broken-lock disk
boots, log-oracle mutation rejection evidence, and explicit timeout rejection.
The two GDB disk boots each inspect one hart and then complete the full guest
lifecycle with the same host oracle. No tag or push is performed here.

## Sample captured values, not a performance benchmark

Every row below had participant mask **3**, final counter **8000**, inside **0**
and overlap violations **0**. Timer and contention counts are observations,
not required golden constants.

| Log under `build/lesson08/` | Lock contention hart0 / hart1 | Timer samples hart0 / hart1 |
|---|---|---|
| `positive-0.log` | 32238 / 41527 | 17 / 12 |
| `positive-1.log` | 35318 / 39308 | 17 / 12 |
| `positive-2.log` | 29672 / 39829 | 17 / 12 |
| `positive-3.log` | 32724 / 38619 | 17 / 12 |
| `positive-4.log` | 34326 / 38457 | 17 / 12 |
| `pty.log` | 30220 / 41269 | 17 / 12 |
| `gdb-hart0-uart.log` | 32859 / 38319 | 17 / 12 |
| `gdb-hart1-uart.log` | 35671 / 39296 | 17 / 12 |

Both spinner tasks were timer-interrupted in the independently disassembled
`[spin_loop, spin_loop_end)` interval on their assigned hart, with saved U-origin,
independent SP/data, preserved `tp=0xdeadbeef`, and increasing progress. Both
harts made progress while the controller and long-sleeping child were blocked.

`bad-context.log` actually ended in `FAIL: spin context restore` with guest exit1.
`bad-lock.log` actually reached both counter participants, then reported
`shared counter lost update` and `FAIL: user assertion`, with guest exit1. Its
forced first-read rendezvous guarantees a lost update when locking is bypassed.

The per-child host model requires wait-call → matching target/child status →
proper parent WAITING/immediate path → exact return/reap ordering. Mutants are
recorded in `oracle-mutations.log`; deleting all wait-block or all wait-call
records is rejected, as are wrong-target/status and missing-kill-completion logs.

## Layout inspected

The gate's linked symbols place M stacks at `0x80203000`, S stacks at
`0x80205000`, metadata tops at `0x80208ff0` and `0x8020cff0`, and kernel BSS end
at `0x8020dc40`. User shared counter/BSS is `0x80402000`–`0x80402040`, distinct
from explicit instance data and eight user stacks. Kernel/user raw sizes were
9080 / 5769 bytes; the packed disk was 15872 bytes.

The raw disk SHA-256 in this build was:

```text
791a2d5d7fd4022e5f98be27d76009a70c92be360b7c4eb7d74ff1c42c3e01cc
```

ELF debug paths may vary in an independent directory; this is not a claim of
path-independent ELF byte reproducibility. The build-time memory boundaries,
actual guest behavior, and host oracle must still pass from an archive.

## Scope and remaining review

This demonstrates QEMU architectural/software behavior for two **pinned**
harts, globally locked lifecycle, race-sensitive shared-state synchronization,
and deferred remote RUNNING kill. It does not prove arbitrary race schedules,
real-board/RTL correctness, memory isolation, fairness, scalability or speedup.
Idle is persistent lock-releasing polling with SIE disabled, not low-power WFI.
The explicit demo DONE syscall shuts down; there is no implicit idle timeout.
UART input/PLIC/getchar wait registration, shell, migration and filesystem are
not implemented. Parent independent review is required before any immutable tag.
