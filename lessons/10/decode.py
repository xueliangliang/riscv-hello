#!/usr/bin/env python3
"""Independent raw-image decoder: no imports from formatter or guest code."""
import argparse
import hashlib
import json
import re
import struct
from pathlib import Path


def decode(path):
    disk = Path(path).read_bytes()
    assert len(disk) == 2097152, "disk size"
    start = 262144
    header = struct.unpack_from("<8s6I", disk, start)
    assert header == (b"FLATFS10", 1, 16, 64, 4096, 1024, 4096), "format header"
    assert disk[start + 32:start + 512] == bytes(480), "header reserved"
    files = {}
    for slot in range(16):
        record = disk[start + 512 + slot * 64:start + 512 + (slot + 1) * 64]
        used, size, sector = struct.unpack_from("<III", record, 32)
        if used == 0:
            assert record == bytes(64), "unused record not zero"
            continue
        assert used == 1 and size <= 4096, "record bounds"
        assert sector == 1024 + slot * 8, "extent/slot bounds"
        name, delimiter, padding = record[:32].partition(b"\0")
        assert delimiter and 1 <= len(name) <= 31 and re.fullmatch(rb"[a-zA-Z0-9_.-]+", name), "name"
        assert not any(padding) and record[44:] == bytes(20), "record reserved"
        name = name.decode("ascii")
        assert name not in files, "duplicate name"
        payload = disk[sector * 512:sector * 512 + size]
        files[name] = {"slot": slot, "lba": sector, "size": size,
                       "content": payload, "sha256": hashlib.sha256(payload).hexdigest()}
    return files


def report(files):
    return {name: {key: value for key, value in entry.items() if key != "content"}
            for name, entry in files.items()}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("disk", type=Path)
    print(json.dumps(report(decode(p.parse_args().disk)), indent=2))
