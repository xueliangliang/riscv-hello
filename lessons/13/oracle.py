"""Independent host binary64 oracle and raw-disk evidence admission."""
import hashlib
import math
import re
import struct
from decode import inspect
SIGN=1<<63
INPUTS=[0x4004000000000000,0xc004000000000000,0x3fe0000000000000,
        0xbfe0000000000000,0x4000000000000000,0xc000000000000000,
        0,SIGN,0x4330000000000000,1,SIGN|1,0x7ff0000000000000,
        0xfff0000000000000,0x7ff8000000000123,0x7ff0000000000001,
        0x432fffffffffffff]

def real(bits):
    return struct.unpack('<d',struct.pack('<Q',bits))[0]

def bits(value):
    return struct.unpack('<Q',struct.pack('<d',value))[0]

def expected(name,a,b,alternate=False):
    if alternate and name=='ceil':
        return bits(42.)
    x,y=real(a),real(b)
    if name in ('ceil','floor'):
        if not math.isfinite(x) or x==0:
            return a
        result=float(math.ceil(x) if name=='ceil' else math.floor(x))
        return bits(math.copysign(0.,x) if result==0 else result)
    if math.isnan(x):
        return b
    if math.isnan(y):
        return a
    if x==0 and y==0:
        return (a & b) if name=='max' else (a | b)
    if name=='max':
        return a if x>=y else b
    return a if x<=y else b

def exports(dll):
    table,count=struct.unpack_from('<II',dll,16)
    return {dll[table+i*24:table+i*24+16].split(b'\0')[0].decode():
            struct.unpack_from('<II',dll,table+i*24+16) for i in range(count)}

def runtime(text,pids,dll,bank,alternate=False):
    text=text.replace('\r','').replace('13> ','')
    starts=list(re.finditer(r'APP ([0-9a-f]{16}) ([0-9a-f]{16}) ([0-9a-f]{16})',text))
    assert len(starts)==len(pids), 'APP count'
    table=exports(dll)
    call_count=0
    for index,(start,pid) in enumerate(zip(starts,pids)):
        hart,base,probe=map(lambda s:int(s,16),start.groups())
        assert (hart,base,probe)==(pid&1,0x80500000,64), 'hart/entry/BSS'
        end=starts[index+1].start() if index+1<len(starts) else len(text)
        section=text[start.end():end]
        modules=[tuple(int(x,16) for x in m) for m in re.findall(r'MODULE ([0-9a-f]{16}) ([0-9a-f]{16}) ([0-9a-f]{16})',section)]
        assert modules==[(0,1,bank),(1,2,bank+4096)], 'handle/base sequence'
        symbols=re.findall(r'SYMBOL (\w+) ([0-9a-f]{16}) ([0-9a-f]{16}) ([0-9a-f]{16})',section)
        want=[]
        calls=[]
        for b in (bank,bank+4096):
            for name in ('ceil','floor','max','min'):
                offset,signature=table[name]
                want.append((name,f'{signature:016x}',f'{b:016x}',f'{b+offset:016x}'))
                for i,a in enumerate(INPUTS):
                    other=INPUTS[(i+7)%len(INPUTS)]
                    got=expected(name,a,other,alternate)
                    calls.append((name,f'{a:016x}',f'{other:016x}',f'{got:016x}'))
                if signature==2:
                    for a,other in [(0,SIGN),(SIGN,0),(0x7ff8000000000123,0x7ff8000000000456),
                                    (0x4000000000000000,0x4000000000000000)]:
                        got=expected(name,a,other,alternate)
                        calls.append((name,f'{a:016x}',f'{other:016x}',f'{got:016x}'))
        assert symbols==want, 'name/signature/base+offset'
        actual=re.findall(r'CALL (\w+) ([0-9a-f]{16}) ([0-9a-f]{16}) ([0-9a-f]{16})',section)
        assert actual==calls, 'math exact-bit/sequence result'
        call_count+=len(calls)
        assert 'CHECK BSS snapshot owner negatives active stale unload two-bases OK' in section
        assert re.search(fr'zombie pid=0x{pid:016x} value=0x0000000000000025',section), 'exact zombie PID/status'
        assert re.search(fr'reap pid=0x{pid:016x} value=0x0000000000000025',section), 'exact reap PID/status'
        assert f'wait target={pid} result=37' in section, 'exact wait PID/status'
    return {'pids':pids,'harts':[p&1 for p in pids], 'calls':call_count,
            'module_bases':[bank,bank+4096]}

def raw_disk(disk,app,dll,boot,saved=None):
    raw=disk.read_bytes()
    files=inspect(raw)['files']
    assert raw[:257*512]==boot, 'boot bytes changed'
    assert not any(raw[12288*512:12289*512]), 'journal commit not clean'
    assert files['math_test']['content']==app, 'raw executable bytes'
    assert files['math.dll']['content']==dll, 'raw DLL bytes'
    if saved is not None:
        assert files['saved']['content']==saved, 'cold content bytes'
    assert 'missing' not in files and 'missing.dll' not in files, 'read created missing file'
    return {name:{'size':files[name]['size'],
                  'sha256':hashlib.sha256(files[name]['content']).hexdigest()}
            for name in ('math_test','math.dll')}
