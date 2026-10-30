#!/usr/bin/env python3
"""Compile actual broken emitters; guest computation must reject all variants."""
from pathlib import Path
import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile
from native import Native
from guest import Guest
from decode import decode

spec=importlib.util.spec_from_file_location('compiler_oracle','lessons/14/compiler-test.py')
assert spec and spec.loader
oracle=importlib.util.module_from_spec(spec)
spec.loader.exec_module(oracle)
BUILD=Path('build/lesson14')

def rejects(function,*arguments):
    try:
        function(*arguments)
    except AssertionError:
        return
    raise AssertionError('mutant accepted by '+function.__name__)

with tempfile.TemporaryDirectory(prefix='lesson14-mutants-',dir=os.environ.get('TMPDIR')) as temporary:
    directory=Path(temporary)
    original=Path('lessons/14/cc.c').read_text()
    changes=[('subtract','binary(0, 32);','binary(0, 0);'),
             ('branch','emit(0x00051463);','emit(0x00050463);'),
             ('store','store(10, 8, current_node->value * 8);','store(10, 8, current_node->value * 8 + 8);')]
    cc=os.environ.get('CC','riscv64-linux-gnu-gcc')
    flags=['-march=rv64imac_zicsr_zifencei','-mabi=lp64','-mcmodel=medany','-g','-O1','-ffreestanding','-fno-builtin','-fno-pic','-fno-stack-protector','-msmall-data-limit=0','-fno-unwind-tables','-fno-asynchronous-unwind-tables','-Ilessons/14','-Ibuild/lesson14']
    records=[]
    for name,before,after in changes:
        assert original.count(before)==1
        source=directory/(name+'.c')
        source.write_text(original.replace(before,after))
        object_file=directory/(name+'.o')
        elf=directory/(name+'.elf')
        raw=directory/(name+'.raw')
        executable=directory/(name+'.exec')
        subprocess.run([cc,*flags,'-c',str(source),'-o',str(object_file)],check=True)
        subprocess.run([cc,*flags,'-nostdlib','-static','-Wl,--build-id=none','-T','lessons/14/cc.ld',str(object_file),'build/lesson14/cc-start.o','build/lesson14/formats.o','build/lesson14/syscall.o','-o',str(elf)],check=True)
        subprocess.run([os.environ.get('OBJCOPY','riscv64-linux-gnu-objcopy'),'-O','binary',str(elf),str(raw)],check=True)
        subprocess.run(['python3','lessons/14/pack.py','compiler',str(elf),str(raw),str(executable)],check=True)
        disk=directory/(name+'.img')
        shutil.copyfile(BUILD/'disk.img',disk)
        fs=Native(disk)
        # A new disposable fixture containing an actual modified compiler.
        fs.put('cc',executable.read_bytes())
        fs.save(disk)
        guest=Guest('mutant-'+name+'.log',str(disk))
        try:
            guest.until('14> ')
            body=b'int main(){int x=40; int y=7; if(x>y) print_int(x-y); else print_int(123); return 0;}\n'
            oracle.paste(guest,'mutant.c',body)
            oracle.run(guest,'./cc mutant.c native',0)
            record,transcript=oracle.run(guest,'./native',0)
            rejects(oracle.check_execution,transcript,record['pid'],0,['33'])
            assert b'cc: published native' in guest.all
            assert b'FAIL:' not in guest.all
            guest.shutdown()
            records.append(name)
        finally:
            guest.close()
    # Captured genuine evidence: change one invariant at a time.
    results=json.loads((BUILD/'runtime-results.json').read_text())
    whole=(BUILD/'compiler-uart.log').read_bytes()
    item=results['programs'][0]
    pid=item['execution']['pid']
    status=item['execution']['status']
    expected=item['expected']
    oracle.check_execution(whole,pid,status,expected)
    rejects(oracle.check_execution,whole.replace(expected[0].encode()+b'\r\n',b'999\r\n'),pid,status,expected)
    rejects(oracle.check_execution,whole.replace(f'reap pid=0x{pid:016x}'.encode(),b'reap pid=0x0000000000000000'),pid,status,expected)
    rejects(oracle.check_execution,whole.replace(f'wait target={pid} result={status}'.encode(),f'wait target={pid} result=0'.encode()),pid,status,expected)
    files=decode(BUILD/'compiler-verified.img')
    original_output=files['loop']['content']
    oracle.native_header(original_output)
    for offset in (8,24,32,48+int.from_bytes(original_output[20:24],'little')):
        mutant=bytearray(original_output)
        mutant[offset]^=1
        rejects(oracle.native_header,bytes(mutant))
    for name in ('loop','loop.c'):
        original_file=files[name]['content']
        mutant=bytearray(original_file)
        mutant[-1]^=1
        rejects(oracle.check_saved,bytes(mutant),original_file)
    # Cold wrong-source fixture must fail guest read-first BEFORE any writes.
    disk=directory/'cold.img'
    shutil.copyfile(BUILD/'compiler-verified.img',disk)
    fs=Native(disk)
    fs.put('loop.c',b'WRONG PERSISTED SOURCE\n')
    fs.save(disk)
    before=disk.read_bytes()
    guest=Guest('mutant-cold.log',str(disk))
    try:
        guest.until('14> ')
        start=len(guest.all)
        guest.cmd('cat loop.c','WRONG PERSISTED SOURCE')
        assert files['loop.c']['content'].replace(b'\n',b'\r\n') not in guest.all[start:]
        guest.shutdown()
    finally:
        guest.close()
    assert disk.read_bytes()==before
    # Neither a missing compiler nor malformed executable is silently reseeded.
    for mode in ('missing','header'):
        disk=directory/(mode+'.img')
        shutil.copyfile(BUILD/'disk.img',disk)
        fs=Native(disk)
        if mode=='missing':
            assert fs.lib.fs_remove(b'cc')==0
        else:
            data=bytearray((BUILD/'cc.exec').read_bytes())
            data[32]=3
            fs.put('cc',bytes(data))
        fs.save(disk)
        before=disk.read_bytes()
        guest=Guest('mutant-'+mode+'.log',str(disk))
        try:
            guest.until('14> ')
            guest.cmd('./cc','exec target=0 result='+('-10' if mode=='missing' else '-4'))
            guest.shutdown()
        finally:
            guest.close()
        assert disk.read_bytes()==before
    (BUILD/'mutation-results.json').write_text(json.dumps({'status':'PASS','actual_broken_emitters_rejected':records,'captured_evidence':['result','reap_pid','wait_status','header','machine_prologue','saved_source','saved_code'],'cold_wrong_source':True,'no_selfheal':['missing','header']},indent=2)+'\n')
print('PASS actual subtraction/branch/store compiler mutants, full-int/PID/status/byte oracles, cold wrong-source and no selfheal')
