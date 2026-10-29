#!/usr/bin/env python3
"""Independent format decoder + actual-C volatile/durable fault experiments."""
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import zlib
from decode import inspect, report

BUILD = Path('build/lesson12')
H = 12288
D = 12289
I = 12305
SIZE = 8 * 1024 * 1024


def homes(raw):
    return raw[512 * 512:1027 * 512] + raw[2048 * 512:10240 * 512]


def contents(raw):
    return {name: value['content'] for name, value in inspect(raw)['files'].items()}


def logged(raw):
    header = raw[H * 512:(H + 1) * 512]
    assert header[:8] == b'REDO12\0\0', 'committed journal header missing'
    fields = struct.unpack_from('<8I', header, 8)
    version, sector, capacity, count, crc, size, start, images = fields
    assert (version, sector, capacity, size, start, images) == (1, 512, 1024, 16384, H, I)
    assert 1 <= count <= 1024 and not any(header[40:508])
    assert zlib.crc32(header[:508]) == struct.unpack_from('<I', header, 508)[0]
    descriptors = raw[D * 512:I * 512]
    assert zlib.crc32(descriptors) == crc and not any(descriptors[count * 8:])
    result = {}
    for n in range(count):
        target, checksum = struct.unpack_from('<II', descriptors, n * 8)
        assert 512 <= target <= 1026 or 2048 <= target < 10240
        assert target not in result
        data = raw[(I + n) * 512:(I + n + 1) * 512]
        assert zlib.crc32(data) == checksum
        result[target] = data
    return result


def reseal(raw):
    struct.pack_into('<I', raw, H * 512 + 24, zlib.crc32(raw[D * 512:I * 512]))
    struct.pack_into('<I', raw, H * 512 + 508, zlib.crc32(raw[H * 512:H * 512 + 508]))


