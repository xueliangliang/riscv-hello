#!/usr/bin/env python3
"""Full output oracles for guest printf: evaluate once before outer writes.

The same file runs against the pre-fix compiler. Expected values are specified
here, not inferred from generated instructions or rounded float output.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

from guest import Guest

spec = importlib.util.spec_from_file_location('frontend', Path(__file__).with_name('frontend-test.py'))
assert spec is not None and spec.loader is not None
frontend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(frontend)
ct = frontend.ct
BUILD = Path('build/lesson15')


def nested_formats(levels):
    expression = 'printf("%d%d%d%d%d%d%d%d\\n",1,2,3,4,5,6,7,8)'
    for _ in range(levels):
        expression = 'printf("%d%d%d%d%d%d%d%d\\n",0,0,0,0,0,0,0,' + expression + ')'
    return expression


def cases():
    yield 'order', 'printf("A%dB%d\\n",print_int(11),print_int(22));', '11\n22\nA0B0\n'
    yield 'nested', 'printf("outer[%d,%d]\\n",printf("inner[%d]\\n",print_int(31)),print_int(32));', '31\ninner[0]\n32\nouter[0,0]\n'
    yield 'specnested', 'printf("A%dB%dC%d\\n",printf("X"),print_int(22),print_int(33));', 'X22\n33\nA0B0C0\n'
    yield 'assign', 'int x=0; printf("%d/%d/%d/%d\\n",x=9007199254740993,x=x+2,x=x+4,x); print_int(x);', '9007199254740993/9007199254740995/9007199254740999/9007199254740999\n9007199254740999\n'
    yield 'float', 'double x=0.0; printf("%f|%f|%d\\n",x=max(ceil(3.25),2.0)+0.125,x=max(ceil(x),7.0)+0.25,print_bits(x)); print_bits(x);', '0x401d000000000000\n4.125000|7.250000|0\n0x401d000000000000\n'
    yield 'eight', 'int x=0; double y=0.0; printf("%d|%f|%s|%d|%f|%s|%d|%d|%%\\n",x=9007199254740993,y=ceil(3.25),"literal",print_int(44),y=max(y,7.25),"end",x=x+2,print_bits(y)); print_int(x);', '44\n0x401d000000000000\n9007199254740993|4.000000|literal|0|7.250000|end|9007199254740995|0|%\n9007199254740995\n'
    yield 'operand', 'print_int(9007199254740993+printf("v%d\\n",print_int(61))+print_int(62)); print_bits((1.0+1.0/4503599627370496.0)+printf("f%d\\n",print_int(63)));', '61\nv0\n62\n9007199254740993\n63\nf0\n0x3ff0000000000001\n'
    yield 'percent', 'print_int(printf("%% plain %%\\n")); printf("");', '% plain %\n0\n'
    declarations = ''.join(f'int v{i}={i};' for i in range(256))
    yield 'locals', declarations + 'printf("%d/%d\\n",v0=9007199254740993,v255=v255+1); print_int(v0); print_int(v255);', '9007199254740993/256\n9007199254740993\n256\n'
    # 17*7 outer saved slots + 8 innermost slots + 1 arithmetic
    # operand = exactly 128 aligned temporary slots, without hidden locals.
    yield 'capacity', 'print_int(9007199254740993+' + nested_formats(17) + ');', '12345678\n' + '00000000\n' * 17 + '9007199254740993\n'


def full_output(record):
    pid = record['pid']
    text = record['transcript'].replace('\r\n', '\n')
    match = re.search(r'exec target=0 result=' + str(pid) + r'\n(?:15> )?(.*?)zombie pid=0x%016x value=' % pid, text, re.S)
    assert match, text
    return match[1]


def invalid_cases():
    yield 'eval', nested_formats(18) + ';', 'native evaluation stack exceeded'
    yield 'generation', 'print_int(printf("%%")' + '+1' * 140 + ');', 'code generation nesting exceeded'
    yield 'ninth', 'printf("%d%d%d%d%d%d%d%d%d",1,2,3,4,5,6,7,8,9);', 'printf argument capacity exceeded'
    yield 'type', 'printf("%d",1.0);', 'printf conversion/type mismatch'
    yield 'string', 'printf("%s",printf("inner"));', 'printf conversion/type mismatch'
    yield 'trailing', 'printf("tail%");', 'unterminated printf conversion'


def main():
    records = []
    errors = []
    completed = False
    with tempfile.TemporaryDirectory(prefix='lesson15-printf-', dir=os.environ.get('TMPDIR')) as temporary:
        disk = Path(temporary) / 'disk.img'
        shutil.copyfile(BUILD / 'disk.img', disk)
        boot = disk.read_bytes()[:512*512]
        guest = Guest('printf-uart.log', str(disk))
        try:
            guest.until('15> ')
            for name, body, expected in cases():
                source = ('int main(){' + body + 'return 0;}\n').encode()
                ct.paste(guest, name + '.c', source)
                compiler = frontend.run_actual(guest, './cc ' + name + '.c ' + name)
                assert compiler['status'] == 0, compiler
                executable = ct.content(disk, name)
                ct.native_header(executable)
                execution = frontend.run_actual(guest, './' + name)
                observed = full_output(execution)
                record = {'name': name, 'source': source.decode(), 'compiler': compiler,
                          'execution': execution, 'expected': expected, 'observed': observed,
                          'source_preserved': ct.content(disk, name + '.c') == source,
                          'executable_sha256': hashlib.sha256(executable).hexdigest()}
                if execution['status'] != 0 or observed != expected or not record['source_preserved']:
                    errors.append(name)
                records.append(record)
            # Rejection must precede publication to BOTH existing and absent
            # outputs; inspect every byte via the independent raw FS decoder.
            for name, body, diagnostic in invalid_cases():
                ct.run(guest, './cc order.c order', 0)
                old = ct.content(disk, 'order')
                if 'absent' in ct.snapshot(disk)['files']:
                    guest.cmd('rm absent')
                source = ('int main(){\n' + body + '\nreturn 0;}\n').encode()
                ct.paste(guest, 'bad.c', source)
                for target in ('order', 'absent'):
                    record = frontend.run_actual(guest, './cc bad.c ' + target)
                    files = ct.snapshot(disk)['files']
                    after = {'old': files['order']['content'], 'source': files['bad.c']['content'],
                             'missing': 'absent' in files}
                    before = {'old': old, 'source': source}
                    try:
                        frontend.require_rejection(record, diagnostic, before, after)
                    except AssertionError as error:
                        errors.append(name + '/' + target + ': ' + str(error))
                    records.append({'invalid': name, 'target': target, 'compiler': record,
                                    'old_preserved': after['old'] == old,
                                    'source_preserved': after['source'] == source,
                                    'missing_absent': not after['missing']})
                guest.cmd('rm bad.c')
            recovery = frontend.run_actual(guest, './order')
            assert recovery['status'] == 0
            assert full_output(recovery) == '11\n22\nA0B0\n'
            guest.shutdown()
            ct.snapshot(disk)
            assert disk.read_bytes()[:512*512] == boot
            completed = True
        finally:
            guest.close()
            result = {'status': 'PASS' if completed and not errors else 'FAIL',
                      'records': records, 'errors': errors,
                      'regression_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
            (BUILD / 'printf-results.json').write_text(json.dumps(result, indent=2) + '\n')
    assert not errors, errors
    print('PASS printf: full output, int64 and binary64 bits, nested calls, 8 typed arguments, 256 user locals, 128 temporaries and fail-closed publication')


if __name__ == '__main__':
    main()
