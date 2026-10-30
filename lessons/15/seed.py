"""Seed only a NEW generated lesson15 fixture, through the real C FS."""
from pathlib import Path
import os
import sys
import tempfile
from format import format_image
from native import Native

if __name__=='__main__':
    kernel,user,output=sys.argv[1:]
    target=Path(output)
    fd,staging=tempfile.mkstemp(prefix='.seed-',dir=target.parent)
    os.close(fd)
    try:
        format_image(kernel,user,staging)
        fs=Native(staging)
        fs.put('math_test',Path('build/lesson15/math_test.exec').read_bytes())
        fs.put('math.dll',Path('build/lesson15/math.dll').read_bytes())
        fs.put('cc',Path('build/lesson15/cc.exec').read_bytes())
        fs.put('c_runtime',Path('build/lesson15/c_runtime').read_bytes())
        fs.save(staging)
        os.replace(staging,target)
    finally:
        if os.path.exists(staging):
            os.unlink(staging)
