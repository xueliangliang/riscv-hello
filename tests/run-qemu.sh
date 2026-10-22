#!/usr/bin/env bash
set -euo pipefail

image=${1:-build/lesson01.elf}
qemu=${QEMU:-qemu-system-riscv64}
readelf=${READELF:-riscv64-linux-gnu-readelf}

for tool in "$qemu" "$readelf" timeout grep; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        printf 'missing required command: %s\n' "$tool" >&2
        exit 1
    fi
done

headers=$("$readelf" -h "$image")
if ! grep -q 'Machine:.*RISC-V' <<<"$headers"; then
    printf 'not a RISC-V ELF: %s\n' "$image" >&2
    exit 1
fi
if ! grep -q 'Entry point address:.*0x80000000' <<<"$headers"; then
    printf 'unexpected entry address in %s\n' "$image" >&2
    exit 1
fi
segments=$("$readelf" -lW "$image")
if ! grep -q 'LOAD.*0x0000000080000000' <<<"$segments"; then
    printf 'no PT_LOAD segment starts at 0x80000000 in %s\n' "$image" >&2
    exit 1
fi

set +e
# This test only emits UART bytes. Keep timeout in the foreground process group
# and detach serial input from the interactive terminal; otherwise QEMU can be
# stopped by SIGTTIN when GNU timeout puts it in a background process group.
output=$(timeout --foreground --kill-after=2s 10s "$qemu" \
    -machine virt \
    -smp 1 \
    -m 128M \
    -display none \
    -serial stdio \
    -monitor none \
    -bios none \
    -kernel "$image" \
    -no-reboot </dev/null 2>&1)
status=$?
set -e

printf '%s\n' "$output"
if [ "$status" -ne 0 ]; then
    printf 'QEMU exited with status %d (expected guest test-device success).\n' "$status" >&2
    exit "$status"
fi
if ! grep -Fq 'Lesson 01: RISC-V entry reached.' <<<"$output"; then
    printf 'expected UART line was not observed.\n' >&2
    exit 1
fi
printf 'PASS: RISC-V ELF entry and UART output verified.\n'
