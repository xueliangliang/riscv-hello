#!/usr/bin/env python3
"""Exercise actual failed children and stale-PASS attacks, then restore gates."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from debugger import DebuggerSession
from gate import stage, children_of
import signal
BUILD=Path('build/lesson15')
BUILD.mkdir(parents=True,exist_ok=True)
EVIDENCE=Path(tempfile.mkdtemp(prefix='lesson15-evidence-',dir=os.environ.get('TMPDIR')))

with tempfile.TemporaryDirectory(prefix='lesson15-evidence-',dir=os.environ.get('TMPDIR')) as temp:
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
def run(name,target,env=None,success=True,timeout=180):
    settings=os.environ.copy()
    settings.update(env or {})
    argv=['make','--no-print-directory',target]
    if env and 'CC' in env:
        argv.append('CC='+env['CC'])
    child=subprocess.Popen(argv,env=settings,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    try:
        output,_=child.communicate(timeout=timeout)
    except BaseException:
        for pid in sorted(children_of(child.pid),reverse=True):
            try:
                os.kill(pid,signal.SIGKILL)
            except ProcessLookupError:
                pass
        output,_=child.communicate()
        (EVIDENCE/(name+'.log')).write_bytes(output)
        assert child.poll() is not None
        raise
    # Keep failure evidence outside build: the next outer gate invalidates it.
    (EVIDENCE/(name+'.log')).write_bytes(output)
    if (BUILD/'gdb-loader.log').exists():
        (EVIDENCE/(name+'-debugger.log')).write_bytes((BUILD/'gdb-loader.log').read_bytes())
    assert (child.returncode==0)==success,(name,child.returncode,output[-3000:])

# Timeout the actual recursive make entry, retaining partial binary output and
# killing/draining/reaping its real child tree before trying another gate.
try:
    run('recursive-make-timeout','test-lesson15',timeout=.2)
except subprocess.TimeoutExpired:
    pass
else:
    raise AssertionError('recursive make timeout accepted')
assert (EVIDENCE/'recursive-make-timeout.log').read_bytes()
(BUILD/'gdb-loader.log').write_bytes(b'STALE PASS GDB\n')
(BUILD/'results.json').write_text('{"status":"PASS"}')
run('wrong-cc','test-lesson15',{'CC':'/bin/false'},False)
assert not (BUILD/'results.json').exists()
assert (BUILD/'gdb-loader.log').read_bytes()==b''
assert b'/bin/false' in (BUILD/'gate-toolchain.log').read_bytes()
(BUILD/'results.json').write_text('{"status":"PASS"}')
run('no-output-cc','test-lesson15',{'CC':'/bin/true'},False)
assert not (BUILD/'results.json').exists()
assert (BUILD/'gdb-loader.log').read_bytes()==b''
(BUILD/'gdb-loader.log').write_bytes(b'STALE PASS GDB\n')
run('early-setup','test-lesson15-gdb',{'GDB':'/no/such/lesson15-debugger'},False)
assert b'STALE' not in (BUILD/'gdb-loader.log').read_bytes()
assert b'PASS GDB' not in (BUILD/'gdb-loader.log').read_bytes()
run('real-before-fake','test-lesson15-gdb')
assert b'PASS GDB:' in (BUILD/'gdb-loader.log').read_bytes()
run('fake-true','test-lesson15-gdb',{'GDB':'/bin/true'},False)
assert b'PASS GDB:' not in (BUILD/'gdb-loader.log').read_bytes()
# The expanded lesson15 suite has independently measured ~220 seconds of
# bounded real guest work (not the old integer-only lesson14 suite). Only this
# outer aggregate budget is360s; individual stage and debugger bounds stay fixed.
run('restored-runtime','test-lesson15',timeout=360)
run('restored-real-gdb','test-lesson15-gdb')
assert b'PASS GDB:' in (BUILD/'gdb-loader.log').read_bytes()
(BUILD/'evidence-results.json').write_text('{"status":"PASS","wrong_CC":true,"early_setup":true,"fake_GDB":true,"partial_timeout_and_reap":true,"restored_real_GDB":true}\n')
print('Evidence directory:', EVIDENCE)
print('PASS evidence attacks: real timeout/nonzero/early children reaped, build/setup stale PASS removed, fake GDB rejected, real gates restored')
