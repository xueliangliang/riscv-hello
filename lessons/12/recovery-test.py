#!/usr/bin/env python3
"""Immediate capacity sync/U shutdown and real-driver same-runtime recovery.
All disks are disposable; once-only blkdebug errors exercise actual DMA/status.
Run each --case separately to prove neither blocker masks the other.
"""
import argparse
import ctypes as C
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
from decode import inspect
from run import command
from test import Guest

spec = importlib.util.spec_from_file_location('model_test', Path(__file__).with_name('model-test.py'))
assert spec is not None and spec.loader is not None
model = importlib.util.module_from_spec(spec)
spec.loader.exec_module(model)
BUILD = Path('build/lesson12')


def capacity_image(m):
    base = m.baseline()
    for index in range(35):
        m.create(f'big{index:02d}', bytes([index]) * 65536)
    raw = m.disk()
    assert inspect(raw)['used_blocks'] * 8 > 1024
    return raw


def native_limit(m, raw):
    m.load(raw)
    m.mount()
    cursor = C.create_string_buffer(8)
    listing = C.create_string_buffer(16 * 36)
    assert m.c.fs_list_page(listing, 16, cursor) == 16
    before_cursor = cursor.raw
    before_listing = listing.raw
    assert m.c.fs_defrag() == -17
    # No open/begin/mutator is allowed between rejection and sync: those
    # used to hide the stale J_LIMIT error by clearing it in journal_begin.
    end = m.c.model_trace_count()
    assert m.c.fs_sync() == 0, 'benign J_LIMIT blocked immediate fs_sync'
    assert m.trace()[end:] == [4], 'sync did not issue an actual type4 request'
    assert m.c.journal_error() == 0
    assert m.disk() == raw, 'capacity rejection/sync changed exact disk'
    assert m.c.fs_list_page(listing, 16, cursor) >= 0, 'saved cursor epoch invalidated'
    fresh = C.create_string_buffer(8)
    assert m.c.fs_list_page(listing, 16, fresh) == 16
    assert fresh.raw == before_cursor and listing.raw == before_listing
    assert m.disk() == raw
    handle = m.c.fs_open(b'alpha', 0)
    data = C.create_string_buffer(4096)
    assert handle >= 4 and m.c.fs_read(handle, data, 4096) == 4096
    assert data.raw == b'A' * 4096
    assert m.c.fs_read(handle, data, 904) == 904 and data.raw[:904] == b'A' * 904
    assert m.c.fs_read(handle, data, 1) == 0
    assert m.c.fs_close(handle) == 0
    # Direct journal abort must clear ONLY the benign error, not sticky IO.
    assert m.c.journal_begin() == 0
    sector = C.create_string_buffer(512)
    for lba in range(2048, 3072):
        assert m.c.journal_io(1, lba, sector) == 0
    assert m.c.journal_io(1, 3072, sector) == -17
    m.c.journal_abort()
    end = m.c.model_trace_count()
    assert m.c.fs_sync() == 0 and m.trace()[end:] == [4]
    m.c.model_fault(0, 2048, 1, 0)
    assert m.c.journal_io(0, 2048, sector) == -14
    m.c.journal_abort()
    end = m.c.model_trace_count()
    assert m.c.journal_error() == -14 and m.c.fs_sync() == -14
    assert m.c.model_trace_count() == end, 'IO poison issued requests'
    m.mount()
    assert m.c.fs_sync() == 0 and m.disk() == raw
    return {'immediate_sync_actual_type4': True, 'exact_disk_RAM_cursor_epoch_rollback': True,
            'abort_retains_IO_poison_until_remount': True}


def user_limit(directory, raw):
    disk = directory / 'capacity.img'
    disk.write_bytes(raw)
    g = Guest('recovery-limit-U.log', str(disk), allow_failure=True)
    try:
        g.until('12> ')
        g.cmd('defrag', 'defrag target=0 result=-17')
        assert 'healthy=0x0000000000000001' in g.cmd('fsinfo')
        # In particular: no FS open/mutator before the shutdown syscall.
        g.shutdown()
    finally:
        g.close()
    assert disk.read_bytes() == raw, 'capacity/shutdown changed exact disk'
    return {'dualhart_U_immediate_shutdown_exit': 0, 'exact_disk_unchanged': True}


