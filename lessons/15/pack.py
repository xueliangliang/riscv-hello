"""Producer: reject unsupported ELF features; only custom files enter the FS."""
from pathlib import Path
import os
import struct
import subprocess
import sys

def tool(name, *args):
    prefix=os.environ.get('CROSS_COMPILE','riscv64-linux-gnu-')
    return subprocess.check_output([prefix+name,*map(str,args)],text=True)

def symbols(elf):
    result={}
    for line in tool('nm','-n',elf).splitlines():
        fields=line.split()
        if len(fields)==3:
            result[fields[2]]=int(fields[0],16)
    assert not tool('nm','-u',elf).strip(), 'unresolved symbol'
    return result

def module(elf,raw,output):
    sym=symbols(elf)
    assert 'There are no relocations' in tool('readelf','-rW',elf)
    sections=tool('readelf','-SW',elf)
    for forbidden in ('.got','.bss','.data','.rodata','.tdata','.tbss','.dynamic','.rela'):
        assert forbidden not in sections, forbidden
    payload=Path(raw).read_bytes()
    header=struct.pack('<8s6I',b'RVDLL01\0',1,128+len(payload),32,4,128,1)
    for name,signature in [('ceil',1),('floor',1),('max',2),('min',2)]:
        header+=struct.pack('<16sII',name.encode(),sym['math_'+name],signature)
    assert len(header)==128 and len(payload)>0 and len(header+payload)<=4096
    Path(output).write_bytes(header+payload)

def executable(elf,raw,output,abi=1):
    sym=symbols(elf)
    payload=Path(raw).read_bytes()
    base=0x80500000
    assert len(payload)==sym['__payload_end']-base
    header=struct.pack('<8s10I',b'RVEXEC1\0',1,48+len(payload),len(payload),
                       sym['app_entry']-base,base,sym['__memory_end']-base,
                       abi,sym['__code_end']-base,0,0)
    assert len(header+payload)<=65536
    Path(output).write_bytes(header+payload)

if __name__=='__main__':
    if sys.argv[1] == 'compiler':
        executable(*sys.argv[2:], abi=2)
    else:
        {'module':module,'executable':executable}[sys.argv[1]](*sys.argv[2:])
