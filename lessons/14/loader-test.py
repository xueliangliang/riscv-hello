"""Actual U C loader lifecycle on host; RISC-V execution is tested in QEMU."""
import ctypes as c
from pathlib import Path
import subprocess
from vectors import negatives
subprocess.run(['cc','-shared','-fPIC','-O1','-Wall','-Wextra','-Werror',
                '-Ilessons/14','lessons/14/native-loader.c','lessons/14/formats.c',
                '-o','build/lesson14/loader.so'],check=True)
lib=c.CDLL(str(Path('build/lesson14/loader.so').resolve()))
for name,args,result in [
    ('test_fixture',[c.c_void_p,c.c_uint,c.c_long],None),
    ('test_generation',[c.c_ulong],None),('test_banks_clear',[],c.c_uint),
    ('module_load',[c.c_char_p],c.c_ulong),
    ('module_base',[c.c_ulong],c.c_ulong),
    ('module_symbol',[c.c_ulong,c.c_char_p,c.c_uint],c.c_void_p),
    ('module_unload',[c.c_ulong],c.c_int)]:
    fn=getattr(lib,name)
    fn.argtypes=args
    fn.restype=result
app=Path('build/lesson14/math_test.exec').read_bytes()
dll=Path('build/lesson14/math.dll').read_bytes()
_,bad=negatives(app,dll)
for blob in bad.values():
    lib.test_fixture(blob,len(blob),0)
    assert lib.module_load(b'math.dll')==0
    assert lib.test_banks_clear()==1
for error in (-10,-14,-17):
    lib.test_fixture(dll,len(dll),error)
    assert lib.module_load(b'math.dll')==0
    assert lib.test_banks_clear()==1
lib.test_fixture(dll,len(dll),0)
one=lib.module_load(b'math.dll')
assert one==1
base=lib.module_base(one)
pointer=lib.module_symbol(one,b'ceil',1)
assert pointer and c.string_at(base,len(dll))==dll
# Error/malformed second candidate cannot replace or clear an active image.
lib.test_fixture(b'broken',6,-14)
assert lib.module_load(b'other.dll')==0
assert lib.module_symbol(one,b'ceil',1)==pointer
assert c.string_at(base,len(dll))==dll
assert lib.module_unload(one)==0
assert not lib.module_symbol(one,b'ceil',1)
assert lib.test_banks_clear()==1
lib.test_fixture(dll,len(dll),0)
two=lib.module_load(b'math.dll')
assert two==2 and lib.module_base(two)==base+4096
assert not lib.module_symbol(one,b'ceil',1)
assert lib.module_unload(two)==0
# Exercise the exact saturation branch, not a host copy of its arithmetic.
maximum=(1<<(c.sizeof(c.c_ulong)*8))-1
lib.test_generation(maximum-1)
last=lib.module_load(b'math.dll')
assert last==maximum
assert lib.module_unload(last)==0
assert lib.module_load(b'math.dll')==0
assert not lib.module_symbol(one,b'ceil',1)
assert lib.test_banks_clear()==1
print('PASS actual U C module loader: malformed/IO atomicity, busy, clear, ABA and generation saturation')
