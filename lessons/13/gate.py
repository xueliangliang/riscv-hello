#!/usr/bin/env python3
"""Invalidate all evidence before build/setup; retain failed stage output."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
BUILD=Path('build/lesson13')

def children_of(parent):
    parents={}
    for entry in Path('/proc').iterdir():
        if entry.name.isdecimal():
            try:
                parents[int(entry.name)]=int((entry/'stat').read_text().rsplit(')',1)[1].split()[1])
            except (OSError,ValueError,IndexError):
                pass
    children={parent}
    while True:
        expanded=children|{pid for pid,ppid in parents.items() if ppid in children}
        if expanded==children:
            return children
        children=expanded

def stage(name,argv,timeout=180):
    child=subprocess.Popen(argv,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    try:
        output,_=child.communicate(timeout=timeout)
    except BaseException:
        for pid in sorted(children_of(child.pid),reverse=True):
            try:
                os.kill(pid,signal.SIGKILL)
            except ProcessLookupError:
                pass
        output,_=child.communicate()
        (BUILD/(name+'.log')).write_bytes(output)
        raise
    (BUILD/(name+'.log')).write_bytes(output)
    sys.stdout.buffer.write(output)
    sys.stdout.buffer.flush()
    assert child.returncode==0,(name,child.returncode)
    return {'name':name,'argv':argv,'exit':child.returncode}

def main():
    BUILD.mkdir(parents=True,exist_ok=True)
    # Clear old success before recursive make, imports of project modules,
    # native compilation, QEMU start, GDB start, or any test setup.
    for pattern in ('*.log','*.json'):
        for path in BUILD.glob(pattern):
            path.unlink()
    (BUILD/'gdb-loader.log').write_bytes(b'')
    cc=os.environ.get('CC','riscv64-linux-gnu-gcc')
    commands=[('gate-build',['make','--no-print-directory','-B','lesson13',
                             'build/lesson13/math-alt.dll','build/lesson13/io_test.exec',f'CC={cc}']),
              ('gate-parsers',[sys.executable,'lessons/13/vectors.py']),
              ('gate-loader-native',[sys.executable,'lessons/13/loader-test.py']),
              ('gate-binary',[sys.executable,'lessons/13/binary-test.py']),
              ('gate-runtime',[sys.executable,'lessons/13/test.py']),
              ('gate-IO-U',[sys.executable,'lessons/13/io-test.py']),
              ('gate-launcher',[sys.executable,'lessons/13/launcher-test.py'])]
    stages=[stage(name,argv) for name,argv in commands]
    result=json.loads((BUILD/'runtime-results.json').read_text())
    assert result['status']=='PASS' and len(result['cold'])==2
    (BUILD/'results.json').write_text(json.dumps({'status':'PASS','stages':stages,'runtime':result},indent=2)+'\n')
    print('PASS complete lesson13 gate: independent native, real U execution, raw cold files, rebinding and launcher')

if __name__=='__main__':
    main()
