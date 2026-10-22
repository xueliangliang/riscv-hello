#!/usr/bin/env bash
set -euo pipefail

boot_elf=${1:-build/lesson03/bootloader.elf}
valid_disk=${2:-build/lesson03/disk.img}
bad_disk=${3:-build/lesson03/disk-bad-magic.img}
qemu=${QEMU:-qemu-system-riscv64}
readelf=${READELF:-riscv64-linux-gnu-readelf}

for tool in "$qemu" "$readelf" timeout grep; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        printf 'missing required command: %s\n' "$tool" >&2
        exit 1
    fi
done

headers=$("$readelf" -h "$boot_elf")
if ! grep -q 'Machine:.*RISC-V' <<<"$headers"; then
    printf 'not a RISC-V bootloader ELF: %s\n' "$boot_elf" >&2
    exit 1
fi
if ! grep -q 'Entry point address:.*0x80000000' <<<"$headers"; then
    printf 'unexpected bootloader entry address in %s\n' "$boot_elf" >&2
    exit 1
fi

run_qemu() {
    local disk_image=$1
    local output_name=$2
    local output
    local status

    # QEMU otherwise exposes the legacy MMIO version 1 transport.
    set +e
    output=$(timeout --foreground --kill-after=2s 10s "$qemu" \
        -machine virt \
        -global virtio-mmio.force-legacy=false \
        -smp 1 \
        -m 128M \
        -display none \
        -serial stdio \
        -monitor none \
        -bios none \
        -kernel "$boot_elf" \
        -drive "file=$disk_image,if=none,format=raw,id=lesson_disk,readonly=on" \
        -device virtio-blk-device,drive=lesson_disk \
        -no-reboot </dev/null 2>&1)
    status=$?
    set -e

    printf '%s\n' "$output"
    printf -v "$output_name" '%s' "$output"
    printf -v "${output_name}_status" '%s' "$status"
}

run_qemu "$valid_disk" good_output
good_status=$good_output_status
if [ "$good_status" -ne 0 ]; then
    printf 'QEMU valid-image run exited with status %d.\n' "$good_status" >&2
    exit 1
fi
for message in \
    'Lesson 03: M-mode bootloader started.' \
    'Boot record validated; loading kernel and shell from disk.' \
    'Bootloader: both images loaded; jumping to kernel at 0x80200000.' \
    'Kernel: entered from the virtio block image.' \
    'Shell payload: loaded from disk and called by the kernel.' \
    'PASS: boot record, kernel/shell reads, and handoff verified.'; do
    if ! grep -Fq "$message" <<<"$good_output"; then
        printf 'missing expected boot output: %s\n' "$message" >&2
        exit 1
    fi
done

run_qemu "$bad_disk" bad_output
bad_status=$bad_output_status
if [ "$bad_status" -eq 0 ] || [ "$bad_status" -eq 124 ]; then
    printf 'QEMU malformed-image run returned unexpected status %d.\n' "$bad_status" >&2
    exit 1
fi
if ! grep -Fq 'ERROR: boot record magic does not match.' <<<"$bad_output"; then
    printf 'malformed boot record was not rejected for the expected reason.\n' >&2
    exit 1
fi

printf 'PASS: disk boot handoff works and a bad boot record is rejected.\n'
