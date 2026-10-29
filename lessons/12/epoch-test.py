#!/usr/bin/env python3
"""Real U-mode epoch exhaustion regression, on disposable disks only."""
import hashlib
from pathlib import Path
import shutil
import struct
import zlib
import tempfile
import time

from decode import inspect
from run import command
from test import Guest


def epoch_boundary(directory):
    disk = directory / 'epoch.img'
    shutil.copyfile('build/lesson12/disk.img', disk)
    g = Guest('epoch-seed.log', str(disk))
    try:
        g.until('12> ')
        g.cmd('fwrite max seed', 'result=4')
        g.cmd('ftruncate max 65536', 'result=0')
        g.cmd('fwrite short small', 'result=5')
        g.shutdown()
    finally:
        g.close()
    raw = bytearray(disk.read_bytes())
    struct.pack_into('<I', raw, 512 * 512 + 36, 0xfffffffe)
    struct.pack_into('<I', raw, 512 * 512 + 508, zlib.crc32(raw[512 * 512:512 * 512 + 508]))
    disk.write_bytes(raw)
    before = inspect(raw)
    assert before['epoch'] == 0xfffffffe
    assert before['files']['max']['size'] == 65536
    # Only the starting persisted counter is seeded. The final counter MUST
    # be reached by the actual syscall/mutator/persist path, not a RAM mock.
    g = Guest('epoch-advance.log', str(disk))
    try:
        g.until('12> ')
        g.cmd('fseek max 9000 Q', 'result=1')
        g.shutdown()
    finally:
        g.close()
    boundary = disk.read_bytes()
    after = inspect(boundary)
    assert after['epoch'] == 0xffffffff, 'real write did not advance epoch'
    expected = bytearray(before['files']['max']['content'])
    expected[9000] = ord('Q')
    assert after['files']['max']['content'] == expected
    print('PASS epoch persisted 0xfffffffe -> 0xffffffff by real U write', flush=True)
    failures = []
    # Fresh cold boots independently reach BOTH operations even on a broken
    # kernel; one early write failure must not mask the append regression.
    for operation in ('write', 'append'):
        g = Guest(f'epoch-{operation}.log', str(disk), allow_failure=True)
        try:
            g.until('12> ')
            g.send(f'fstest epoch-{operation}\r')
            output = ''
            deadline = time.monotonic() + 5
            while 'PASS epoch no-op' not in output and 'FAIL epoch' not in output:
                assert time.monotonic() < deadline, ('epoch timeout', operation, output)
                output += g.read()
                if 'FAIL epoch' not in output and 'PASS epoch no-op' not in output:
                    assert g.process.poll() is None, output
            if 'FAIL epoch' in output:
                failures.append((operation, output.strip()))
                print(f'FAIL epoch {operation}: {output.strip()}', flush=True)
            else:
                if '\r\n12> ' not in output:
                    g.until('\r\n12> ')
                g.shutdown()
                print(f'PASS epoch {operation}: validation, no-op, cursor, full-file limit, nonzero rejection', flush=True)
        finally:
            g.close()
        assert disk.read_bytes() == boundary, f'{operation} changed exact disk bytes'
        assert inspect(disk)['epoch'] == 0xffffffff
    assert not failures, ('epoch zero-count regression', failures)

    # Start one mutation earlier: the faulted write reaches epoch max before
    # its real FLUSH fails. A bare FLUSH on a clean QEMU backend may be elided.
    struct.pack_into('<I', raw, 512 * 512 + 508, zlib.crc32(raw[512 * 512:512 * 512 + 508]))
    disk.write_bytes(raw)
    config = directory / 'epoch-flush.conf'
    config.write_text('[inject-error]\nevent = "flush_to_disk"\nerrno = "5"\nonce = "on"\n')
    options = command(f'blkdebug:{config}:{disk}', device_extra=',werror=report,rerror=report')
    g = Guest('epoch-poison.log', str(disk), allow_failure=True, options=options)
    try:
        g.until('12> ')
        g.cmd('fstest epoch-poison', 'PASS epoch poison validation')
        assert b'request-type=0x0000000000000004 status=0x0000000000000001' in g.all
        g.shutdown(failure=True)
    finally:
        g.close()
    # Error durability is intentionally uncertain; do not require rollback
    # of the faulted mutator, unlike the exact-byte checks on the clean disk.
    print('PASS epoch poison: actual device IOERR, both zero calls reject F_IO', flush=True)


def main():
    fixture = Path('build/lesson12/disk.img')
    digest = hashlib.sha256(fixture.read_bytes()).digest()
    result = Path('build/lesson12/epoch-result.log')
    result.write_text('RUNNING epoch boundary regression\n')
    try:
        with tempfile.TemporaryDirectory(prefix='lesson12-epoch-') as scratch:
            epoch_boundary(Path(scratch))
    finally:
        assert hashlib.sha256(fixture.read_bytes()).digest() == digest, 'protected fixture changed'
    result.write_text('PASS: persisted epoch transition, cold U write/append no-ops, validation, full-file limit, exact disk nonmutation, real IOERR poison\n')


if __name__ == '__main__':
    main()
