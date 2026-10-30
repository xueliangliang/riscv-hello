"""Actual copy-once make launcher, host lock, rebuild persistence and reset."""
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
from guest import Guest
from decode import decode

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

with tempfile.TemporaryDirectory(prefix='lesson14-launcher-',dir=os.environ.get('TMPDIR')) as temp:
    disk=Path(temp)/'persistent.img'
    g=Guest('launcher-first.log',str(disk),options=['make','--no-print-directory','run-lesson14',f'LESSON14_ARGS=--disk {disk}'])
    try:
        g.until('14> ')
        g.cmd('fwrite saved survives-build','fwrite target=0 result=14')
        for reset in (False,True):
            target='reset-lesson14' if reset else 'run-lesson14'
            argv=['make','--no-print-directory',target,f'LESSON14_ARGS=--disk {disk}']
            p=subprocess.run(argv,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=4)
            assert p.returncode!=0 and b'disk busy:' in p.stdout,p.stdout
        g.shutdown()
    finally:
        g.close()
    assert decode(disk)['saved']['content']==b'survives-build'
    before=digest(disk)
    subprocess.run(['make','--no-print-directory','lesson14'],check=True,stdout=subprocess.PIPE,timeout=30)
    assert digest(disk)==before
    g=Guest('launcher-second.log',str(disk),options=['python3','lessons/14/run.py','--disk',str(disk)])
    try:
        g.until('14> ')
        g.cmd('cat saved','survives-build')
        g.cmd('rm math_test','rm target=0 result=0')
        g.shutdown()
    finally:
        g.close()
    assert 'math_test' not in decode(disk)
    before=digest(disk)
    g=Guest('launcher-missing.log',str(disk),options=['python3','lessons/14/run.py','--disk',str(disk)])
    try:
        g.until('14> ')
        g.cmd('./math_test','exec target=0 result=-10')
        g.shutdown()
    finally:
        g.close()
    assert digest(disk)==before,'launcher reseeded missing executable'
    subprocess.run(['make','--no-print-directory','reset-lesson14',f'LESSON14_ARGS=--disk {disk}'],check=True,stdout=subprocess.PIPE,timeout=5)
    assert disk.read_bytes()==Path('build/lesson14/disk.img').read_bytes()
    # Existing invalid FS stays invalid, not silently reformatted.
    raw=bytearray(disk.read_bytes())
    raw[512*512]^=1
    disk.write_bytes(raw)
    before=digest(disk)
    g=Guest('launcher-corrupt.log',str(disk),True,options=['python3','lessons/14/run.py','--disk',str(disk)])
    try:
        g.until('FAIL: filesystem mount rejected')
        g.process.wait(timeout=3)
        assert g.process.returncode==1
    finally:
        g.close()
    assert digest(disk)==before
print('PASS actual launcher: copy once, two locks, build/reboot persistence, missing not reseeded, explicit reset and corrupt untouched')
