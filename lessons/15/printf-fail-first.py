#!/usr/bin/env python3
"""Prove the identical printf regression fails the unmodified exact old tree."""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time

OLD = 'ad8f8241c5e5e5a36021791c75782aed4b10ef81'


def main():
    archive = Path(tempfile.mkdtemp(prefix='lesson15-printf-old-', dir=os.environ.get('TMPDIR')))
    raw = subprocess.check_output(['git', 'archive', OLD])
    with tarfile.open(fileobj=io.BytesIO(raw)) as bundle:
        bundle.extractall(archive, filter='data')
    regression = Path(__file__).with_name('printf-test.py')
    shutil.copyfile(regression, archive / 'lessons/15/printf-test.py')
    compiler = archive / 'lessons/15/cc.c'
    compiler_hash = hashlib.sha256(compiler.read_bytes()).hexdigest()
    stages = []
    for name, argv in [('build', ['make', 'lesson15']),
                       ('regression', [sys.executable, 'lessons/15/printf-test.py'])]:
        start = time.monotonic()
        process = subprocess.run(argv, cwd=archive, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, timeout=180)
        log = archive / (name + '.log')
        log.write_bytes(process.stdout)
        stages.append({'command': argv, 'exit': process.returncode,
                       'seconds': time.monotonic() - start, 'log': str(log)})
        if name == 'build':
            assert process.returncode == 0, stages
    result_path = archive / 'build/lesson15/printf-results.json'
    result = json.loads(result_path.read_text())
    order = next(record for record in result['records'] if record.get('name') == 'order')
    assert stages[-1]['exit'] != 0 and result['status'] == 'FAIL'
    assert order['compiler']['status'] == order['execution']['status'] == 0
    assert order['observed'] == 'A11\n0B22\n0\n'
    assert order['expected'] == '11\n22\nA0B0\n'
    assert order['source_preserved']
    assert hashlib.sha256(compiler.read_bytes()).hexdigest() == compiler_hash
    receipt = {'status': 'PASS', 'old_sha': OLD, 'archive': str(archive),
               'old_cc_sha256': compiler_hash, 'stages': stages,
               'regression_sha256': hashlib.sha256(regression.read_bytes()).hexdigest(),
               'results': str(result_path), 'order': order}
    destination = Path('build/lesson15/printf-fail-first-results.json')
    destination.write_text(json.dumps(receipt, indent=2) + '\n')
    print('PASS actual fail-first: unchanged old compiler/native both exit0, wrong full output; receipt:', destination.resolve())


if __name__ == '__main__':
    main()
