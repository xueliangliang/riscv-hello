#!/usr/bin/env python3
"""Explicit fresh FlatFS10 fixture; never run against a mounted/persistent disk."""
import argparse
import runpy
import struct
from pathlib import Path


def format_image(kernel, user, output):
    packer = runpy.run_path(str(Path(__file__).resolve().parents[2] / "tools/make-disk-image.py"))
    packer["create_image"](Path(kernel), Path(user), Path(output), False)
    image = bytearray(Path(output).read_bytes())
    assert len(image) <= 257 * 512 < 512 * 512
    image.extend(bytes(2 * 1024 * 1024 - len(image)))
    struct.pack_into("<8s6I", image, 512 * 512, b"FLATFS10", 1, 16, 64, 4096, 1024, 4096)
    Path(output).write_bytes(image)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("kernel")
    p.add_argument("user")
    p.add_argument("output")
    a = p.parse_args()
    format_image(a.kernel, a.user, a.output)
