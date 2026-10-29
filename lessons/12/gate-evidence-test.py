#!/usr/bin/env python3
"""Replay real prior success evidence, then fail the outer gate before tests."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main():
    build = Path('build/lesson12')
    result = build / 'gate-evidence-results.json'
    result.unlink(missing_ok=True)
    for path in build.glob('evidence-*.log'):
        path.unlink()
    evidence = {p.name: p.read_bytes() for pattern in ('*.log', '*.json')
                for p in build.glob(pattern)}
    assert json.loads(evidence['results.json'])['status'] == 'PASS'
    assert any(b'PASS' in data for data in evidence.values())
    outcomes = []
    with tempfile.TemporaryDirectory(prefix='lesson12-gate-evidence-', dir=os.environ.get('TMPDIR')) as directory:
        root = Path(directory)
        shutil.copyfile('Makefile', root / 'Makefile')
        shutil.copytree('lessons', root / 'lessons', ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copytree('tools', root / 'tools')
        target = root / 'build/lesson12'
        target.mkdir(parents=True)
        for name, argv, overrides in [
            ('bad-CC', ['make', 'test-lesson12', 'CC=/no-such-lesson12-compiler'], {}),
            ('early-setup', [sys.executable, 'lessons/12/gate.py'],
             {'MAKE': '/no-such-lesson12-make'})]:
            for filename, data in evidence.items():
                (target / filename).write_bytes(data)
            environment = os.environ.copy()
            environment.update(overrides)
            child = subprocess.run(argv, cwd=root, env=environment, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, timeout=30)
            assert child.returncode != 0, (name, child.stdout)
            assert not (target / 'results.json').exists(), name + ' kept prior aggregate PASS'
            for pattern in ('*.json', '*.log'):
                for path in target.glob(pattern):
                    assert b'PASS' not in path.read_bytes(), (name, path)
            (build / ('evidence-' + name + '.log')).write_bytes(child.stdout)
            outcomes.append({'failure': name, 'exit': child.returncode,
                             'all_prior_JSON_and_logs_invalidated': True})
        saved = root / 'state/lesson12/disk.img'
        saved.parent.mkdir(parents=True)
        shutil.copyfile(build / 'disk.img', saved)
        digest = hashlib.sha256(saved.read_bytes()).hexdigest()
        clean = subprocess.run(['make', 'clean'], cwd=root, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, timeout=30)
        assert clean.returncode == 0, clean.stdout
        assert hashlib.sha256(saved.read_bytes()).hexdigest() == digest
    (build / 'gate-evidence-results.json').write_text(json.dumps(
        {'status': 'PASS', 'cases': outcomes, 'clean_preserves_saved_disk': True}, indent=2) + '\n')
    print('PASS outer evidence gate: real old success -> bad CC and early setup failure; no stale PASS in any JSON/log; disposable clean preserves saved disk')


if __name__ == '__main__':
    main()
