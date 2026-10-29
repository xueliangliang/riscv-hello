#!/usr/bin/env python3
"""Writable disk launcher. Persistent disk updates/reset require explicit consent."""
import argparse
import contextlib
import fcntl
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def command(disk="state/lesson12/disk.img", readonly=False, device_extra="", drive_extra=""):
    return [os.environ.get("QEMU", "qemu-system-riscv64"),
            "-machine", "virt", "-accel", "tcg,thread=multi", "-cpu", "rv64,sstc=true",
            "-global", "virtio-mmio.force-legacy=false", "-smp", "2", "-m", "128M",
            "-display", "none", "-serial", "stdio", "-monitor", "none", "-bios", "none",
            "-kernel", "build/lesson12/bootloader.elf",
            "-drive", f"file={disk},if=none,format=raw,id=disk,readonly={'on' if readonly else 'off'}{drive_extra}",
            "-device", f"virtio-blk-device,drive=disk,write-cache=on{device_extra}", "-no-reboot"]


@contextlib.contextmanager
def disk_lock(path):
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path) + ".lock", "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit(f"disk busy: {path}")
        yield path


def install(path):
    fd, staging = tempfile.mkstemp(prefix=".disk-", dir=path.parent)
    os.close(fd)
    try:
        shutil.copyfile("build/lesson12/disk.img", staging)
        with open(staging, "rb") as f:
            os.fsync(f.fileno())
        os.replace(staging, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(staging):
            os.unlink(staging)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--disk", default="state/lesson12/disk.img")
    p.add_argument("--reset", action="store_true", help="DESTROYS disk data and installs the current fresh fixture, then exits")
    args = p.parse_args()
    with disk_lock(args.disk) as disk:
        if args.reset or not disk.exists():
            install(disk)
            print(f"installed fresh fixture: {disk}", flush=True)
        if not args.reset:
            raise SystemExit(subprocess.call(command(disk)))
