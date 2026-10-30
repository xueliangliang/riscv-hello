#!/usr/bin/env python3
"""Arm AFTER mount; actual runtime's late DLL READ status1 must fail closed."""
from pathlib import Path
import importlib.util
import json
import os
import shutil
import tempfile
from decode import decode
from guest import Guest
from run import command

spec = importlib.util.spec_from_file_location('compiler_oracle','lessons/15/compiler-test.py')
assert spec and spec.loader
oracle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oracle)
BUILD = Path('build/lesson15')
with tempfile.TemporaryDirectory(prefix='lesson15-dll-read-',dir=os.environ.get('TMPDIR')) as temporary:
    directory = Path(temporary)
    disk = directory/'disk.img'
    shutil.copyfile(BUILD/'float-verified.img',disk)
    files = decode(disk)
    sector = 2048+(files['math.dll']['head']-1)*8
    config = directory/'late-read.conf'
    config.write_text('[set-state]\nevent = "write_aio"\nstate = "1"\nnew_state = "2"\n'
                      '[inject-error]\nevent = "read_aio"\nstate = "2"\n'
                      f'sector = "{sector}"\nerrno = "5"\nonce = "on"\n')
    guest = Guest('runtime-dll-read-ioerr.log',str(disk),True,
                  options=command(f'blkdebug:{config}:{disk}',device_extra=',werror=report,rerror=report'))
    try:
        guest.until('15> ')
        guest.cmd('fwrite arm ready','fwrite target=0 result=5')
        _,transcript = oracle.run(guest,'./binding',70)
        assert b'math.dll missing, unreadable or malformed' in transcript
        assert b'request-type=0x0000000000000000 status=0x0000000000000001' in transcript
        assert b'0x4045000000000000\r\n' not in transcript
        guest.shutdown(failure=True)
    finally:
        guest.close()
    after = decode(disk)
    for name in ('math.dll','binding','binding.c'):
        assert after[name]['content'] == files[name]['content']
    guest = Guest('runtime-dll-read-recovery.log',str(disk))
    try:
        guest.until('15> ')
        for name in ('binding.c','binding'):
            start = len(guest.all)
            guest.cmd('cat '+name,'cat target=0 result=0')
            assert files[name]['content'].replace(b'\n',b'\r\n') in guest.all[start:]
        oracle.run(guest,'./binding',0,['0x4045000000000000','0xc010000000000000'])
        guest.shutdown()
    finally:
        guest.close()
(BUILD/'dll-io-results.json').write_text(json.dumps({'status':'PASS','actual_IOERR_status':1,'late_runtime_DLL_READ':True,'first_read_cold_recovery':True})+'\n')
print('PASS actual late runtime DLL READ IOERR, nonzero exit/reap, sticky poison, unchanged whole executable/source/module and cold recovery')
