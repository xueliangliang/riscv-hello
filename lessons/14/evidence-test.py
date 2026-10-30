#!/usr/bin/env python3
"""Exercise actual failed children and stale-PASS attacks, then restore gates."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from debugger import DebuggerSession
from gate import stage
BUILD=Path('build/lesson14')
EVIDENCE=Path(os.environ.get('TMPDIR','build/lesson14'))/'lesson14-evidence'
EVIDENCE.mkdir(parents=True,exist_ok=True)

with tempfile.TemporaryDirectory(prefix='lesson14-evidence-',dir=os.environ.get('TMPDIR')) as temp:
    directory=Path(temp)
    log=directory/'debugger.log'
    for status in (0,7):
        log.write_bytes(b'STALE PASS GDB\n')
        with DebuggerSession(log) as session:
            session.start([sys.executable,'-c',f"import os;os.write(1,b'out\\n');os.write(2,b'err\\xff\\n');raise SystemExit({status})"])
            assert session.collect()==b'out\nerr\xff\n'
            assert session.process.returncode==status
        assert log.read_bytes()==b'out\nerr\xff\n'
        (EVIDENCE/f'child-exit-{status}.log').write_bytes(log.read_bytes())
    try:
        with DebuggerSession(log) as session:
            session.start([sys.executable,'-c',"import os,time;os.write(1,b'partial-out\\n');os.write(2,b'partial-err\\xff\\n');time.sleep(30)"])
            session.collect(timeout=.2)
    except subprocess.TimeoutExpired:
        pass
    else:
        raise AssertionError('debugger timeout accepted')
    assert session.process.poll() is not None
    data=log.read_bytes()
    assert b'partial-out\n' in data and b'partial-err\xff\n' in data and b'TimeoutExpired' in data
    (EVIDENCE/'partial-timeout.log').write_bytes(data)
    marker=directory/'ready'
    try:
        with DebuggerSession(log) as session:
            session.start([sys.executable,'-c',f"import os,time;from pathlib import Path;os.write(1,b'early-output\\n');Path({str(marker)!r}).touch();time.sleep(30)"])
            end=time.monotonic()+3
            while not marker.exists():
                assert time.monotonic()<end
                time.sleep(.01)
            raise AssertionError('guest setup failed before collect')
    except AssertionError as error:
        assert str(error)=='guest setup failed before collect'
    assert b'early-output\n' in log.read_bytes() and session.process.poll() is not None
    (EVIDENCE/'early-before-collect.log').write_bytes(log.read_bytes())
    try:
        stage('gate-timeout-regression',[sys.executable,'-c',"import os,time;os.write(1,b'outer-partial\\n');time.sleep(30)"],timeout=.2)
    except subprocess.TimeoutExpired:
        pass
    else:
        raise AssertionError('outer gate timeout accepted')
    assert (BUILD/'gate-timeout-regression.log').read_bytes()==b'outer-partial\n'
    (EVIDENCE/'outer-partial-timeout.log').write_bytes((BUILD/'gate-timeout-regression.log').read_bytes())

# These are actual public make targets, not a mocked fresh-log function.
def run(name,target,env=None,success=True):
    settings=os.environ.copy()
    settings.update(env or {})
    argv=['make','--no-print-directory',target]
    if env and 'CC' in env:
        argv.append('CC='+env['CC'])
    child=subprocess.run(argv,env=settings,
                         stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=180)
    # Keep failure evidence outside build: the next outer gate invalidates it.
    (EVIDENCE/(name+'.log')).write_bytes(child.stdout)
    if (BUILD/'gdb-loader.log').exists():
        (EVIDENCE/(name+'-debugger.log')).write_bytes((BUILD/'gdb-loader.log').read_bytes())
    assert (child.returncode==0)==success,(name,child.returncode,child.stdout[-3000:])

(BUILD/'gdb-loader.log').write_bytes(b'STALE PASS GDB\n')
(BUILD/'results.json').write_text('{"status":"PASS"}')
run('wrong-cc','test-lesson14',{'CC':'/bin/false'},False)
assert not (BUILD/'results.json').exists()
assert (BUILD/'gdb-loader.log').read_bytes()==b''
assert b'/bin/false' in (BUILD/'gate-build.log').read_bytes()
(BUILD/'gdb-loader.log').write_bytes(b'STALE PASS GDB\n')
run('early-setup','test-lesson14-gdb',{'GDB':'/no/such/lesson14-debugger'},False)
assert b'STALE' not in (BUILD/'gdb-loader.log').read_bytes()
assert b'PASS GDB' not in (BUILD/'gdb-loader.log').read_bytes()
run('real-before-fake','test-lesson14-gdb')
assert b'PASS GDB:' in (BUILD/'gdb-loader.log').read_bytes()
run('fake-true','test-lesson14-gdb',{'GDB':'/bin/true'},False)
assert b'PASS GDB:' not in (BUILD/'gdb-loader.log').read_bytes()
run('restored-runtime','test-lesson14')
run('restored-real-gdb','test-lesson14-gdb')
assert b'PASS GDB:' in (BUILD/'gdb-loader.log').read_bytes()
(BUILD/'evidence-results.json').write_text('{"status":"PASS","wrong_CC":true,"early_setup":true,"fake_GDB":true,"partial_timeout_and_reap":true,"restored_real_GDB":true}\n')
print('PASS evidence attacks: real timeout/nonzero/early children reaped, build/setup stale PASS removed, fake GDB rejected, real gates restored')
