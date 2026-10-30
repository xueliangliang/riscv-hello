#!/usr/bin/env python3
"""Build/test unmodified compiler-rt sources entirely in $TMPDIR scratch."""
import hashlib
import json
import math
import os
from pathlib import Path
import random
import struct
import subprocess
import tempfile

integration = Path(__file__).resolve().parent
root = integration / 'softfloat'
manifest = json.loads((root / 'UPSTREAM.json').read_text())
for info in manifest['files']:
    assert hashlib.sha256((root / info['name']).read_bytes()).hexdigest() == info['sha256'], info['name']
scratch = Path(tempfile.mkdtemp(prefix='rv64-softfloat-', dir=os.environ['TMPDIR']))
cc = os.environ.get('CC', 'riscv64-linux-gnu-gcc')
include = subprocess.check_output([cc, '-print-file-name=include'], text=True).strip()
flags = ['-march=rv64imac_zicsr_zifencei', '-mabi=lp64', '-mcmodel=medany',
         '-Os', '-ffreestanding', '-fno-builtin', '-fno-pic', '-fno-stack-protector',
         '-fno-asynchronous-unwind-tables', '-fno-unwind-tables',
         '-Wall', '-Wextra', '-Werror', '-nostdinc', '-isystem', include,
         '-D_LIBC_LIMITS_H_', '-I' + str(root), '-I' + str(scratch)]

def run(args, **kw):
    return subprocess.run(args, check=True, **kw)

objects = []
for name in sorted(info['name'] for info in manifest['files']):
    if not name.endswith('.c'):
        continue
    obj = scratch / (name[:-2] + '.o')
    run([cc, *flags, '-c', str(root / name), '-o', str(obj)])
    objects.append(str(obj))
combined = scratch / 'combined.o'
run(['riscv64-linux-gnu-ld', '-r', *objects, '-o', str(combined)])
assert not subprocess.check_output(['riscv64-linux-gnu-nm', '-u', str(combined)], text=True).strip()
run(['riscv64-linux-gnu-ar', 'rcs', str(scratch / 'libsoftfloat.a'), *objects])
run(['riscv64-linux-gnu-readelf', '-h', '-A', str(combined)])

rng = random.Random(1917)
def bits(x):
    return struct.unpack('>Q', struct.pack('>d', x))[0]
def value(u):
    return struct.unpack('>d', struct.pack('>Q', u))[0]
def signed(x, width):
    x &= (1 << width) - 1
    return x - (1 << width) if x >> (width - 1) else x

def divide(a, b):
    if b == 0.0:
        if a == 0.0 or math.isnan(a):
            return float('nan')
        return math.copysign(float('inf'), math.copysign(1.0, a) * math.copysign(1.0, b))
    return a / b

edge = [0, 1, 0xfffffffffffff, 0x10000000000000, 0x3ff0000000000000,
        0x3ff0000000000001, 0x3ca0000000000000, 0x7fefffffffffffff,
        0x7ff0000000000000, 0x7ff8000000000000]
edge += [u ^ (1 << 63) for u in edge]
pairs = [(a, b) for a in edge for b in edge]
pairs += [(rng.getrandbits(64), rng.getrandbits(64)) for _ in range(2000)]
arith = []
for u, v in pairs:
    a, b = value(u), value(v)
    arith.append([u, v, bits(a+b), bits(a-b), bits(a*b), bits(divide(a,b))])
integers = [0, 1, 2**31-1, 2**31, 2**32-1, 2**53-1, 2**53+1,
            2**63-1, 2**63, 2**64-1]
integers += [rng.getrandbits(64) for _ in range(1000)]
intconv = [[u, bits(float(signed(u, 64))), bits(float(u)),
            bits(float(signed(u, 32))), bits(float(u & 0xffffffff))] for u in integers]
fixconv = [[bits(a), int(a)] for a in [0.0, 0.5, 1.5, 2147483647.75] +
           [rng.random()*2147483647 for _ in range(1000)]]
with (scratch / 'vectors.inc').open('w') as out:
    for name, rows in [('arith', arith), ('intconv', intconv), ('fixconv', fixconv)]:
        out.write('static const U %s[][%d] = {\n' % (name, len(rows[0])))
        for row in rows:
            out.write('{' + ','.join('0x%xULL' % u for u in row) + '},\n')
        out.write('};\n')
(scratch / 'start.S').write_text('''
.text
.globl _start
_start:
  call main
  li a7, 93
  ecall
1: j 1b
.section .note.GNU-stack,"",@progbits
''')
exe = scratch / 'test.elf'
run([cc, *flags, '-nostdlib', '-static', '-no-pie', '-Wl,-e,_start',
     str(scratch / 'start.S'), str(integration / 'helper-test.c'),
     str(scratch / 'libsoftfloat.a'), '-o', str(exe)])
assert not subprocess.check_output(['riscv64-linux-gnu-nm', '-u', str(exe)], text=True).strip()
run(['qemu-riscv64', '-cpu', 'rv64,f=false,d=false,zfa=false', str(exe)], timeout=30)
print('PASS: %d arithmetic pairs (4 operations + negation), %d integer-to-double rows '
      '(4 widths/signs), %d double-to-integer rows (4 widths/signs), '
      'signed/unsigned boundaries and ordered/unordered comparisons; QEMU F/D disabled.'
      % (len(arith), len(intconv), len(fixconv)))
print('No compiler warnings (-Werror), no unresolved symbols; vendor hashes verified.')
print('Scratch artifacts:', scratch)
print('FLAGS:', ' '.join(flags))
