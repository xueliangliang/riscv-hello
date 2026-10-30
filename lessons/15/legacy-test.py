#!/usr/bin/env python3
"""Compile using unchanged lesson14 U cc; execute that ABI2 image in lesson15."""
from pathlib import Path
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from native import Native
from guest import Guest

BUILD = Path('build/lesson15')
subprocess.run(['make','--no-print-directory','lesson14'],check=True)
with tempfile.TemporaryDirectory(prefix='lesson15-old-abi2-',dir=os.environ.get('TMPDIR')) as temporary:
    directory = Path(temporary)
    output = directory/'old.exec'
    disk14 = directory/'old.img'
    shutil.copyfile('build/lesson14/disk.img',disk14)
    code = '''
import sys
from pathlib import Path
from importlib.machinery import SourceFileLoader
sys.path.insert(0,'lessons/14')
from guest import Guest
from decode import decode
m=SourceFileLoader('old_oracle','lessons/14/compiler-test.py').load_module()
g=Guest('abi2-for15.log',sys.argv[1])
try:
    g.until('14> ')
    m.paste(g,'old.c','int main(){int i=5;int sum=0;while(i>0){sum=sum+i;i=i-1;}print_int(sum*900719925474099);return 39;}\\n')
    m.run(g,'./cc old.c old',0)
    m.run(g,'./old',39,['13510798882111485'])
    g.shutdown()
finally:
    g.close()
Path(sys.argv[2]).write_bytes(decode(sys.argv[1])['old']['content'])
'''
    subprocess.run([sys.executable,'-c',code,str(disk14),str(output)],check=True)
    image = output.read_bytes()
    assert int.from_bytes(image[32:36],'little') == 2
    assert image[48:56] == b'RVINT14\0'
    disk15 = directory/'new.img'
    shutil.copyfile(BUILD/'disk.img',disk15)
    fs = Native(disk15)
    fs.put('old',image)
    fs.save(disk15)
    spec = importlib.util.spec_from_file_location('oracle15','lessons/15/compiler-test.py')
    assert spec and spec.loader
    oracle = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(oracle)
    guest = Guest('legacy-abi2.log',str(disk15))
    try:
        guest.until('15> ')
        record,_ = oracle.run(guest,'./old',39,['13510798882111485'])
        oracle.run(guest,'./math_test',37)
        guest.shutdown()
    finally:
        guest.close()
    (BUILD/'legacy14.exec').write_bytes(image)
    (BUILD/'legacy-results.json').write_text(json.dumps({'status':'PASS','old_ABI2_actual_lesson14_guest_compile':True,'new_kernel_execution':record,'old_ABI1_math_test_status':37})+'\n')
print('PASS actual old integer ABI2 image and old ABI1 math_test execute without runtime15 requirement')
