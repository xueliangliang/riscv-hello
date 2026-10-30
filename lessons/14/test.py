#!/usr/bin/env python3
"""Real UART/PID/FS loading, independent math and cold/raw evidence gates."""
import ctypes as c
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from guest import Guest
from native import Native
from vectors import negatives
from oracle import runtime,raw_disk,assert_cat
from pack import symbols
from decode import decode

BUILD=Path('build/lesson14')

def rejected(action):
    try:
        action()
    except AssertionError:
        return
    raise AssertionError('mutated evidence accepted')

def start(log,disk):
    g=Guest(log,str(disk))
    try:
        g.until('13> ')
    except BaseException:
        g.close()
        raise
    return g

def application(g,pid):
    g.cmd('./math_test',f'exec target=0 result={pid}')
    g.cmd('exec math_test','exec target=0 result=-13') # live reservation
    g.read(.8)
    g.cmd('exec math_test','exec target=0 result=-13') # ZOMBIE reservation
    g.cmd(f'wait {pid}',f'wait target={pid} result=37')

def verify_cold_saved(g):
    assert_cat(g.cmd('cat saved'),b'cold-loader-journal')

def snapshot_native(disk):
    fs=Native(disk)
    stage=c.create_string_buffer(65536)
    dll=(BUILD/'math.dll').read_bytes()
    assert fs.lib.snapshot_read(b'math.dll',stage,65536)==len(dll)
    assert stage.raw[:len(dll)]==dll
    for _ in range(8):
        assert fs.lib.snapshot_read(b'missing.dll',stage,65536)==-10
        assert fs.lib.snapshot_read(b'math.dll',stage,1)==-17
    handles=[fs.lib.fs_open(name.encode(),0) for name in ('math.dll','math_test')]
    assert all(h>=0 for h in handles),'snapshot leaked handles'
    for h in handles:
        assert fs.lib.fs_close(h)==0
    # Fail a real data sector read. The staged failure must still close its
    # private handle (verified by opening the same file after remount).
    block=decode(disk)['math.dll']['head']
    fs.lib.model_fault(0,2048+(block-1)*8,1,0)
    assert fs.lib.snapshot_read(b'math.dll',stage,65536)==-14
    fs.check()
    # Inherited FS is poisoned after IOERR, but close must still release.
    assert fs.lib.test_live_handles()==0
    assert fs.lib.snapshot_read(b'math.dll',stage,65536)==-14
    fs.check()
    return 'actual C snapshot capacity/missing/IO cleanup'

