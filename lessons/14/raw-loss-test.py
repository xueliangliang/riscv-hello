#!/usr/bin/env python3
"""Real RX overflow: baseline predates queued command, drain and editor recovery."""
from pathlib import Path
import os
import re
import shutil
import tempfile
from guest import Guest
from decode import decode

with tempfile.TemporaryDirectory(prefix='lesson14-loss-',dir=os.environ.get('TMPDIR')) as temporary:
    disk=Path(temporary)/'disk.img'
    shutil.copyfile('build/lesson14/disk.img',disk)
    guest=Guest('raw-loss.log',str(disk))
    try:
        guest.until('14> ')
        guest.send('sleep 500\r')
        guest.until('sleep pid=')
        # Controller cannot consume input for five seconds, but hart0 RX IRQs
        # keep enqueuing. This burst is intentionally beyond advertised capacity.
        guest.send(b'fappend lost <<LOSS\r\n'+b'x'*60000+b'\nshutdown\nLOSS\n')
        guest.until('raw: collecting',10)
        guest.read(0.2)
        guest.send('\nLOSS\n')
        guest.until('raw: rejected; drained; unchanged',10)
        guest.read(0.1)
        output=guest.cmd('stats')
        match=re.search(r'rx-ring pid=0x[0-9a-f]+ value=0x([0-9a-f]+)',output)
        assert match and int(match[1],16)>0,output
        assert 'lost' not in decode(disk)
        guest.cmd('echo ad\x1b[Db','echo: abd')
        # A sticky boot baseline also rejects a later seemingly valid body;
        # acknowledging only its later baseline would hide earlier burst loss.
        guest.send('fappend lost <<LOSS\nvalid\nLOSS\n')
        guest.until('raw: rejected; drained; unchanged')
        guest.read(0.1)
        assert 'lost' not in decode(disk)
        guest.cmd('echo recovered','echo: recovered')
        guest.shutdown()
    finally:
        guest.close()
    assert 'lost' not in decode(disk)
print('PASS real RX drops before raw entry rejected, exact delimiter drain, sticky loss, editor and shutdown recovery')
