#!/usr/bin/env python3
"""Fresh BPTFS12 fixture only; never used to mount or repair existing disks."""
import argparse
import zlib
import runpy
import struct
from pathlib import Path


def format_image(kernel, user, output):
    packer = runpy.run_path(str(Path(__file__).resolve().parents[2] / 'tools/make-disk-image.py'))
    packer['create_image'](Path(kernel), Path(user), Path(output), False)
    image = bytearray(Path(output).read_bytes())
    assert len(image) <= 257 * 512
    image.extend(bytes(8 * 1024 * 1024 - len(image)))
    struct.pack_into('<8s9I', image, 512 * 512, b'BPTFS12\0',
                     1, 512, 1024, 512, 65536, 1, 0, 1, 2048)
    image[513 * 512] = 1
    struct.pack_into('<I', image, 515 * 512, 1)
    struct.pack_into("<I", image, 512 * 512 + 508, zlib.crc32(image[512 * 512:512 * 512 + 508]))
    Path(output).write_bytes(image)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('kernel')
    p.add_argument('user')
    p.add_argument('output')
    a = p.parse_args()
    format_image(a.kernel, a.user, a.output)
