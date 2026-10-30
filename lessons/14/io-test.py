"""Real blkdebug IOERR after mount, through the actual U snapshot syscall."""
import os
from pathlib import Path
import shutil
import tempfile
from native import Native
from decode import decode
from guest import Guest
from run import command

with tempfile.TemporaryDirectory(prefix='lesson14-io-',dir=os.environ.get('TMPDIR')) as temp:
    directory=Path(temp)
    disk=directory/'disk.img'
    shutil.copyfile('build/lesson14/disk.img',disk)
    fs=Native(disk)
    fs.put('io_test',Path('build/lesson14/io_test.exec').read_bytes())
    fs.save(disk)
    files=decode(disk)
    sector=2048+(files['math.dll']['head']-1)*8
    config=directory/'io.conf'
    # Mount validates all files. Do not fault those reads: the first actual
    # shell journal WRITE arms state2 AFTER mount; only DLL payload reads fail.
    config.write_text('[set-state]\nevent = "write_aio"\nstate = "1"\nnew_state = "2"\n'
                      '[inject-error]\nevent = "read_aio"\nstate = "2"\nerrno = "5"\nonce = "on"\n'
                      f'sector = "{sector}"\n')
    opts=command(f'blkdebug:{config}:{disk}',device_extra=',werror=report,rerror=report')
    g=Guest('io-U-snapshot.log',str(disk),True,options=opts)
    try:
        g.until('13> ')
        g.cmd('fwrite arm ready','fwrite target=0 result=5')
        g.cmd('exec io_test','exec target=0 result=17')
        g.cmd('wait 17','wait target=17 result=43')
        assert b'CHECK actual U IOERR snapshot unchanged and module inactive' in g.all
        assert b'request-type=0x0000000000000000 status=0x0000000000000001' in g.all
        g.cmd('exec math_test','exec target=0 result=-14')
        g.shutdown(failure=True)
    finally:
        g.close()
    after=decode(disk)
    assert after['math.dll']['content']==files['math.dll']['content']
    assert after['math_test']['content']==files['math_test']['content']
    assert after['arm']['content']==b'ready'
print('PASS actual QEMU IOERR status1: U failed snapshot unchanged, module inactive, reap43, sticky failure and shutdown failure')
