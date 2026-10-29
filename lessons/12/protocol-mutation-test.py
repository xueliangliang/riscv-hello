#!/usr/bin/env python3
"""Prove a protocol violation is caught by running actual mutated C in isolation."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main():
    result = Path('build/lesson12/protocol-mutation.json')
    result.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix='lesson12-protocol-', dir=os.environ.get('TMPDIR')) as directory:
        root = Path(directory)
        lesson = root / 'lessons/12'
        shutil.copytree('lessons/12', lesson, ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copytree('lessons/02', root / 'lessons/02')
        (root / 'build/lesson12').mkdir(parents=True)
        shutil.copyfile('build/lesson12/disk.img', root / 'build/lesson12/disk.img')
        path = lesson / 'journal.c'
        text = path.read_text()
        original = '''    journal_hook(3, 0);
    if (raw(4, 0, 0)) {
        return J_IO;
    }
    journal_hook(4, 0);'''
        mutation = '''    journal_hook(3, 0);
    /* Deliberately broken: checkpoint without durable commit. */
    journal_hook(4, 0);'''
        assert text.count(original) == 1
        path.write_text(text.replace(original, mutation))
        completed = subprocess.run([sys.executable, 'lessons/12/model-test.py'], cwd=root,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=90)
        Path('build/lesson12/protocol-mutation.log').write_bytes(completed.stdout)
        assert completed.returncode != 0, 'oracle accepted missing commit FLUSH'
        assert b'committed journal header missing' in completed.stdout, completed.stdout
        path.write_text(text)
        regressions = []
        for filename, before, after, rejection in [
            ('model.c', '        trace_overflow = 1;', '        trace_overflow = 0;',
             'native call accepted saturated trace'),
            ('model-test.py', "'model_trace': (C.c_uint,", "'model_trace': (C.c_int,",
             'unsigned trace ABI mismatch')]:
            target = lesson / filename
            good = target.read_text()
            assert good.count(before) == 1
            target.write_text(good.replace(before, after))
            broken = subprocess.run([sys.executable, 'lessons/12/model-test.py'], cwd=root,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=90)
            Path('build/lesson12/mutation-' + filename + '.log').write_bytes(broken.stdout)
            assert broken.returncode != 0 and rejection.encode() in broken.stdout, broken.stdout
            regressions.append({'mutation': filename, 'child_exit': broken.returncode,
                                'oracle_rejection': rejection})
            target.write_text(good)
        reset_regressions = []
        target = lesson / 'block.c'
        good = target.read_text()
        for name, before, after, rejection in [
            ('ungated-init', '    poisoned = 1;\n    device_registers = NULL;',
             '    device_registers = NULL;', 'poisoned == 1'),
            ('early-release', '    write_register(VIRTIO_MMIO_STATUS, DEVICE_STATUS_ACKNOWLEDGE);',
             '    poisoned = 0;\n    write_register(VIRTIO_MMIO_STATUS, DEVICE_STATUS_ACKNOWLEDGE);',
             'poisoned == 1'),
            ('pre-reset-ring-reuse', '    poisoned = 1;\n    device_registers = NULL;',
             '    poisoned = 1;\n    available_ring.index = 0;\n    device_registers = NULL;',
             'saved_available')]:
            assert good.count(before) == 1
            target.write_text(good.replace(before, after))
            broken = subprocess.run([sys.executable, 'lessons/12/block-reset-test.py'], cwd=root,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30)
            Path('build/lesson12/mutation-reset-' + name + '.log').write_bytes(broken.stdout)
            assert broken.returncode != 0 and rejection.encode() in broken.stdout, broken.stdout
            reset_regressions.append({'mutation': name, 'child_exit': broken.returncode,
                                      'oracle_rejection': rejection})
            target.write_text(good)
    result.write_text(json.dumps({'status': 'PASS', 'mutation': 'remove actual-C commit FLUSH',
                                  'child_exit': completed.returncode, 'trace_regressions': regressions,
                                  'reset_regressions': reset_regressions,
                                  'oracle_rejection': 'committed journal header missing'}, indent=2) + '\n')
    print('PASS load-bearing oracles: missing commit FLUSH, trace overflow, signed FFI and three unsafe reset/DMA mutations rejected in throwaway copies')


if __name__ == '__main__':
    main()
