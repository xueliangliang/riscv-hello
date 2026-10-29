#!/usr/bin/env python3
"""Real RISC-V journal/fs crash matrix followed by real two-hart U shell replay.
Finisher exits are deterministic software interruptions, not device power cuts.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
from decode import inspect
from run import command
from test import Guest, assert_cat

spec = importlib.util.spec_from_file_location('model_test', Path(__file__).with_name('model-test.py'))
model = importlib.util.module_from_spec(spec)
spec.loader.exec_module(model)
BUILD = Path('build/lesson12')


def build_harness():
    compiler = os.environ.get('CC', 'riscv64-linux-gnu-gcc')
    flags = ['-march=rv64imac_zicsr_zifencei', '-mabi=lp64', '-mcmodel=medany',
             '-msmall-data-limit=0', '-O1', '-g', '-ffreestanding', '-fno-builtin',
             '-fno-pic', '-fno-stack-protector', '-fno-unwind-tables',
             '-fno-asynchronous-unwind-tables', '-Wall', '-Wextra', '-Werror',
             '-Ilessons/02', '-Ilessons/12', '-nostdlib', '-static', '-Wl,--build-id=none']
    subprocess.run([compiler] + flags + ['-T', 'lessons/02/linker.ld',
        'lessons/02/start.S', 'lessons/02/uart.c', 'lessons/12/runtime.c',
        'lessons/12/block.c', 'lessons/12/journal.c', 'lessons/12/fs.c',
        'lessons/12/workload.c', 'lessons/12/crash-kernel.c',
        '-o', str(BUILD / 'crash-kernel.elf')], check=True)


def control(disk, operation=0, phase=0, index=0):
    with open(disk, 'r+b') as stream:
        stream.seek(12000 * 512)
        stream.write(struct.pack('<3I', operation, phase, index) + bytes(500))


def harness(disk, name, operation=0, phase=0, index=0, failure=False):
    control(disk, operation, phase, index)
    opts = command(str(disk))
    opts[opts.index('-kernel') + 1] = str(BUILD / 'crash-kernel.elf')
    opts[opts.index('-smp') + 1] = '1'
    completed = subprocess.run(opts, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, timeout=12)
    (BUILD / (name + '.log')).write_bytes(completed.stdout)
    assert completed.returncode == (1 if failure else 0), completed.stdout
    marker = b'FAIL: harness mount rejected' if failure else b'INTERRUPT phase=' if phase else b'PASS harness clean return'
    assert marker in completed.stdout, completed.stdout
    if phase and not failure:
        assert f'phase=0x{phase:016x}'.encode() in completed.stdout
    return disk.read_bytes()


def run_crashes():
    build_harness()
    native = model.Model()
    baseline = native.baseline()
    protected = baseline[:257 * 512]
    rows = []
    replay_image = None
    replay_reference = None

    def verify(raw, reference, label):
        assert raw[:257 * 512] == protected, label + ' protected boot changed'
        assert model.homes(raw) == model.homes(reference), label + ' exact home mismatch'
        assert model.contents(raw) == model.contents(reference), label + ' full file mismatch'

    with tempfile.TemporaryDirectory(prefix='lesson12-crash-') as scratch:
        directory = Path(scratch)
        for operation in range(1, 9):
            disk = directory / f'operation{operation}.img'
            disk.write_bytes(baseline)
            post = harness(disk, f'crash-op{operation}-clean', operation)
            assert model.contents(post) == model.expected(operation, baseline)
            for phase in range(1, 9):
                disk.write_bytes(baseline)
                interrupted = harness(disk, f'crash-op{operation}-phase{phase}', operation, phase, 2 if phase == 5 else 0)
                if phase >= 3 and any(interrupted[12288 * 512:12289 * 512]):
                    applied = bytearray(baseline)
                    for target, image in model.logged(interrupted).items():
                        applied[target * 512:(target + 1) * 512] = image
                    verify(applied, post, 'independent committed-log reconstruction')
                # QEMU normal process exit may flush writes that had no guest
                # FLUSH. At phase3 (header written, not yet flushed), both PRE
                # and POST are permitted; the native model separately proves
                # the volatile-loss PRE outcome at this boundary.
                reference = baseline if phase <= 2 else post
                if phase == 3 and not any(interrupted[12288 * 512:12289 * 512]):
                    reference = baseline
                if operation == 2 and phase == 5:
                    replay_image = interrupted
                    replay_reference = post
                recovered = harness(disk, f'crash-op{operation}-phase{phase}-replay')
                verify(recovered, reference, f'op{operation}-phase{phase}')
                stable = disk.read_bytes()
                again = harness(disk, f'crash-op{operation}-phase{phase}-again')
                assert again == stable, 'second boot changed clean disk'
                rows.append({'operation': operation, 'phase': phase,
                             'expected': 'PRE' if reference is baseline else 'POST',
                             'sha256': hashlib.sha256(model.homes(recovered)).hexdigest()})
        assert replay_image is not None
        disk = directory / 'replay-midpoint.img'
        disk.write_bytes(replay_image)
        harness(disk, 'crash-replay-midpoint', 0, 9, 2)
        final = harness(disk, 'crash-replay-resume')
        verify(final, replay_reference, 'interrupted RISC-V replay')
        for malformed in sorted(BUILD.glob('malformed-*.img')):
            disk = directory / malformed.name
            shutil.copyfile(malformed, disk)
            control(disk)
            before = disk.read_bytes()
            harness(disk, 'crash-' + malformed.stem, failure=True)
            assert disk.read_bytes() == before, 'rejected QEMU recovery wrote image'
        # This is the actual dual-hart disk-boot kernel/U shell, not the above
        # direct-boot harness. A deliberately invalid partially-checkpointed
        # home tree is repaired before the mount's full-tree validation.
        disk = directory / 'dualhart-cold-replay.img'
        disk.write_bytes(replay_image)
        g = Guest('dualhart-cold-replay.log', str(disk))
        try:
            banner = g.until('12> ')
            assert 'both images loaded' in banner and 'mounted BPTFS12' in banner
            assert 'hart-online pid=0x0000000000000001' in banner
            # alpha is binary; readback through real U APIs uses a bounded
            # test command added below, rather than terminal byte guesses.
            g.cmd('fstest replay', 'PASS replay exact binary bytes and EOF')
            g.cmd('echo after-replay', 'echo: after-replay\r\n')
            g.shutdown()
        finally:
            g.close()
        verify(disk.read_bytes(), replay_reference, 'actual dual-hart cold replay')
        stable = disk.read_bytes()
        g = Guest('dualhart-cold-replay-second.log', str(disk))
        try:
            g.until('12> ')
            g.cmd('fstest replay', 'PASS replay exact binary bytes and EOF')
            g.shutdown()
        finally:
            g.close()
        assert disk.read_bytes() == stable, 'second U-shell boot changed image'
        shutil.copyfile(disk, BUILD / 'evidence-dualhart-replay.img')
    result = {'status': 'PASS', 'case_count': len(rows), 'cases': rows,
              'interrupted_replay': True, 'dualhart_U_shell_cold_replay': True,
              'model': 'deterministic QEMU software interruption; not device power loss'}
    (BUILD / 'crash-results.json').write_text(json.dumps(result, indent=2) + '\n')
    print(f'PASS QEMU: {len(rows)} actual RISC-V crash boundaries, interrupted replay, malformed no-write rejection, dual-hart U-shell cold replay and readonly second boot')
    return result


if __name__ == '__main__':
    run_crashes()
