"""Pack exact runtime15 prefix, validating maps, targets, and undefineds."""
from pathlib import Path
import struct
import sys
from pack import symbols
elf, raw, output = sys.argv[1:]
sym = symbols(elf)
base = 0x80500000
names = ['guard', 'integer', 'floating', 'text', 'bits', 'itod', 'dtoi', 'truth', 'neg', 'add', 'sub', 'mul', 'div', 'eq', 'ne', 'lt', 'le', 'gt', 'ge', 'ceil', 'floor', 'max', 'min']
signatures = [1, 2, 3, 4, 3, 5, 6, 6, 7, 8, 8, 8, 8, 9, 9, 9, 9, 9, 9, 7, 7, 8, 8]
start = sym['__functions_begin'] - base
end = sym['__functions_end'] - base
assert start == 256 and start >= 64 + 8*len(names)
assert start < end <= 20480
assert sym['__runtime_bss_begin'] - base == 65536
assert 65536 <= sym['__runtime_bss_end'] - base <= 1048576
payload = Path(raw).read_bytes()
assert len(payload) == sym['__runtime_payload_end'] - sym['__functions_begin']
image = bytearray(20480)
image[start:start+len(payload)] = payload
struct.pack_into('<8s14I', image, 0, b'RVRT15\0\0', 1,20480,len(names),64,start,end,65536,
                 sym['__runtime_bss_end']-base,20480,53248,1,0,0,0)
for i, (name, signature) in enumerate(zip(names, signatures)):
    target = sym['rt_'+name] - base
    assert start <= target < end and target % 2 == 0
    struct.pack_into('<II',image,64+i*8,target,signature)
Path(output).write_bytes(image)
