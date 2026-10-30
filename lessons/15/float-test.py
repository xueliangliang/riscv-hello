#!/usr/bin/env python3
"""Independent Python IEEE bits; actual guest compilation, cold read, DLL rebind."""
from pathlib import Path
import hashlib
import importlib.util
import json
import math
import os
import random
import re
import shutil
import struct
import subprocess
import tempfile
from guest import Guest
from native import Native
from decode import decode

spec = importlib.util.spec_from_file_location('compiler_oracle', 'lessons/15/compiler-test.py')
oracle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oracle)
BUILD = Path('build/lesson15')


def bits(value):
    return struct.unpack('<Q', struct.pack('<d', value))[0]


def divide(left, right):
    if right == 0:
        if left == 0 or math.isnan(left):
            return float('nan')
        return math.copysign(float('inf'), math.copysign(1, left) * math.copysign(1, right))
    return left / right


def literal(text):
    """Independent implementation of the DOCUMENTED staged rounding contract."""
    sign = -1 if text.startswith('-') else 1
    text = text.lstrip('+-').lower()
    pieces = text.split('e')
    significand = pieces[0]
    exponent = int(pieces[1]) if len(pieces) == 2 else 0
    fraction = len(significand.split('.')[1]) if '.' in significand else 0
    value = float(int(significand.replace('.', '')))
    scale = exponent - fraction
    for _ in range(abs(scale)):
        value = value * 10.0 if scale > 0 else value / 10.0
    return value * sign


def check_bits(transcript, expected):
    actual = [int(item, 16) for item in re.findall(rb'(?:\r\n|15> )0x([0-9a-f]{16})\r\n', transcript)]
    # Lookahead is needed: consuming the preceding newline drops alternate rows.
    actual = [int(item, 16) for item in re.findall(rb'(?:(?<=\r\n)|(?<=15> ))0x([0-9a-f]{16})(?=\r\n)', transcript)]
    assert len(actual) == len(expected), (len(actual), len(expected), transcript[-4000:])
    for observed, wanted in zip(actual, expected):
        if math.isnan(wanted):
            assert observed & 0x7ff0000000000000 == 0x7ff0000000000000 and observed & 0xfffffffffffff
        else:
            assert observed == bits(wanted), (hex(observed), hex(bits(wanted)), wanted)
    return [hex(item) for item in actual]


def check_full_read(guest, name, expected):
    start = len(guest.all)
    guest.cmd('cat ' + name, 'cat target=0 result=0')
    assert expected.replace(b'\n', b'\r\n') in guest.all[start:], name


def cases():
    yield ('nested', 'int main(){double x=3.25; double y=-2.5; print_bits(x+y*2); print_bits(min(ceil(x),max(2.0,3.5))); print_bits(17/5.0); int n=-3.75; print_int(n); print_bits(9007199254740993+0.0); return 0;}\n',
           [-1.75, 3.5, 3.4, float(9007199254740993)], ['-3'])
    yield ('truth', 'int main(){double z=-0.0; double n=0.0/0.0; if(z) print_int(91); else print_int(7); if(n) print_int(8); print_int(!z); print_int(!n); print_int(n==n); print_int(n!=n); print_int(n<0.0); print_int(n<=0.0); print_int(n>0.0); print_int(n>=0.0); print_bits(z); print_bits(1.0/z); print_bits(n); return 0;}\n',
           [-0.0, -float('inf'), float('nan')], ['7','8','1','0','0','1','0','0','0','0'])
    yield ('decl', 'int main(){int i=0; while(i<3){double x; print_bits(x); x=7.5; i=i+1;} double a=(-9223372036854775807-1); int b=a; print_int(b); return 0;}\n',
           [0.0]*3, [str(-(1<<63))])
    spellings = ['0.0','-0.0','0.1','1234567890123456.0','1.0e-308','1.0e308','2.2250738585072014e-308','9.0e-307','1.0e-320']
    # Last spelling is outside the bounded exponent grammar and tested negative.
    spellings.pop()
    yield ('literals', 'int main(){' + ''.join('print_bits('+text+');' for text in spellings) + 'return 0;}\n',
           [literal(text) for text in spellings], [])
    rng = random.Random(15001917)
    pairs = [('0.0','-0.0'),('1.0e308','1.0e308'),('1.0e-308','3.0'),('-7.25','2.5')]
    pairs += [(str(rng.randrange(-10000,10000)/4),str(rng.randrange(-10000,10000)/8)) for _ in range(32)]
    for index in range(0,len(pairs),4):
        body = 'int main(){'
        expected = []
        integers = []
        for left, right in pairs[index:index+4]:
            a, b = literal(left), literal(right)
            body += '{double a='+left+';double b='+right+';'
            for operator, function in [('+',lambda a,b:a+b),('-',lambda a,b:a-b),('*',lambda a,b:a*b),('/',divide)]:
                body += 'print_bits(a'+operator+'b);'
                expected.append(function(a,b))
            for operator, value in [('==',a==b),('!=',a!=b),('<',a<b),('<=',a<=b),('>',a>b),('>=',a>=b)]:
                body += 'print_int(a'+operator+'b);'
                integers.append(str(int(value)))
            body += '}'
        yield ('arith'+str(index), body+'return 0;}\n',expected,integers)


