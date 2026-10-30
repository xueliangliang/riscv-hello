#!/usr/bin/env python3
"""A saved ABI3 program must diagnose real missing/corrupt/wrong-signature DLL."""
from pathlib import Path
import importlib.util
import json
import os
import shutil
import tempfile
from guest import Guest
from native import Native
from decode import decode
from vectors import u32

spec = importlib.util.spec_from_file_location('oracle','lessons/15/compiler-test.py')
assert spec and spec.loader
oracle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oracle)
BUILD = Path('build/lesson15')
dll = (BUILD/'math.dll').read_bytes()
variants = {'missing':None, 'short':dll[:31], 'magic':b'X'+dll[1:],
            'signature':u32(dll,52,2),'missing-export':dll[:32]+b'other'+bytes(11)+dll[48:]}
records = []
with tempfile.TemporaryDirectory(prefix='lesson15-module-negative-',dir=os.environ.get('TMPDIR')) as temporary:
    directory = Path(temporary)
    for name,blob in variants.items():
        disk = directory/(name+'.img')
        shutil.copyfile(BUILD/'float-verified.img',disk)
        fs = Native(disk)
        assert fs.lib.fs_remove(b'math.dll') == 0
        if blob is not None:
            fs.put('math.dll',blob)
        fs.save(disk)
        before = disk.read_bytes()
        files = decode(disk)
        guest = Guest('module-negative-'+name+'.log',str(disk))
        try:
            guest.until('15> ')
            for target in ('binding.c','binding'):
                start = len(guest.all)
                guest.cmd('cat '+target,'cat target=0 result=0')
                assert files[target]['content'].replace(b'\n',b'\r\n') in guest.all[start:]
            for _ in range(2):
                record,transcript = oracle.run(guest,'./binding',70)
                assert b'runtime15: math.dll ' in transcript
                assert b'0x4045000000000000\r\n' not in transcript
            guest.shutdown()
        finally:
            guest.close()
        assert disk.read_bytes() == before,'module failure silently healed or wrote disk'
        records.append(name)
(BUILD/'module-negative-results.json').write_text(json.dumps({'status':'PASS','actual_runtime_errors':records,'reexec_twice':True,'cold_read_first':True,'no_disk_mutation':True})+'\n')
print('PASS actual dynamic math missing/corrupt/signature/export errors; nonzero exit, no stale-cache call, no healing')