class Model:
    def __init__(self):
        BUILD.mkdir(parents=True, exist_ok=True)
        command = [os.environ.get('HOSTCC', 'cc'), '-std=c11', '-O1', '-g', '-shared', '-fPIC',
                   '-Wall', '-Wextra', '-Werror', '-Ilessons/02', '-Ilessons/12',
                   'lessons/12/fs.c', 'lessons/12/journal.c', 'lessons/12/workload.c',
                   'lessons/12/model.c', '-o', str(BUILD / 'model.so')]
        subprocess.run(command, check=True)
        self.c = C.CDLL(str((BUILD / 'model.so').resolve()))
        # Declare both halves of every exposed native ABI. ctypes otherwise
        # silently returns signed int (UINT_MAX becomes -1) and narrows longs.
        signatures = {
            'model_load': (None, [C.c_void_p]),
            'model_disk': (None, [C.c_void_p]),
            'model_cut': (None, []),
            'model_crash': (None, [C.c_uint, C.c_uint]),
            'model_fault': (None, [C.c_int, C.c_long, C.c_uint, C.c_int]),
            'model_run': (C.c_long, [C.c_uint]),
            'model_trace': (C.c_uint, [C.c_uint, C.c_int]),
            'model_trace_count': (C.c_uint, []),
            'model_trace_overflow': (C.c_uint, []),
            'model_trace_capacity': (C.c_uint, []),
            'fs_mount': (C.c_int, []), 'fs_sync': (C.c_int, []),
            'fs_open': (C.c_long, [C.c_char_p, C.c_uint]),
            'fs_read': (C.c_long, [C.c_long, C.c_void_p, C.c_uint]),
            'fs_write': (C.c_long, [C.c_long, C.c_void_p, C.c_uint]),
            'fs_append': (C.c_long, [C.c_long, C.c_void_p, C.c_uint]),
            'fs_seek': (C.c_long, [C.c_long, C.c_uint]),
            'fs_truncate': (C.c_long, [C.c_long, C.c_uint]),
            'fs_flush': (C.c_long, [C.c_long]),
            'fs_close': (C.c_long, [C.c_long]),
            'fs_remove': (C.c_long, [C.c_char_p]),
            'fs_list_page': (C.c_long, [C.c_void_p, C.c_uint, C.c_void_p]),
            'fs_defrag': (C.c_long, []), 'fs_info': (None, []),
            'journal_crc': (C.c_uint, [C.c_void_p, C.c_uint]),
            'journal_identity': (C.c_int, [C.c_void_p]),
            'journal_recover': (C.c_int, []),
            'journal_begin': (C.c_int, []), 'journal_abort': (None, []),
            'journal_io': (C.c_int, [C.c_uint, C.c_uint, C.c_void_p]),
            'journal_commit': (C.c_int, []), 'journal_error': (C.c_int, []),
            'journal_hook': (None, [C.c_uint, C.c_uint]),
            'block_init': (C.c_int, []),
            'block_request': (C.c_int, [C.c_uint, C.c_uint64, C.c_void_p]),
            'workload': (C.c_long, [C.c_uint]),
            'uart_puts': (None, [C.c_char_p]),
            'print_hex': (None, [C.c_uint64]),
        }
        for name, (result, arguments) in signatures.items():
            function = getattr(self.c, name)
            function.restype = result
            function.argtypes = arguments
        for name in signatures:
            if not name.startswith('model_trace'):
                getattr(self.c, name).errcheck = self.check_trace
        self.buffer = C.create_string_buffer(SIZE)

    def check_trace(self, result, function, arguments):
        assert not self.c.model_trace_overflow(), 'native IO trace overflow: evidence incomplete'
        return result

    def trace(self):
        self.check_trace(None, None, None)
        return [self.c.model_trace(n, 0) for n in range(self.c.model_trace_count())]

    def load(self, raw):
        self.c.model_load(C.c_char_p(raw))

    def disk(self):
        self.c.model_disk(self.buffer)
        return self.buffer.raw

    def mount(self):
        assert self.c.model_run(0) == 0, 'actual C mount/recovery failed'

    def create(self, name, data):
        handle = self.c.fs_open(name.encode(), 1)
        assert handle >= 4, (name, handle)
        for n in range(0, len(data), 4096):
            chunk = data[n:n + 4096]
            assert self.c.fs_write(handle, C.c_char_p(chunk), len(chunk)) == len(chunk)
        assert self.c.fs_close(handle) == 0

    def baseline(self):
        self.load((BUILD / 'disk.img').read_bytes())
        self.mount()
        self.create('alpha', b'A' * 5000)
        self.create('b', b'B' * 5000)
        self.create('c', b'C' * 9000)
        for name in 'defgh':
            self.create(name, name.encode() * 31)
        assert self.c.fs_remove(b'b') == 0
        raw = self.disk()
        assert len(contents(raw)) == 7
        return raw


def expected(operation, before):
    value = contents(before)
    pattern = bytes((i * 37 + 19) & 255 for i in range(4096))
    if operation == 1:
        value['split'] = b''
    elif operation == 2:
        value['alpha'] = value['alpha'][:4900] + pattern
    elif operation == 3:
        value['alpha'] += pattern
    elif operation == 4:
        value['alpha'] = value['alpha'][:20]
    elif operation == 5:
        del value['alpha']
    elif operation == 7:
        value['alpha'] = b''
    elif operation == 8:
        value['alpha'] += bytes(65536 - 5000)
    return value


