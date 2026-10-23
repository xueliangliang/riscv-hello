#!/usr/bin/env python3
import os
import subprocess


def command(disk="build/lesson09/disk.img"):
    return [os.environ.get("QEMU", "qemu-system-riscv64"),
            "-machine", "virt", "-accel", "tcg,thread=multi", "-cpu", "rv64,sstc=true",
            "-global", "virtio-mmio.force-legacy=false", "-smp", "2", "-m", "128M",
            "-display", "none", "-serial", "stdio", "-monitor", "none", "-bios", "none",
            "-kernel", "build/lesson09/bootloader.elf",
            "-drive", f"file={disk},if=none,format=raw,id=disk,readonly=on",
            "-device", "virtio-blk-device,drive=disk", "-no-reboot"]


if __name__ == "__main__":
    raise SystemExit(subprocess.call(command()))
