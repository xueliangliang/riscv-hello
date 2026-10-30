#!/usr/bin/env python3
"""Invalidate all evidence before build/setup; retain failed stage output."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
BUILD=Path('build/lesson15')

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
    started=time.monotonic()
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
    return {'name':name,'argv':argv,'exit':child.returncode,'elapsed_seconds':time.monotonic()-started}

def main():
    BUILD.mkdir(parents=True,exist_ok=True)
    # Clear old success before recursive make, imports of project modules,
    # native compilation, QEMU start, GDB start, or any test setup.
    for pattern in ('*.log','*.json'):
        for path in BUILD.glob(pattern):
            path.unlink()
    (BUILD/'gdb-loader.log').write_bytes(b'')
    cc=os.environ.get('CC','riscv64-linux-gnu-gcc')
    commands=[('gate-toolchain',[sys.executable,'lessons/15/toolchain-test.py',cc]),
              ('gate-build',['make','--no-print-directory','-B','lesson15', f'CC={cc}']),
              ('gate-resources',[sys.executable,'lessons/15/resource-test.py']),
              ('gate-helpers',[sys.executable,'lessons/15/helper-test.py']),
              ('gate-legacy-ABI2',[sys.executable,'lessons/15/legacy-test.py']),
              ('gate-formats',[sys.executable,'lessons/15/vectors.py']),
              ('gate-legacy-module',[sys.executable,'lessons/15/loader-test.py']),
              ('gate-storage',[sys.executable,'lessons/15/store-test.py']),
              ('gate-runtime',[sys.executable,'lessons/15/compiler-test.py']),
              ('gate-floats',[sys.executable,'lessons/15/float-test.py']),
              ('gate-template',[sys.executable,'lessons/15/template-test.py']),
              ('gate-module-negatives',[sys.executable,'lessons/15/module-negative-test.py']),
              ('gate-frontend',[sys.executable,'lessons/15/frontend-test.py']),
              ('gate-IO-U',[sys.executable,'lessons/15/compiler-io-test.py']),
              ('gate-dll-IO',[sys.executable,'lessons/15/dll-io-test.py']),
              ('gate-raw-loss',[sys.executable,'lessons/15/raw-loss-test.py']),
              ('gate-mutants',[sys.executable,'lessons/15/mutant-test.py']),
              ('gate-launcher',[sys.executable,'lessons/15/launcher-test.py'])]
    stages=[stage(name,argv) for name,argv in commands]
    result=json.loads((BUILD/'runtime-results.json').read_text())
    assert result['status']=='PASS' and result['cold']['status']==23
    floating=json.loads((BUILD/'float-results.json').read_text())
    assert floating['status']=='PASS'
    frontend=json.loads((BUILD/'frontend-all-results.json').read_text())
    assert frontend['status']=='PASS' and not frontend['errors']
    (BUILD/'results.json').write_text(json.dumps({'status':'PASS','stages':stages,'runtime':result,'frontend':frontend,'floating':floating},indent=2)+'\n')
    print('PASS complete lesson15 gate: real guest compiler/native/cold closure, atomic storage, IO, raw loss, mutations and launcher')

if __name__=='__main__':
    main()