def trace_contract(m):
    """Fail-first ABI and bounded-evidence regressions using real native IO."""
    raw = (BUILD / 'disk.img').read_bytes()
    m.load(raw)
    # Reproduce the original ctypes default, independently of the typed handle.
    old = C.CDLL(str((BUILD / 'model.so').resolve()))
    assert old.model_trace(0, 0) == -1
    assert m.c.model_trace(0, 0) == 0xffffffff, 'unsigned trace ABI mismatch'
    sector = C.create_string_buffer(512)
    for _ in range(32769):
        assert m.c.block_request(0, 2048, sector) == 0
    assert m.c.block_request(1, 2048, sector) == 0
    assert m.trace()[-1] == 1 and m.c.model_trace_count() == 32770
    capacity = m.c.model_trace_capacity()
    for _ in range(capacity - m.c.model_trace_count()):
        assert m.c.block_request(0, 2048, sector) == 0
    try:
        m.c.block_request(1, 2048, sector)
    except AssertionError as error:
        assert 'trace overflow' in str(error)
    else:
        raise AssertionError('native call accepted saturated trace')
    try:
        m.trace()
    except AssertionError as error:
        assert 'trace overflow' in str(error)
    else:
        raise AssertionError('oracle accepted incomplete evidence')
    m.load(raw)
    assert m.trace() == []
    return {'unsigned_sentinel': True, 'late_write_after_32768': True,
            'overflow_rejected_by_call_and_oracle': True, 'capacity': capacity}


