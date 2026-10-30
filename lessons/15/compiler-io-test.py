#!/usr/bin/env python3
"""Real virtio READ/WRITE/FLUSH IOERR through guest compiler syscalls."""
from pathlib import Path
import os
import re
import shutil
import tempfile
from native import Native
from decode import decode
from guest import Guest
from run import command

with tempfile.TemporaryDirectory(prefix='lesson15-io-',dir=os.environ.get('TMPDIR')) as temporary:
    directory=Path(temporary)
    for kind in (0,1,4):
        disk=directory/f'disk{kind}.img'
        shutil.copyfile('build/lesson15/disk.img',disk)
        fs=Native(disk)
        source=b'int main() { print_int(123456); return 19; }\n'
        fs.put('io.c',source)
        fs.put('saved',b'OLD\x00OUTPUT\xff')
        fs.save(disk)
        files=decode(disk)
        sector=2048+(files['io.c']['head']-1)*8
        config=directory/f'io{kind}.conf'
        if kind==0:
            inject=f'event = "read_aio"\nsector = "{sector}"\n'
        elif kind==1:
            inject='event = "write_aio"\nsector = "12306"\n'
        else:
            inject='event = "flush_to_disk"\n'
        config.write_text('[set-state]\nevent = "write_aio"\nstate = "1"\nnew_state = "2"\n'
                          '[inject-error]\nstate = "2"\nerrno = "5"\nonce = "on"\n'+inject)
        guest=Guest(f'io-compiler-{kind}.log',str(disk),True,
                    options=command(f'blkdebug:{config}:{disk}',device_extra=',werror=report,rerror=report'))
        try:
            guest.until('15> ')
            if kind==0:
                guest.cmd('fwrite arm ready','fwrite target=0 result=5')
            output=guest.cmd('./cc io.c saved')
            match=re.search(r'exec target=0 result=(\d+)',output)
            assert match,output
            pid=int(match[1])
            status=3 if kind==0 else 4
            guest.cmd(f'wait {pid}',f'wait target={pid} result={status}')
            assert f'request-type=0x{kind:016x} status=0x0000000000000001'.encode() in guest.all
            assert b'cc: published' not in guest.all
            guest.shutdown(failure=True)
        finally:
            guest.close()
        after=decode(disk)
        assert after['saved']['content']==files['saved']['content']
        assert after['io.c']['content']==source
        # Recovery gets a NEW transport/FS instance; first reads precede writes.
        guest=Guest(f'io-compiler-{kind}-recovery.log',str(disk))
        try:
            guest.until('15> ')
            guest.cmd('cat io.c','print_int(123456)')
            start=len(guest.all)
            guest.cmd('cat saved','cat target=0 result=0')
            assert files['saved']['content'] in guest.all[start:]
            guest.shutdown()
        finally:
            guest.close()
        assert decode(disk)['saved']['content']==files['saved']['content']
print('PASS actual compiler READ/WRITE/FLUSH IOERR status1, exact exit/reap, sticky poison, cold old-output recovery')
