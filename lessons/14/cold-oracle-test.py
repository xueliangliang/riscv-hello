"""Actual guest fail-first: an overwrite must not hide wrong cold content."""
import os
from pathlib import Path
import shutil
import tempfile
from native import Native
from test import start,verify_cold_saved,rejected

with tempfile.TemporaryDirectory(prefix='lesson14-cold-oracle-',dir=os.environ.get('TMPDIR')) as temp:
    for old_order in (True,False):
        disk=Path(temp)/('old.img' if old_order else 'fixed.img')
        shutil.copyfile('build/lesson14/disk.img',disk)
        fs=Native(disk)
        fs.put('saved',b'WRONG-PERSISTED-CONTENT')
        fs.save(disk)
        g=start('cold-oracle-old.log' if old_order else 'cold-oracle-fixed.log',disk)
        try:
            if old_order:
                # The pre-fix gate did exactly this: its own write masked loss
                # or corruption of the previous boot's saved file.
                g.cmd('fwrite saved cold-loader-journal','fwrite target=0 result=19')
                verify_cold_saved(g)
            else:
                rejected(lambda:verify_cold_saved(g))
                assert b'WRONG-PERSISTED-CONTENT' in g.all
            g.shutdown()
        finally:
            g.close()
print('PASS actual cold-content oracle regression: old overwrite-first admits corruption; new read-first rejects it')
