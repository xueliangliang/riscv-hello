#!/usr/bin/env python3
"""Pack a lesson-03 boot record, kernel, and shell payload into a disk image."""

from __future__ import annotations

import argparse
import struct
from pathlib import Path

SECTOR_SIZE = 512
BOOT_MAGIC = b"RVKERN01"
BAD_MAGIC = b"BADBOOT!"
HEADER = struct.Struct("<8sIIQQQQQQQQ")
KERNEL_LOAD_ADDRESS = 0x80200000
SHELL_LOAD_ADDRESS = 0x80400000
KERNEL_LBA = 1
MAX_IMAGE_BYTES = 64 * 1024


def create_image(
    kernel_path: Path,
    shell_path: Path,
    output_path: Path,
    corrupt_magic: bool,
) -> None:
    kernel = kernel_path.read_bytes()
    shell = shell_path.read_bytes()
    if not kernel:
        raise ValueError("kernel image is empty")
    if not shell:
        raise ValueError("shell image is empty")
    if len(kernel) > MAX_IMAGE_BYTES:
        raise ValueError(f"kernel image exceeds {MAX_IMAGE_BYTES} bytes")
    if len(shell) > MAX_IMAGE_BYTES:
        raise ValueError(f"shell image exceeds {MAX_IMAGE_BYTES} bytes")

    kernel_sector_count = (len(kernel) + SECTOR_SIZE - 1) // SECTOR_SIZE
    shell_sector_count = (len(shell) + SECTOR_SIZE - 1) // SECTOR_SIZE
    shell_lba = KERNEL_LBA + kernel_sector_count
    magic = BAD_MAGIC if corrupt_magic else BOOT_MAGIC
    boot_sector = bytearray(SECTOR_SIZE)
    HEADER.pack_into(
        boot_sector,
        0,
        magic,
        1,                  # format version
        HEADER.size,
        KERNEL_LBA,
        len(kernel),
        KERNEL_LOAD_ADDRESS,
        KERNEL_LOAD_ADDRESS,
        shell_lba,
        len(shell),
        SHELL_LOAD_ADDRESS,
        SHELL_LOAD_ADDRESS,
    )

    padded_kernel = kernel.ljust(kernel_sector_count * SECTOR_SIZE, b"\0")
    padded_shell = shell.ljust(shell_sector_count * SECTOR_SIZE, b"\0")
    image = bytes(boot_sector) + padded_kernel + padded_shell
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(image)
    print(
        f"created {output_path}: {len(image)} bytes, "
        f"kernel={len(kernel)} bytes ({kernel_sector_count} sectors), "
        f"shell={len(shell)} bytes ({shell_sector_count} sectors)"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kernel", type=Path, help="raw kernel binary")
    parser.add_argument("shell", type=Path, help="raw shell payload binary")
    parser.add_argument("output", type=Path, help="output disk image")
    parser.add_argument(
        "--corrupt-magic",
        action="store_true",
        help="write an invalid boot-record signature for the negative test",
    )
    return parser.parse_args()


def main() -> None:
    arguments = parse_args()
    create_image(
        arguments.kernel,
        arguments.shell,
        arguments.output,
        arguments.corrupt_magic,
    )


if __name__ == "__main__":
    main()
