#!/usr/bin/env python3
"""Outermost acceptance gate: invalidate evidence BEFORE any recursive build."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

BUILD = Path('build/lesson12')


def children_of(parent):
    parents = {}
    for entry in Path('/proc').iterdir():
        if entry.name.isdecimal():
            try:
                stat = (entry / 'stat').read_text().rsplit(')', 1)[1].split()
                parents[int(entry.name)] = int(stat[1])
            except (OSError, ValueError, IndexError):
                pass
    children = {parent}
    while True:
        expanded = children | {pid for pid, ppid in parents.items() if ppid in children}
        if expanded == children:
            return children
        children = expanded


def stage(name, argv):
    child = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        output, _ = child.communicate(timeout=600)
    except BaseException:
        # Kill even a PTY guest that created its own session. Drain/reap the
        # direct child and retain all partial binary stdout/stderr.
        for pid in sorted(children_of(child.pid), reverse=True):
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        output, _ = child.communicate()
        (BUILD / (name + '.log')).write_bytes(output)
        raise
    (BUILD / (name + '.log')).write_bytes(output)
    sys.stdout.buffer.write(output)
    sys.stdout.buffer.flush()
    assert child.returncode == 0, (name, child.returncode)
    return {'name': name, 'argv': argv, 'exit': child.returncode}


def main():
    BUILD.mkdir(parents=True, exist_ok=True)
    # Neither a bad CC nor an import/setup failure may preserve yesterday's
    # success. Clean only this lesson's generated evidence, not earlier gates.
    for pattern in ('*.log', '*.json'):
        for path in BUILD.glob(pattern):
            path.unlink()
    stages = []
    commands = [
        ('gate-build', [os.environ.get('MAKE', 'make'), '--no-print-directory', 'lesson12', 'build/lesson12/disk-no-flush.img']),
        ('gate-model', [sys.executable, 'lessons/12/model-test.py']),
        ('gate-protocol-mutation', [sys.executable, 'lessons/12/protocol-mutation-test.py']),
        ('gate-runtime', [sys.executable, 'lessons/12/test.py']),
        ('gate-epoch', [sys.executable, 'lessons/12/epoch-test.py']),
        ('gate-crash', [sys.executable, 'lessons/12/crash-test.py'])]
    for name, argv in commands:
        stages.append(stage(name, argv))
    model = json.loads((BUILD / 'model-results.json').read_text())
    crash = json.loads((BUILD / 'crash-results.json').read_text())
    assert model['case_count'] == len(model['cases'])
    assert crash['case_count'] == len(crash['cases'])
    result = {'status': 'PASS', 'stages': stages,
              'native_crash_error_cases': model['case_count'],
              'native_recovery_error_cases': model['recovery_error_count'],
              'QEMU_crash_cases': crash['case_count'],
              'QEMU_dualhart_cold_replay': crash['dualhart_U_shell_cold_replay']}
    (BUILD / 'results.json').write_text(json.dumps(result, indent=2) + '\n')
    print('PASS lesson12 complete gate: actual-C model, protocol mutation, U runtime, epoch boundary, QEMU crashes and dual-hart cold replay')


if __name__ == '__main__':
    main()