def main():
    records = []
    with tempfile.TemporaryDirectory(prefix='lesson15-float-', dir=os.environ.get('TMPDIR')) as temporary:
        disk = Path(temporary)/'disk.img'
        shutil.copyfile(BUILD/'disk.img', disk)
        guest = Guest('float-uart.log', disk)
        saved = {}
        try:
            guest.until('15> ')
            for name, source, expected, integers in cases():
                oracle.paste(guest, name+'.c', source)
                oracle.run(guest, './cc '+name+'.c '+name, 0, busy=True)
                output = decode(disk)[name]['content']
                header = oracle.native_header(output)
                execution, transcript = oracle.run(guest, './'+name, 0, integers)
                actual = check_bits(transcript, expected)
                records.append({'name':name,'header':header,'execution':execution,'bits':actual})
                saved[name] = output
                saved[name+'.c'] = source.encode()
            assert len({hashlib.sha256(value).hexdigest() for name,value in saved.items() if not name.endswith('.c')}) == len(records)
            demo = Path('lessons/15/demo.c').read_bytes() + b'\n'
            oracle.paste(guest, 'demo.c', demo)
            oracle.run(guest, './cc demo.c demo', 0)
            oracle.run(guest, './demo', 0, ['sum(1..5) = 15','x = 3.250000','ceil(x) = 4.000000','floor(-x) = -4.000000','max(a, b) = 2.250000','min(a, b) = -3.500000','nested math = 3.500000','average = 3.000000','DEMO_PASS'])
            saved['demo.c'] = demo
            saved['demo'] = decode(disk)['demo']['content']
            # A separate persisted program observes the DLL, without baking math results.
            binding = b'int main(){print_bits(ceil(3.25));print_bits(floor(-3.25));return 0;}\n'
            oracle.paste(guest, 'binding.c', binding)
            oracle.run(guest, './cc binding.c binding', 0)
            _, transcript = oracle.run(guest, './binding', 0)
            check_bits(transcript, [4.0,-4.0])
            saved['binding.c'] = binding
            saved['binding'] = decode(disk)['binding']['content']
            old = saved['nested']
            invalid = ['double x=1.0%2;', 'printf("%d",1.0);', 'printf("%f",1);', 'printf("%s",1);',
                       'printf("%q",1);','printf("%");','printf("%d");','printf("",1);',
                       'double x=1.0e;', 'double x=1.0e309;', 'double x=123456789012345678.0;',
                       'double x=9.9e308;', 'double x=0.0000000000000001e-308;',
                       'double x=x;', 'int x=1; {double x=x;}', 'double x; (+x)=1.0;',
                       'double x; x++;', 'double x=1.;', 'double x=.5;', 'double x=1.2.3;',
                       'double x=1.0; print_int(x);', 'print_bits(1);']
            for index, bad in enumerate(invalid):
                source = ('int main(){'+bad+'return 0;}\n').encode()
                oracle.paste(guest,'bad.c',source)
                for target in ('nested','absent'):
                    oracle.run(guest,'./cc bad.c '+target,1)
                    files = decode(disk)
                    assert files['nested']['content'] == old and files['bad.c']['content'] == source
                    assert 'absent' not in files
                guest.cmd('rm bad.c')
            for index, value in enumerate(['0.0/0.0','1.0/0.0','-1.0/0.0','9.223372036854776e18','-1.0e20']):
                source = 'int main(){double x='+value+';int n=x;print_int(n);return 0;}\n'
                oracle.paste(guest,'trap'+str(index)+'.c',source)
                oracle.run(guest,'./cc trap'+str(index)+'.c trap',0)
                _, transcript = oracle.run(guest,'./trap',70)
                assert b'outside finite int64 range' in transcript
            guest.shutdown()
        finally:
            guest.close()
        # First cold reads of FULL source and executable precede all writes/compiles.
        guest = Guest('float-cold.log', disk)
        try:
            guest.until('15> ')
            for name in ('demo.c','demo','binding.c','binding'):
                check_full_read(guest,name,saved[name])
            cold, transcript = oracle.run(guest,'./binding',0)
            check_bits(transcript,[4.0,-4.0])
            oracle.run(guest,'./demo',0,['DEMO_PASS'])
            guest.shutdown()
        finally:
            guest.close()
        subprocess.run(['make','--no-print-directory','build/lesson15/math-alt.dll'],check=True)
        before_hash = hashlib.sha256(saved['binding']).hexdigest()
        fs = Native(disk)
        fs.put('math.dll',(BUILD/'math-alt.dll').read_bytes())
        fs.save(disk)
        assert decode(disk)['binding']['content'] == saved['binding']
        guest = Guest('float-rebind-cold.log',disk)
        try:
            guest.until('15> ')
            check_full_read(guest,'binding.c',saved['binding.c'])
            check_full_read(guest,'binding',saved['binding'])
            for _ in range(2):
                rebound, transcript = oracle.run(guest,'./binding',0)
                check_bits(transcript,[42.0,-4.0])
            guest.shutdown()
        finally:
            guest.close()
        assert hashlib.sha256(decode(disk)['binding']['content']).hexdigest() == before_hash
        shutil.copyfile(disk,BUILD/'float-verified.img')
        (BUILD/'float-results.json').write_text(json.dumps({'status':'PASS','cases':records,'cold':cold,'rebound':rebound,'unchanged_executable_sha256':before_hash,'negative_classes':len(invalid),'checked_conversion_traps':5,'cpu':'rv64,f=false,d=false,zfa=false'},indent=2)+'\n')
    print('PASS typed native binary64 bits, demo, bounded literal negatives, checked conversions, cold read-first and unchanged executable dynamic DLL rebind')


if __name__ == '__main__':
    main()