def build_remount():
    flags = ['-march=rv64imac_zicsr_zifencei', '-mabi=lp64', '-mcmodel=medany',
             '-msmall-data-limit=0', '-O1', '-g', '-ffreestanding', '-fno-builtin',
             '-fno-pic', '-fno-stack-protector', '-fno-unwind-tables',
             '-fno-asynchronous-unwind-tables', '-Wall', '-Wextra', '-Werror',
             '-Ilessons/02', '-Ilessons/12', '-nostdlib', '-static', '-Wl,--build-id=none']
    subprocess.run([os.environ.get('CC', 'riscv64-linux-gnu-gcc')] + flags +
                   ['-T', 'lessons/02/linker.ld', 'lessons/02/start.S', 'lessons/02/uart.c',
                    'lessons/12/runtime.c', 'lessons/12/block.c', 'lessons/12/journal.c',
                    'lessons/12/fs.c', 'lessons/12/workload.c', 'lessons/12/remount-kernel.c',
                    '-o', str(BUILD / 'remount-kernel.elf')], check=True)


def real_remount(m, directory, fault='both'):
    build_remount()
    baseline = m.baseline()
    m.load(baseline)
    m.mount()
    assert m.c.model_run(2) == 4096
    post = m.disk()
    assert model.contents(post) == model.expected(2, baseline)
    rows = []
    for name, lba, reference in [('payload', model.I, baseline), ('checkpoint', 513, post)]:
        if fault != 'both' and name != fault:
            continue
        disk = directory / (name + '.img')
        disk.write_bytes(baseline)
        config = directory / (name + '.conf')
        config.write_text('[inject-error]\nevent = "write_aio"\nerrno = "5"\n'
                          f'sector = "{lba}"\nonce = "on"\nimmediately = "on"\n')
        opts = command(f'blkdebug:{config}:{disk}', device_extra=',werror=report,rerror=report')
        opts[opts.index('-kernel') + 1] = str(BUILD / 'remount-kernel.elf')
        opts[opts.index('-smp') + 1] = '1'
        completed = subprocess.run(opts, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, timeout=12)
        (BUILD / f'recovery-remount-{name}.log').write_bytes(completed.stdout)
        assert b'request-type=0x0000000000000001 status=0x0000000000000001' in completed.stdout, completed.stdout
        assert b'PASS sticky IO poison before reset' in completed.stdout, completed.stdout
        assert completed.returncode == 0, completed.stdout
        assert b'PASS real-driver same-runtime remount and mutation' in completed.stdout
        m.load(reference)
        m.mount()
        m.create('resumed', b'after-reset')
        expected = m.disk()
        actual = disk.read_bytes()
        assert actual[:257 * 512] == baseline[:257 * 512]
        assert model.homes(actual) == model.homes(expected), name + ' exact PRE/POST home mismatch'
        assert model.contents(actual) == model.contents(expected)
        assert not any(actual[model.H * 512:(model.H + 1) * 512]), 'log not cleared'
        # Cold read-only boot must be idempotent after SAME-runtime recovery.
        g = Guest(f'recovery-remount-{name}-cold.log', str(disk))
        try:
            g.until('12> ')
            g.cmd('cat resumed', 'after-reset')
            g.shutdown()
        finally:
            g.close()
        assert disk.read_bytes() == actual
        rows.append({'fault': name, 'sector': lba, 'status': 1, 'remount_exit': 0,
                     'recovery': 'PRE' if name == 'payload' else 'POST',
                     'exact_home_content_and_cold_idempotence': True})
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--case', choices=['native', 'limit-U', 'remount', 'all'], default='all')
    parser.add_argument('--fault', choices=['payload', 'checkpoint', 'both'], default='both')
    args = parser.parse_args()
    case = args.case
    fixture = BUILD / 'disk.img'
    digest = hashlib.sha256(fixture.read_bytes()).digest()
    result_path = BUILD / ('recovery-' + case + '-results.json')
    result_path.unlink(missing_ok=True)
    result = {}
    try:
        m = model.Model()
        with tempfile.TemporaryDirectory(prefix='lesson12-recovery-') as scratch:
            directory = Path(scratch)
            if case in ('native', 'limit-U', 'all'):
                raw = capacity_image(m)
                if case in ('native', 'all'):
                    result['native'] = native_limit(m, raw)
                if case in ('limit-U', 'all'):
                    result['U_limit'] = user_limit(directory, raw)
            if case in ('remount', 'all'):
                result['QEMU_remount'] = real_remount(m, directory, args.fault)
    finally:
        assert hashlib.sha256(fixture.read_bytes()).digest() == digest, 'protected fixture changed'
    result_path.write_text(json.dumps({'status': 'PASS', **result}, indent=2) + '\n')
    print('PASS recovery regression:', json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
