#!/usr/bin/env python3
"""Exact-rational six-decimal oracle, with actual U input bits and full output.

No expected string uses float multiplication/addition or host printf rounding.
Finite inputs are constructed by exact int -> double / powers of two, not the
staged decimal parser. This identical regression must fail on 60558eb.
"""
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import random
import shutil
import struct
import tempfile
from fractions import Fraction

from guest import Guest

spec = importlib.util.spec_from_file_location('printf_test', Path(__file__).with_name('printf-test.py'))
assert spec is not None and spec.loader is not None
formatted = importlib.util.module_from_spec(spec)
spec.loader.exec_module(formatted)
frontend = formatted.frontend
ct = formatted.ct
BUILD = Path('build/lesson15')
SEED = 150060558


def raw_bits(value):
    return int.from_bytes(struct.pack('>d', value), 'big')


def exact_six(value):
    """Round the exact rational magnitude once; genuine ties go away."""
    raw = raw_bits(value)
    magnitude = raw & ((1 << 63) - 1)
    if magnitude > 0x7ff0000000000000:
        return 'nan'
    sign = '-' if raw >> 63 else ''
    if math.isinf(value):
        return sign + 'inf'
    if abs(value) >= 1000000000:
        return sign + '<range>'
    numerator, denominator = abs(value).as_integer_ratio()
    whole, remainder = divmod(numerator * 1000000, denominator)
    if remainder * 2 >= denominator:
        whole += 1
    return sign + str(whole // 1000000) + '.' + f'{whole % 1000000:06d}'


def finite_source(value):
    """All intermediates are exactly representable, including subnormals.

    Start from the <=53-bit integer significand, then divide in <=60-bit
    powers. No earlier intermediate is smaller than the final exact input.
    Unary minus after construction preserves the negative-zero sign.
    """
    numerator, denominator = abs(value).as_integer_ratio()
    assert numerator < 1 << 63
    shift = denominator.bit_length() - 1
    assert denominator == 1 << shift
    source = 'double x=' + str(numerator) + ';'
    while shift:
        count = min(60, shift)
        source += 'x=x/' + str(1 << count) + ';'
        shift -= count
    if raw_bits(value) >> 63:
        source += 'x=-x;'
    return source


def cases():
    result = []

    def add(label, value):
        # Keep directed duplicates: they document separate boundary obligations.
        result.append({'label': label, 'bits': f'0x{raw_bits(value):016x}',
                       'formatted': exact_six(value), 'setup': finite_source(value)})

    # All four reviewer cases, plus the other signs of the three magnitudes.
    for index, (num, den) in enumerate(((8303350407216725, 134217728),
                                      (3468996685553071, 8388608),
                                      (8808704944236413, 16777216))):
        for sign in (1, -1):
            add(f'Q1-{index}-sign{sign}', sign * (num / den))

    # Nearest binary64 neighbors around decimal midpoints, including exact
    # binary ties (odd multiples of 1/128) and fractional/integer carries.
    centers = [Fraction(1, 2000000), Fraction(3, 2000000),
               Fraction(1999999, 2000000), Fraction(3999999, 2000000),
               Fraction(123456789999999, 2000000),
               Fraction(1999999999999999, 2000000),
               Fraction(1, 128), Fraction(3, 128),
               Fraction(999999999 * 128 + 1, 128)]
    for index, center in enumerate(centers):
        middle = float(center)
        for position, value in (('below', math.nextafter(middle, 0.0)),
                                ('nearest', middle),
                                ('above', math.nextafter(middle, math.inf))):
            for sign in (1, -1):
                add(f'midpoint-{index}-{position}-sign{sign}', sign * value)

    for index, value in enumerate((0.0, math.ulp(0.0),
                                    float.fromhex('0x0.fffffffffffffp-1022'),
                                    float.fromhex('0x1p-1022'),
                                    float.fromhex('0x1p-120'),
                                    float.fromhex('0x1p-110'),
                                    float.fromhex('0x1p-100'),
                                    float.fromhex('0x1p-74'),
                                    float.fromhex('0x1p-73'),
                                    1.0, math.nextafter(1.0, 0.0),
                                    math.nextafter(1.0, math.inf),
                                    math.nextafter(1000000000.0, 0.0),
                                    1000000000.0)):
        for sign in (1, -1):
            add(f'boundary-{index}-sign{sign}', sign * value)

    rng = random.Random(SEED)
    for index in range(128):
        # Half span zero/subnormal through the entire valid exponent interval;
        # half focus on values with nonzero six-decimal fractional output.
        exponent = rng.randrange(1053) if index < 64 else rng.randrange(1000, 1053)
        raw = (rng.randrange(2) << 63) | (exponent << 52) | rng.getrandbits(52)
        value = struct.unpack('>d', raw.to_bytes(8, 'big'))[0]
        if abs(value) >= 1000000000:
            value /= 2
        add(f'random-{index}', value)
    return result


def main():
    vectors = cases()
    # Nonfinite classification is exercised without relying on unspecified NaN
    # payload/sign from arithmetic. Infinity bits remain a full exact oracle.
    special = [('positive-inf', 'double x=1.0/0.0;', '0x7ff0000000000000', 'inf'),
               ('negative-inf', 'double x=-1.0/0.0;', '0xfff0000000000000', '-inf'),
               ('nan', 'double x=0.0/0.0;', None, 'nan')]
    records = []
    errors = []
    completed = False
    BUILD.mkdir(parents=True, exist_ok=True)
    result_path = BUILD / 'formatter-results.json'
    result_path.write_text(json.dumps({'status': 'RUNNING'}) + '\n')
    hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in (Path(__file__), Path(__file__).with_name('runtime15.c'),
                           Path(__file__).with_name('cc.c'), BUILD / 'c_runtime',
                           BUILD / 'cc.exec')}
    with tempfile.TemporaryDirectory(prefix='lesson15-formatter-', dir=os.environ.get('TMPDIR')) as temporary:
        disk = Path(temporary) / 'disk.img'
        shutil.copyfile(BUILD / 'disk.img', disk)
        boot = disk.read_bytes()[:512 * 512]
        guest = Guest('formatter-uart.log', str(disk))
        try:
            guest.until('15> ')
            for offset in range(0, len(vectors), 8):
                batch = vectors[offset:offset + 8]
                body = ''.join('{' + item['setup'] + 'print_bits(x);printf("%f\\n",x);}'
                               for item in batch)
                source = ('int main(){' + body + 'return 0;}\n').encode()
                expected = ''.join(item['bits'] + '\n' + item['formatted'] + '\n' for item in batch)
                ct.paste(guest, 'round.c', source)
                compiler = frontend.run_actual(guest, './cc round.c round')
                assert compiler['status'] == 0, compiler
                executable = ct.content(disk, 'round')
                header = ct.native_header(executable)
                execution = frontend.run_actual(guest, './round')
                observed = formatted.full_output(execution)
                preserved = ct.content(disk, 'round.c') == source
                match = execution['status'] == 0 and observed == expected and preserved
                if not match:
                    errors.append('batch-' + str(offset // 8))
                records.append({'vectors': batch, 'source': source.decode(),
                                'source_sha256': hashlib.sha256(source).hexdigest(),
                                'compiler': compiler, 'execution': execution,
                                'header': header, 'source_preserved': preserved,
                                'executable_sha256': hashlib.sha256(executable).hexdigest(),
                                'expected': expected, 'observed': observed, 'match': match})
                guest.cmd('rm round.c')
            for label, setup, expected_bits, expected_text in special:
                source = ('int main(){' + setup + 'print_bits(x);printf("%f\\n",x);print_int(printf(""));return 0;}\n').encode()
                ct.paste(guest, 'special.c', source)
                compiler = frontend.run_actual(guest, './cc special.c special')
                assert compiler['status'] == 0, compiler
                ct.native_header(ct.content(disk, 'special'))
                execution = frontend.run_actual(guest, './special')
                observed = formatted.full_output(execution)
                lines = observed.splitlines()
                assert len(lines) == 3, observed
                raw = int(lines[0], 16)
                bits_match = (lines[0] == expected_bits if expected_bits else
                              (raw & 0x7fffffffffffffff) > 0x7ff0000000000000)
                match = bits_match and lines[1:] == [expected_text, '0'] and execution['status'] == 0
                assert ct.content(disk, 'special.c') == source
                if not match:
                    errors.append(label)
                records.append({'label': label, 'compiler': compiler, 'execution': execution,
                                'observed': observed, 'match': match})
                guest.cmd('rm special.c')
            # A malformed format must not alter an existing executable or create
            # a missing one; verify WHOLE source/output bytes from the real FS.
            old = ct.content(disk, 'round')
            bad = b'int main(){\nprintf("%d",1.0);return 0;}\n'
            ct.paste(guest, 'bad.c', bad)
            for target in ('round', 'absent'):
                compiler = frontend.run_actual(guest, './cc bad.c ' + target)
                files = ct.snapshot(disk)['files']
                frontend.require_rejection(compiler, 'printf conversion/type mismatch',
                                           {'old': old, 'source': bad},
                                           {'old': files['round']['content'],
                                            'source': files['bad.c']['content'],
                                            'missing': 'absent' in files})
                records.append({'invalid_target': target, 'compiler': compiler,
                                'whole_old_preserved': True, 'whole_source_preserved': True,
                                'missing_absent': True})
            guest.shutdown()
            ct.snapshot(disk)
            assert disk.read_bytes()[:512 * 512] == boot
            completed = True
        finally:
            guest.close()
            result = {'status': 'PASS' if completed and not errors else 'FAIL',
                      'seed': SEED, 'finite_vectors': len(vectors), 'special_vectors': len(special),
                      'invalid_attempts': 2, 'hashes': hashes, 'records': records, 'errors': errors}
            result_path.write_text(json.dumps(result, indent=2) + '\n')
    assert not errors, errors
    print(f'PASS exact formatter: {len(vectors)} finite bits/full strings, {len(special)} nonfinite, 2 atomic rejections')


if __name__ == '__main__':
    main()
