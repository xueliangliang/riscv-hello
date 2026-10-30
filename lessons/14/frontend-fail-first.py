#!/usr/bin/env python3
"""Build an exact old archive and run the SAME real-guest class regressions.

Run from repository root. All build/disks/evidence stay in a new scratch archive;
no checkout, reset, old-source edits, shared build directory or source disk writes.
"""
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

OLD = 'dba51e699c49278a4fd00d4fb985dff84ac51c76'
CLASSES = ('lvalue', 'increment', 'decrement', 'initializer')


def main():
    archive = Path(tempfile.mkdtemp(prefix='lesson14-fail-first-', dir=os.environ.get('TMPDIR')))
    sha = subprocess.check_output(['git', 'rev-parse', OLD + '^{commit}'], text=True).strip()
    data = subprocess.check_output(['git', 'archive', sha])
    with tarfile.open(fileobj=io.BytesIO(data)) as bundle:
        bundle.extractall(archive, filter='data')
    regression = Path(__file__).with_name('frontend-test.py')
    shutil.copyfile(regression, archive / 'lessons/14/frontend-test.py')
    old_cc = archive / 'lessons/14/cc.c'
    compiler_hash = hashlib.sha256(old_cc.read_bytes()).hexdigest()
    stages = []
    errors = []
    build = subprocess.run(['make', 'lesson14'], cwd=archive, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=180)
    (archive / 'old-build.log').write_bytes(build.stdout)
    assert build.returncode == 0, (archive, 'old build failed', build.returncode)
    for category in CLASSES:
        child = subprocess.run([sys.executable, 'lessons/14/frontend-test.py', '--class', category],
                               cwd=archive, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, timeout=180)
        (archive / f'old-{category}.log').write_bytes(child.stdout)
        result_path = archive / f'build/lesson14/frontend-{category}-results.json'
        result = json.loads(result_path.read_text())
        records = [record for record in result['records'] if 'output' in record]
        wrongly_accepted = [record for record in records if record['status'] == 0]
        item = {'class': category, 'exit': child.returncode, 'status': result['status'],
                'negative_compiles': result['negative_compiles'],
                'positive_recovery_runs': result['positive_runs'],
                'assertions_failed': len(result['errors']),
                'old_status_zero': len(wrongly_accepted),
                'full_old_changed': sum(record['output'] == 'old' and not record['old_preserved'] for record in records),
                'missing_created': sum(not record['missing_absent'] for record in records),
                'results': str(result_path)}
        # Diagnostic wording alone is NOT fail-first proof. These classes must
        # actually compile forbidden programs, overwrite old bytes and create files.
        if not (child.returncode != 0 and result['status'] == 'FAIL' and
                wrongly_accepted and item['full_old_changed'] and item['missing_created'] and
                result['positive_runs'] == 3):
            errors.append(category)
        stages.append(item)
        print(json.dumps(item), flush=True)
    assert hashlib.sha256(old_cc.read_bytes()).hexdigest() == compiler_hash
    receipt = {'status': 'FAIL' if errors else 'PASS', 'old_sha': sha,
               'old_cc_sha256': compiler_hash,
               'regression_sha256': hashlib.sha256(regression.read_bytes()).hexdigest(),
               'archive': str(archive), 'build_exit': build.returncode,
               'classes': stages, 'unproven_classes': errors}
    (archive / 'fail-first-results.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print('Receipt:', archive / 'fail-first-results.json')
    assert not errors, ('old compiler did not expose all defects', errors)
    print('PASS fail-first: four separately executed real U compiler defect classes fail new assertions')


if __name__ == '__main__':
    main()