def run_model():
    m = Model()
    trace_evidence = trace_contract(m)
    base = m.baseline()
    (BUILD / 'baseline.img').write_bytes(base)
    protected = base[:257 * 512]
    cases = []
    references = {}
    committed = None

    def verify(raw, reference, label):
        assert raw[:257 * 512] == protected, label + ' protected boot'
        assert homes(raw) == homes(reference), label + ' exact home PRE/POST mismatch'
        assert contents(raw) == contents(reference), label + ' full content mismatch'

    for operation in range(1, 9):
        m.load(base)
        m.mount()
        assert m.c.model_run(operation) >= 0
        post = m.disk()
        assert contents(post) == expected(operation, base), ('independent operation bytes', operation)
        references[operation] = post
        if operation == 1:
            assert inspect(post)['height'] == 2, 'no real B+ split'
        if operation == 6:
            assert inspect(post)['holes'] == 0
            assert inspect(post)['files']['c']['blocks'] != inspect(base)['files']['c']['blocks']
        for phase in range(1, 9):
            m.load(base)
            m.mount()
            m.c.model_crash(phase, 2 if phase == 5 else 0)
            assert m.c.model_run(operation) == -99, ('hook not reached', operation, phase)
            crashed = m.disk()
            if phase == 4:
                after = bytearray(base)
                for target, data in logged(crashed).items():
                    after[target * 512:(target + 1) * 512] = data
                verify(after, post, 'independent redo application')
                if operation == 2:
                    committed = crashed
            reference = base if phase <= 3 else post
            # The volatile model loses the unflushed commit header at phase3.
            m.mount()
            recovered = m.disk()
            verify(recovered, reference, f'op{operation}-phase{phase}')
            m.c.model_cut()
            m.mount()
            assert m.disk() == recovered, 'second readonly boot changed image'
            cases.append({'operation': operation, 'phase': phase, 'expected': 'PRE' if phase <= 3 else 'POST'})
        # Reported errors can either persist or not. Match real request sites.
        for kind, typ, sector, occurrence in [
            ('payload-flush', 4, -1, 1), ('commit-write', 1, H, 1),
            ('commit-flush', 4, -1, 2), ('checkpoint-write', 1, 513, 1),
            ('home-flush', 4, -1, 3), ('clear-write', 1, H, 2),
            ('clear-flush', 4, -1, 4)]:
            for persisted in (0, 1):
                m.load(base)
                m.mount()
                m.c.model_fault(typ, sector, occurrence, persisted)
                assert m.c.model_run(operation) == -14, ('missing error classification', operation, kind, persisted)
                # No further request is allowed before remount.
                assert m.c.fs_defrag() == -14
                m.c.model_cut()
                m.mount()
                after_commit = kind in ('checkpoint-write', 'home-flush', 'clear-write', 'clear-flush')
                after_commit |= kind in ('commit-write', 'commit-flush') and bool(persisted)
                reference = post if after_commit else base
                verify(m.disk(), reference, f'{operation}-{kind}-{persisted}')
                stable = m.disk()
                m.c.model_cut()
                m.mount()
                assert m.disk() == stable
                cases.append({'operation': operation, 'error': kind, 'persisted': persisted,
                              'expected': 'POST' if after_commit else 'PRE'})
    assert committed is not None
    (BUILD / 'committed.img').write_bytes(committed)
    m.load(committed)
    m.c.model_crash(9, 2)
    assert m.c.model_run(0) == -99
    m.mount()
    verify(m.disk(), references[2], 'interrupted native replay')

    # Recovery errors also have persisted/nonpersisted legal outcomes. Home
    # may be partly checkpointed; the next complete mount must still yield POST.
    recovery_cases = []
    for kind, typ, sector, occurrence in [
        ('replay-home-write', 1, 513, 1), ('replay-home-flush', 4, -1, 1),
        ('replay-clear-write', 1, H, 1), ('replay-clear-flush', 4, -1, 2)]:
        for persisted in (0, 1):
            m.load(committed)
            m.c.model_fault(typ, sector, occurrence, persisted)
            assert m.c.model_run(0) < 0, (kind, persisted)
            m.c.model_cut()
            m.mount()
            verify(m.disk(), references[2], kind)
            stable = m.disk()
            m.c.model_cut()
            m.mount()
            assert m.disk() == stable
            recovery_cases.append({'error': kind, 'persisted': persisted, 'expected': 'POST'})

    # CRC-correct malicious target records still reject before any writes.
    mutations = {}
    for label, location in [('header-crc', H * 512 + 508), ('payload-crc', I * 512 + 20),
                            ('descriptor-crc', D * 512 + 4)]:
        raw = bytearray(committed)
        raw[location] ^= 1
        mutations[label] = raw
    for label, target in [('duplicate', struct.unpack_from('<I', committed, D * 512)[0]),
                          ('boot', 0), ('gap', 12000), ('log', H), ('outside', 16384)]:
        raw = bytearray(committed)
        struct.pack_into('<I', raw, D * 512 + 8, target)
        reseal(raw)
        mutations[label] = raw
    for label, offset, value in [('count-overflow', 20, 1025), ('count-zero', 20, 0),
                                  ('version', 8, 2), ('reserved', 40, 1)]:
        raw = bytearray(committed)
        struct.pack_into('<I', raw, H * 512 + offset, value)
        reseal(raw)
        mutations[label] = raw
    raw = bytearray(committed)
    raw[512 * 512 + 6] = ord('1')
    struct.pack_into('<I', raw, 512 * 512 + 508, zlib.crc32(raw[512 * 512:512 * 512 + 508]))
    mutations['foreign11'] = raw
    for label, raw in mutations.items():
        m.load(bytes(raw))
        assert m.c.model_run(0) < 0, label
        assert m.disk() == raw, label + ' wrote durable bytes'
        trace = m.trace()
        assert 1 not in trace and 4 not in trace, label + ' issued writes before validation'
        (BUILD / f'malformed-{label}.img').write_bytes(raw)

    # 1024 means unique sectors, not number of journal_io calls. Exercise
    # the real core directly without introducing a second journal algorithm.
    m.load(base)
    m.mount()
    assert m.c.journal_begin() == 0
    sector_buffer = C.create_string_buffer(b'X' * 512, 512)
    readback = C.create_string_buffer(512)

    for sector in range(2048, 3072):
        assert m.c.journal_io(1, sector, sector_buffer) == 0
    sector_buffer.raw = b'Y' * 512
    for _ in range(1030):
        assert m.c.journal_io(1, 2048, sector_buffer) == 0
    assert m.c.journal_io(0, 2048, readback) == 0
    assert readback.raw == b'Y' * 512
    assert m.c.journal_io(1, 3072, sector_buffer) == -17
    assert m.disk() == base
    m.c.journal_abort()
    trace_end = m.c.model_trace_count()
    assert m.c.journal_begin() == 0
    assert m.c.journal_commit() == 0
    assert m.c.model_trace_count() == trace_end, 'empty transaction issued IO'
    assert m.c.model_trace(trace_end, 0) == 0xffffffff, 'unsigned trace ABI mismatch'
    assert m.disk() == base
    for forbidden in (0, 511, 1027, 12000, H, 16384):
        m.load(base)
        m.mount()
        assert m.c.journal_begin() == 0
        assert m.c.journal_io(1, forbidden, sector_buffer) == -14
        assert m.disk() == base
        m.c.journal_abort()

    # Exact rollback on a real oversized defrag, including RAM cursors/epoch.
    m.load(base)
    m.mount()
    for i in range(35):
        m.create(f'big{i:02d}', bytes([i]) * 65536)
    large = m.disk()
    assert inspect(large)['used_blocks'] * 8 > 1024
    before_cursor = C.create_string_buffer(8)
    listing = C.create_string_buffer(16 * 36)
    assert m.c.fs_list_page(listing, 16, before_cursor) == 16
    assert m.c.fs_defrag() == -17
    assert m.disk() == large, 'capacity failure changed disk'
    after_cursor = C.create_string_buffer(8)
    assert m.c.fs_list_page(listing, 16, after_cursor) == 16
    assert before_cursor.raw == after_cursor.raw, 'capacity failure changed epoch'
    m.create('stillhealthy', b'usable-after-limit')
    assert contents(m.disk())['stillhealthy'] == b'usable-after-limit'
    # Max epoch zero calls: ordinary validation still applies, exact nonmutation.
    raw = bytearray(base)
    struct.pack_into('<I', raw, 512 * 512 + 36, 0xffffffff)
    struct.pack_into('<I', raw, 512 * 512 + 508, zlib.crc32(raw[512 * 512:512 * 512 + 508]))
    m.load(bytes(raw))
    m.mount()
    handle = m.c.fs_open(b'alpha', 2)
    assert handle >= 4
    assert m.c.fs_seek(handle, 23) == 23
    assert m.c.fs_write(handle, None, 0) == 0
    assert m.c.fs_append(handle, None, 0) == 0
    assert m.c.fs_write(handle, C.c_char_p(b'x'), 1) == -11
    assert m.c.fs_seek(handle, 23) == 23
    assert m.disk() == raw
    # Actual successful captured evidence is load-bearing: corrupt a content byte.
    damaged = bytearray(references[2])
    location = (2048 + (inspect(damaged)['files']['alpha']['head'] - 1) * 8) * 512 + 4
    damaged[location] ^= 1
    try:
        verify(damaged, references[2], 'mutated oracle evidence')
    except AssertionError:
        pass
    else:
        raise AssertionError('oracle accepted changed payload')
    result = {'status': 'PASS', 'trace_contract': trace_evidence,
              'cases': cases, 'case_count': len(cases),
              'recovery_errors': recovery_cases, 'recovery_error_count': len(recovery_cases),
              'dedup_read_your_writes_1024_unique': True, 'empty_transaction_no_IO': True,
              'malformed_no_write': list(mutations), 'capacity': 'atomic -17, healthy afterward',
              'baseline_sha256': hashlib.sha256(base).hexdigest(),
              'baseline': report(inspect(base)), 'references': {str(k): report(inspect(v)) for k, v in references.items()}}
    (BUILD / 'model-results.json').write_text(json.dumps(result, indent=2) + '\n')
    print(f'PASS actual-C volatile/durable model: {len(cases)} crash/error outcomes, {len(mutations)} no-write malformed logs, interrupted replay, capacity rollback, epoch no-op')
    return result


if __name__ == '__main__':
    run_model()
