"""Independent byte fixtures; same rejected files later traverse actual U loading."""
import struct

def u32(blob, offset, value):
    out = bytearray(blob)
    struct.pack_into('<I', out, offset, value)
    return bytes(out)

def negatives(app, dll):
    apps = {'truncated': app[:47], 'magic': b'X'+app[1:],
            'version': u32(app,8,2), 'overflow': u32(app,16,0xfffffff0),
            'trailing': app+b'x', 'entry': u32(app,20,0xffffffff),
            'alignment': u32(app,20,1), 'address': u32(app,24,0x80400000),
            'memory': u32(app,28,0xffffffff), 'abi': u32(app,32,3),
            'reserved': u32(app,44,1), 'code': u32(app,36,0),
            'short-code':u32(app,36,1), 'odd-code':u32(app,36,3)}
    table = struct.unpack_from('<I',dll,16)[0]
    code = struct.unpack_from('<I',dll,24)[0]
    modules = {'truncated':dll[:31], 'magic':b'X'+dll[1:],
               'version':u32(dll,8,2), 'overflow':u32(dll,16,0xfffffff8),
               'trailing':dll+b'x', 'table':u32(dll,24,32),
               'header-target':u32(dll,table+16,0),
               'alignment':u32(dll,table+16,code+1),
               'range':u32(dll,table+16,len(dll)),
               'signature':u32(dll,table+20,3), 'abi':u32(dll,28,2),
               'count':u32(dll,20,0xffffffff),
               'oversized':dll+bytes(4098-len(dll)),
               'odd-image':u32(dll+b'x',12,len(dll)+1)}
    for name, value in [('empty',bytes(16)), ('unterminated',b'x'*16),
                         ('padding',b'a\0x'+bytes(13))]:
        modules[name]=dll[:table]+value+dll[table+16:]
    blob=bytearray(dll)
    blob[table+24:table+40]=blob[table:table+16]
    modules['duplicate']=bytes(blob)
    return apps, modules

if __name__ == '__main__':
    import ctypes as c
    import subprocess
    from pathlib import Path
    subprocess.run(['cc','-shared','-fPIC','-Wall','-Wextra','-Werror',
                    'lessons/14/formats.c','-o','build/lesson14/formats.so'],check=True)
    lib=c.CDLL(str(Path('build/lesson14/formats.so').resolve()))
    class Executable(c.Structure):
        _fields_=[('payload',c.c_uint32),('entry',c.c_uint32),('memory',c.c_uint32),('abi',c.c_uint32)]
    lib.executable_valid.argtypes=[c.c_void_p,c.c_ulong,c.POINTER(Executable)]
    lib.executable_valid.restype=c.c_int
    lib.module_valid.argtypes=[c.c_void_p,c.c_ulong]
    lib.module_valid.restype=c.c_int
    app=struct.pack('<8s10I',b'RVEXEC1\0',1,64,16,0,0x80500000,32,1,16,0,0)+bytes(16)
    dll=struct.pack('<8s6I',b'RVDLL01\0',1,84,32,2,80,1)
    dll+=struct.pack('<16sII',b'ceil',80,1)+struct.pack('<16sII',b'floor',82,1)+bytes(4)
    assert lib.executable_valid(app,len(app),c.byref(Executable()))==1
    abi2=u32(u32(app,32,2),28,1048576)
    assert lib.executable_valid(abi2,len(abi2),c.byref(Executable()))==1
    assert lib.executable_valid(u32(abi2,28,1048592),len(abi2),c.byref(Executable()))==0
    assert lib.executable_valid(u32(app,28,65552),len(app),c.byref(Executable()))==0
    assert lib.module_valid(dll,len(dll))==1
    apps,modules=negatives(app,dll)
    for name, blob in apps.items():
        assert lib.executable_valid(blob,len(blob),c.byref(Executable()))==0,name
    for name, blob in modules.items():
        assert lib.module_valid(blob,len(blob))==0,name
    print('PASS actual native C parser:',len(apps),'EXEC and',len(modules),'DLL rejections')
