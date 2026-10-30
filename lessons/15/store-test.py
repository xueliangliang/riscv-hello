#!/usr/bin/env python3
"""Actual C whole-store transactions: disk/RAM rollback and durability cuts."""
import ctypes as c
from pathlib import Path
import json
import os
import struct
import subprocess
import tempfile
import zlib
from native import Native
from decode import inspect

BUILD=Path('build/lesson15')

def durable(fs):
    fs.check()
    out=c.create_string_buffer(8*1024*1024)
    fs.lib.model_disk(out)
    fs.check()
    return out.raw

def get(fs,name):
    out=c.create_string_buffer(65536)
    count=fs.lib.snapshot_read(name.encode(),out,65536)
    fs.check()
    assert count>=0, count
    return out.raw[:count]

def load(fs,data):
    fs.lib.model_load(data)
    assert fs.lib.model_run(0)==0
    fs.check()

def main():
    fs=Native(BUILD/'disk.img')
    clean=durable(fs)
    records=[]
    old=b'old publication\0binary\xff'*400
    assert fs.lib.fs_store(b'publish',old,len(old),0)==len(old)
    baseline=durable(fs)
    for body in (b'',b'a',bytes(range(256))*150,b'new shorter'):
        assert fs.lib.fs_store(b'publish',body,len(body),0)==len(body)
        assert get(fs,'publish')==body
        before=durable(fs)
        assert fs.lib.fs_store(b'publish',b'\x00tail\xff',6,1)==6
        assert get(fs,'publish')==body+b'\x00tail\xff'
        assert durable(fs)!=before
    load(fs,baseline)
    # Busy and malformed operations preserve whole disk, live handles, cursor.
    token=fs.lib.fs_open(b'publish',0)
    out=c.create_string_buffer(7)
    assert fs.lib.fs_read(token,out,7)==7 and out.raw==old[:7]
    before=durable(fs)
    assert fs.lib.fs_store(b'publish',b'new',3,0)==-13
    assert fs.lib.fs_read(token,out,7)==7 and out.raw==old[7:14]
    assert fs.lib.fs_sync()==0 and durable(fs)==before
    assert fs.lib.fs_close(token)==0
    for name,count,append in ((b'bad/name',1,0),(b'new',65537,0),(b'new',1,2)):
        before=durable(fs)
        assert fs.lib.fs_store(name,b'x',count,append)==-4
        assert fs.lib.fs_sync()==0 and durable(fs)==before
        assert fs.lib.test_live_handles()==0
    # Epoch exhaustion can fail after private open/truncate; rollback restores all.
    epoch=bytearray(baseline)
    struct.pack_into('<I',epoch,512*512+36,0xfffffffe)
    struct.pack_into('<I',epoch,512*512+508,zlib.crc32(epoch[512*512:512*512+508]))
    load(fs,bytes(epoch))
    before=durable(fs)
    assert fs.lib.fs_store(b'publish',b'x'*8192,8192,0)==-11
    assert fs.lib.fs_sync()==0 and durable(fs)==before
    assert get(fs,'publish')==old and fs.lib.test_live_handles()==0
    # Both replacement and append run through the SAME real outer transaction.
    expected=bytes((index*29+7)&255 for index in range(8192))
    fs.lib.model_crash.argtypes=[c.c_uint,c.c_uint]
    fs.lib.model_crash.restype=None
    for operation in (14,15):
        after=expected if operation==14 else old+expected
        for phase in range(1,9):
            load(fs,baseline)
            fs.lib.model_crash(phase,1 if phase==5 else 0)
            assert fs.lib.model_run(operation)==-99
            fs.check()
            assert fs.lib.model_run(0)==0
            fs.check()
            recovered=get(fs,'publish')
            assert recovered==(old if phase<=3 else after),(operation,phase)
            image=durable(fs)
            inspect(image)
            assert image[:512*512]==baseline[:512*512]
            assert not any(image[12288*512:12289*512])
            assert fs.lib.model_run(0)==0 and durable(fs)==image
            records.append({'operation':operation,'cut':phase,'outcome':'old' if recovered==old else 'new'})
        # Every FLUSH failure can be reported before OR after persistence.
        faults=[(0,-1,1),(1,-1,1),(1,12288,1)]+[(4,-1,index) for index in range(1,5)]
        for kind,sector,occurrence in faults:
            for persisted in (0,1):
                load(fs,baseline)
                fs.lib.model_fault(kind,sector,occurrence,persisted)
                assert fs.lib.model_run(operation)==-14,(kind,sector,occurrence)
                fs.check()
                assert fs.lib.fs_sync()==-14, 'uncertain IO must fail closed'
                fs.lib.model_cut()
                assert fs.lib.model_run(0)==0
                fs.check()
                recovered=get(fs,'publish')
                assert recovered in (old,after),(kind,sector,occurrence,persisted)
                image=durable(fs)
                inspect(image)
                assert not any(image[12288*512:12289*512])
                assert image[:512*512]==baseline[:512*512]
                records.append({'operation':operation,'fault':[kind,sector,occurrence,persisted], 'outcome':'old' if recovered==old else 'new'})
    # Production store bound cannot fill the 1024-sector journal. Compile the
    # SAME C with a reduced native-only capacity to exercise defensive rollback.
    sources=['model.c','native-fs.c','journal.c','workload.c','snapshot.c']
    target=BUILD/'storage-limit.so'
    subprocess.run(['cc','-shared','-fPIC','-O1','-Wall','-Wextra','-Werror','-DJ_CAPACITY=8','-Ilessons/15','-Ilessons/02',*[str(Path('lessons/15')/name) for name in sources],'-o',str(target)],check=True)
    limited=c.CDLL(str(target.resolve()))
    for name in ('model_load','model_disk','model_run','model_trace_overflow','fs_store','fs_sync','snapshot_read','test_live_handles'):
        function=getattr(limited,name)
        function.argtypes=getattr(fs.lib,name).argtypes
        function.restype=getattr(fs.lib,name).restype
    limited.model_load(baseline)
    assert limited.model_run(0)==0
    assert limited.fs_store(b'publish',b'large'*2000,10000,0)==-17
    assert limited.test_live_handles()==0
    start=limited.model_trace_overflow()
    assert start==0 and limited.fs_sync()==0
    out=c.create_string_buffer(len(baseline))
    limited.model_disk(out)
    assert out.raw==baseline and not limited.model_trace_overflow()
    # Usable block exhaustion, through public real-C API, then rollback on create.
    load(fs,clean)
    large=b'X'*65536
    index=0
    while True:
        result=fs.lib.fs_store(f'fill{index}'.encode(),large,len(large),0)
        fs.check()
        if result<0:
            assert result==-11,result
            break
        index+=1
    before=durable(fs)
    assert fs.lib.fs_store(b'out',large,len(large),0)==-11
    assert fs.lib.fs_sync()==0 and durable(fs)==before
    assert 'out' not in inspect(before)['files']
    (BUILD/'store-results.json').write_text(json.dumps({'status':'PASS','durability':records,'full_files':index,'reduced_journal_rollback':True},indent=2)+'\n')
    print('PASS actual C store/append: binary replacement, busy/epoch/full/limit rollback, crash cuts, uncertain IO recovery')

if __name__=='__main__':
    main()
