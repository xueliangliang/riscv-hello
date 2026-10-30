#!/usr/bin/env python3
"""Malformed runtime15: native validator AND actual guest producer/admission."""
from pathlib import Path
import ctypes as c
import importlib.util
import json
import os
import re
import shutil
import struct
import subprocess
import tempfile
from native import Native
from decode import decode
from guest import Guest
from vectors import u32

spec = importlib.util.spec_from_file_location('compiler_oracle', 'lessons/15/compiler-test.py')
assert spec and spec.loader
oracle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oracle)
BUILD = Path('build/lesson15')


def mutants(template):
    end = struct.unpack_from('<I', template, 28)[0]
    result = {'short':template[:-1], 'trailing':template+b'x', 'magic':b'X'+template[1:]}
    for name,offset,value in [('version',8,2),('size',12,20479),('count',16,22),
                              ('count-overflow',16,0xffffffff),('table-overflow',20,0xfffffff8),
                              ('table-off-by-one',20,65),('function-begin',24,248),
                              ('function-end',28,20482),('empty-functions',28,256),
                              ('bss-overlap',32,53248),('bss-under',36,65520),
                              ('bss-overflow',36,1048592),('bss-unaligned',36,65537),
                              ('code-base',40,20478),('string-base',44,53249),
                              ('api-version',48,2),('reserved',52,1),
                              ('target-header',64,0),('target-end',64,end),
                              ('target-odd',64,257),('signature',68,2),('table-padding',248,1)]:
        result[name] = u32(template,offset,value)
    return result


def main():
    subprocess.run(['cc','-shared','-fPIC','-Wall','-Wextra','-Werror','lessons/15/formats.c','-o',str(BUILD/'formats.so')],check=True)
    lib = c.CDLL(str((BUILD/'formats.so').resolve()))
    lib.runtime_valid.argtypes = [c.c_void_p,c.c_ulong]
    lib.runtime_valid.restype = c.c_int
    template = (BUILD/'c_runtime').read_bytes()
    assert lib.runtime_valid(template,len(template)) == 1
    variants = mutants(template)
    for name,blob in variants.items():
        assert lib.runtime_valid(blob,len(blob)) == 0,name
    source = b'int main(){double x=2.5;print_bits(x*4);return 0;}\n'
    records = []
    with tempfile.TemporaryDirectory(prefix='lesson15-template-',dir=os.environ.get('TMPDIR')) as temporary:
        directory = Path(temporary)
        baseline = directory/'baseline.img'
        shutil.copyfile(BUILD/'disk.img',baseline)
        guest = Guest('template-setup.log',str(baseline))
        try:
            guest.until('15> ')
            oracle.paste(guest,'source.c',source)
            oracle.run(guest,'./cc source.c old',0)
            guest.shutdown()
        finally:
            guest.close()
        old = decode(baseline)['old']['content']
        for name,blob in {**variants,'missing':None}.items():
            disk = directory/(name+'.img')
            shutil.copyfile(baseline,disk)
            fs = Native(disk)
            assert fs.lib.fs_remove(b'c_runtime') == 0
            if blob is not None:
                fs.put('c_runtime',blob)
            fs.save(disk)
            before = disk.read_bytes()
            guest = Guest('template-'+name+'.log',str(disk))
            try:
                guest.until('15> ')
                status = 3 if name in ('trailing','missing') else 1
                for output in ('old','absent'):
                    oracle.run(guest,'./cc source.c '+output,status)
                    files = decode(disk)
                    assert files['source.c']['content'] == source
                    assert files['old']['content'] == old and 'absent' not in files
                guest.shutdown()
            finally:
                guest.close()
            assert disk.read_bytes() == before,'template failure mutated disk: '+name
            records.append(name)
        # Full malformed ABI3 files traverse EXEC, not just host validation.
        disk = directory/'admission.img'
        shutil.copyfile(baseline,disk)
        fs = Native(disk)
        admissions = {}
        for index,(name,blob) in enumerate(variants.items()):
            if name in ('short','trailing'):
                continue
            image = bytearray(old)
            image[48:48+20480] = blob
            filename = 'bad'+str(index)
            admissions[filename] = bytes(image)
            fs.put(filename,bytes(image))
        for name,offset,value in [('badabi',32,4),('badentry',20,256),('badmemory',28,65536),('badcode',36,53250)]:
            image = u32(old,offset,value)
            admissions[name] = image
            fs.put(name,image)
        fs.save(disk)
        before = disk.read_bytes()
        guest = Guest('template-admission.log',str(disk))
        try:
            guest.until('15> ')
            for name in admissions:
                transcript = guest.cmd('./'+name,'exec target=0 result=-4')
                assert 'spawn pid=' not in transcript and 'zombie pid=' not in transcript
                guest.cmd('ps')
            oracle.run(guest,'./old',0,['0x4024000000000000'])
            guest.shutdown()
        finally:
            guest.close()
        assert disk.read_bytes() == before
        (BUILD/'template-results.json').write_text(json.dumps({'status':'PASS','producer_rejections':records,'kernel_admission_rejections':list(admissions),'full_source_old_output_and_missing_preserved':True},indent=2)+'\n')
    print('PASS strict runtime15 mutations: actual compiler preservation, no healing, ABI3 kernel no-child admission rejection')


if __name__ == '__main__':
    main()
