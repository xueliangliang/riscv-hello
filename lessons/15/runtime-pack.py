"""Embed a bounded, versioned, relocation-free integer syscall helper."""
from pathlib import Path
import struct
import subprocess
import sys
import os

elf, binary, output = map(Path, sys.argv[1:])
prefix = os.environ.get('CROSS_COMPILE', 'riscv64-linux-gnu-')
assert not subprocess.check_output([prefix + 'nm', '-u', str(elf)]).strip()
assert b'There are no relocations' in subprocess.check_output([prefix + 'readelf', '-rW', str(elf)])
data = binary.read_bytes()
magic, version, size, entry, a, b, c = struct.unpack_from('<8s6I', data)
assert magic == b'RVINT14\0' and version == 1 and size == len(data)
assert 32 <= entry < size <= 512 and not entry % 4 and not (a or b or c)
output.write_text('#define INTEGER_RUNTIME_VERSION 1\n'
                  f'#define INTEGER_RUNTIME_SIZE {size}\n'
                  f'#define INTEGER_PRINT_OFFSET {entry}\n'
                  'static const unsigned char integer_runtime[] = {\n' +
                  ','.join(str(byte) for byte in data) + '\n};\n')