def main():
    app=(BUILD/'math_test.exec').read_bytes()
    dll=(BUILD/'math.dll').read_bytes()
    alternate=(BUILD/'math-alt.dll').read_bytes()
    bank=symbols(BUILD/'math_test.elf')['banks']
    apps,modules=negatives(app,dll)
    assert len(modules)==18, "keep actual U negative fixture loop in sync"
    fixture=BUILD/'disk.img'
    boot=fixture.read_bytes()[:257*512]
    result={'native':snapshot_native(fixture),'cold':[]}
    mutation_count=0
    with tempfile.TemporaryDirectory(prefix='lesson14-',dir=os.environ.get('TMPDIR')) as temp:
        directory=Path(temp)
        disk=directory/'cold.img'
        shutil.copyfile(fixture,disk)
        fs=Native(disk)
        for i,blob in enumerate(modules.values()):
            fs.put(f'bad{i:02}.dll',blob)
        for i,blob in enumerate(apps.values()):
            fs.put(f'bad{i:02}.exec',blob)
        fs.save(disk)
        malformed_files={**{f'bad{i:02}.dll':blob for i,blob in enumerate(modules.values())},
                         **{f'bad{i:02}.exec':blob for i,blob in enumerate(apps.values())}}
        stored=decode(disk)
        assert all(stored[name]['content']==blob for name,blob in malformed_files.items())
        for cold in range(2):
            g=start(f'cold-{cold}.log',disk)
            try:
                g.cmd('ls','file: math.dll size=')
                if cold:
                    # Read persisted bytes BEFORE any same-value overwrite.
                    verify_cold_saved(g)
                g.cmd('exec missing','exec target=0 result=-10')
                for i in range(len(apps)):
                    g.cmd(f'exec bad{i:02}.exec','exec target=0 result=-4')
                application(g,17)
                g.cmd('run spin 0','run target=1 result=33')
                application(g,18) # occupied odd slot -> receiving hart0
                g.cmd('kill 33')
                g.cmd('wait 33','wait target=33 result=137')
                # Fill every child slot, including unreaped zombies.
                for pid in (49,34,19,20,21,22,23):
                    g.cmd('run exit 7',f'run target=3 result={pid}')
                g.cmd('exec math_test','exec target=0 result=-3')
                g.cmd('run exit 7','run target=3 result=-3')
                for pid in (49,34,19,20,21,22,23):
                    g.cmd(f'wait {pid}',f'wait target={pid} result=7')
                g.cmd('wait 17','wait target=17 result=-1')
                g.cmd('fwrite saved cold-loader-journal','fwrite target=0 result=19')
                saved_text=g.cmd('cat saved')
                assert_cat(saved_text,b'cold-loader-journal')
                rejected(lambda:assert_cat(saved_text.replace('cold-loader-journal','WRONG-COLD-CONTENT'),
                                           b'cold-loader-journal'))
                mutation_count+=1
                g.shutdown()
                text=g.all.decode(errors='replace')
            finally:
                g.close()
            observation=runtime(text,[17,18],dll,bank)
            observation['raw']=raw_disk(disk,app,dll,boot,b'cold-loader-journal')
            after=decode(disk)
            assert all(after[name]['content']==blob for name,blob in malformed_files.items())
            observation['malformed_files_checked']=len(malformed_files)
            result['cold'].append(observation)
            # Independently break every claimed evidence layer.
            mutations=[('CALL ceil','CALL wrong'),
                       ('4008000000000000','4008000000000001'),
                       ('SYMBOL ceil 0000000000000001','SYMBOL ceil 0000000000000002'),
                       (f'MODULE 0000000000000000 0000000000000001 {bank:016x}',
                        f'MODULE 0000000000000000 0000000000000001 {bank+16:016x}'),
                       (f'SYMBOL ceil 0000000000000001 {bank:016x} {bank+int.from_bytes(dll[48:52],"little"):016x}',
                        f'SYMBOL ceil 0000000000000001 {bank:016x} {bank+2:016x}'),
                       ('wait target=17 result=37','wait target=17 result=36'),
                       ('wait target=18 result=37','wait target=19 result=37'),
                       ('APP 0000000000000001','APP 0000000000000000')]
            for before,after in mutations:
                assert before in text,before
                rejected(lambda:runtime(text.replace(before,after,1),[17,18],dll,bank))
                mutation_count+=1
            rejected(lambda:raw_disk(disk,app,dll,boot,b'WRONG-COLD-CONTENT'))
            mutation_count+=1
        # Real DLL rebinding, not a different application or fake output.
        variant=directory/'variant.img'
        shutil.copyfile(fixture,variant)
        fs=Native(variant)
        fs.put('math.dll',alternate)
        fs.save(variant)
        assert decode(variant)['math_test']['content']==app
        assert hashlib.sha256(alternate).digest()!=hashlib.sha256(dll).digest()
        g=start('variant.log',variant)
        try:
            application(g,17)
            g.shutdown()
            text=g.all.decode(errors='replace')
        finally:
            g.close()
        result['variant']=runtime(text,[17],alternate,bank,True)
        rejected(lambda:runtime(text,[17],dll,bank))
        mutation_count+=1
        result['variant']['raw']=raw_disk(variant,app,alternate,boot)
        # Existing deleted/corrupt ordinary files never self-heal on reboot.
        for kind in ('missing-app','missing-dll','corrupt-dll'):
            negative=directory/(kind+'.img')
            shutil.copyfile(fixture,negative)
            fs=Native(negative)
            if kind.startswith('missing'):
                name='math_test' if kind=='missing-app' else 'math.dll'
                assert fs.lib.fs_remove(name.encode())==0
            else:
                fs.put('math.dll',b'X'+dll[1:])
            fs.save(negative)
            before=negative.read_bytes()
            g=start(kind+'.log',negative)
            try:
                if kind=='missing-app':
                    g.cmd('./math_test','exec target=0 result=-10')
                else:
                    g.cmd('./math_test','exec target=0 result=17')
                    g.read(.8)
                    g.cmd('wait 17','wait target=17 result=41')
                    assert b'MODULE_MISSING_OR_INVALID' in g.all
                g.shutdown()
            finally:
                g.close()
            assert negative.read_bytes()==before,(kind,'self-healed/mutated')
    result['status']='PASS'
    result['oracle_mutations']=mutation_count
    (BUILD/'runtime-results.json').write_text(json.dumps(result,indent=2)+'\n')
    print('PASS lesson14 real dual-hart UART, two cold boots, exact bits, lifecycle, malformed U paths, raw disks, changed DLL and oracle mutations')

if __name__=='__main__':
    main()
