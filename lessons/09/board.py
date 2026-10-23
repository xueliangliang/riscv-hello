#!/usr/bin/env python3
"""Decode QEMU's actual DTB without dtc; assert the board assumptions we use."""
import hashlib
import json
from pathlib import Path
import struct
import subprocess
from run import command


def decode(data):
    magic, total, structure, strings, *_ = struct.unpack_from(">10I", data)
    assert magic == 0xd00dfeed and total == len(data)
    names = data[strings:]
    offset = structure
    stack = []
    nodes = {}
    while True:
        token = struct.unpack_from(">I", data, offset)[0]
        offset += 4
        if token == 1:
            end = data.index(0, offset)
            stack.append(data[offset:end].decode())
            offset = (end + 4) & ~3
            nodes["/".join(stack)] = {}
        elif token == 2:
            stack.pop()
        elif token == 3:
            size, name = struct.unpack_from(">II", data, offset)
            offset += 8
            end = names.index(0, name)
            nodes["/".join(stack)][names[name:end].decode()] = data[offset:offset+size]
            offset = (offset + size + 3) & ~3
        elif token == 4:
            continue
        elif token == 9:
            return nodes
        else:
            raise AssertionError((token, offset))


def main():
    path = Path("build/lesson09/virt.dtb")
    result = subprocess.run(command() + ["-machine", f"virt,dumpdtb={path}"],
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=5)
    assert result.returncode == 0, result.stdout
    data = path.read_bytes()
    nodes = decode(data)
    serial = nodes["/soc/serial@10000000"]
    plic = nodes["/soc/plic@c000000"]
    cells = lambda blob: struct.unpack(">" + "I"*(len(blob)//4), blob)
    assert b"ns16550a\0" in serial["compatible"]
    assert cells(serial["reg"]) == (0, 0x10000000, 0, 0x100)
    assert cells(serial["interrupts"]) == (10,)
    assert cells(plic["reg"])[:2] == (0, 0xc000000)
    assert cells(serial["interrupt-parent"]) == cells(plic["phandle"])
    contexts = cells(plic["interrupts-extended"])
    assert contexts[1::2] == (11, 9, 11, 9), contexts
    assert cells(nodes["/cpus"]["timebase-frequency"]) == (10000000,)
    report = {"qemu": subprocess.check_output([command()[0], "--version"], text=True).splitlines()[0],
              "dtb_sha256": hashlib.sha256(data).hexdigest(),
              "uart": "ns16550a 0x10000000 IRQ10", "plic": "0x0c000000",
              "contexts": list(contexts), "timebase": 10000000}
    Path("build/lesson09/platform.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
