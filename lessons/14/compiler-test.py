#!/usr/bin/env python3
"""Real UART → U cc → reap → native exec → cold exec, independent oracles."""
from pathlib import Path
import hashlib
import json
import os
import re
import shutil
import struct
import tempfile
from guest import Guest
from decode import inspect, report

BUILD = Path('build/lesson14')
MASK = (1 << 64) - 1

def signed(value):
    value &= MASK
    return value - (1 << 64) if value >> 63 else value

def divide(left, right):
    if not right:
        return -1
    magnitude = abs(left) // abs(right)
    return signed(-magnitude if (left < 0) != (right < 0) else magnitude)

def remainder(left, right):
    return left if not right else signed(left - divide(left, right) * right)

def snapshot(disk):
    raw = Path(disk).read_bytes()
    assert not any(raw[12288*512:12289*512]), 'unclean journal'
    return inspect(raw)

def content(disk, name):
    return snapshot(disk)['files'][name]['content']

def native_header(data):
    magic, version, size, payload, entry, base, memory, abi, code, a, b = struct.unpack_from('<8s10I', data)
    assert magic == b'RVEXEC1\0' and version == 1 and size == len(data)
    assert payload == len(data)-48 and base == 0x80500000 and abi == 2
    assert payload <= memory <= 1048576 and not payload % 16 and not memory % 16
    assert 32 <= entry < code <= 32768 and not code % 4 and not (a or b)
    assert struct.unpack_from('<I', data, 48+entry)[0] == 0x80010113, 'native stack prologue'
    assert data[48:56] == b'RVINT14\0'

    return {'bytes': len(data), 'entry': entry, 'code': code,
            'sha256': hashlib.sha256(data).hexdigest()}

def paste(guest, name, body, delimiter='END14', ending=b'\r\n', success=True):
    if isinstance(body, str):
        body = body.encode()
    start = len(guest.all)
    guest.send(b'fappend '+name.encode()+b' <<'+delimiter.encode()+ending+body+delimiter.encode()+ending)
    expected = 'raw target=0 result=' if success else 'raw: rejected; drained; unchanged'
    guest.until(expected, 15)
    guest.read(0.05)
    output = guest.all[start:].decode(errors='replace')
    assert expected in output, output[-2000:]
    if success:
        normalized = body.replace(b'\r\n',b'\n').replace(b'\r',b'\n')
        assert f'raw target=0 result={len(normalized)}\r\n' in output, output[-2000:]
    return output

def check_execution(data, pid, status, expected=None):
    assert re.search(rb'reap pid=0x%016x value=0x%016x' % (pid, status), data), data[-2000:]
    assert re.search(rb'zombie pid=0x%016x value=0x%016x' % (pid, status), data), data[-2000:]
    assert f'wait target={pid} result={status}'.encode() in data
    if expected is not None:
        for text in expected:
            assert re.search(rb'(?:\r\n|14> )'+re.escape(text.encode())+rb'\r\n', data), (text, data[-2000:])

def check_saved(actual, expected):
    assert actual == expected, 'persisted full bytes differ'

def run(guest, command, status, expected=None, busy=False):
    start = len(guest.all)
    output = guest.cmd(command)
    match = re.search(r'exec target=0 result=(\d+)\r?\n', output)
    assert match, output
    pid = int(match[1])
    if busy:
        guest.cmd('./cc', 'exec target=0 result=-13')
    guest.cmd(f'wait {pid}', f'wait target={pid} result={status}')
    data = guest.all[start:]
    check_execution(data, pid, status, expected)
    return {'pid': pid, 'status': status, 'command': command}, data

def programs():
    cases = []
    cases.append(('loop', 'int main(void) { int n=8; int sum=0; while(n>0) { sum=sum+n*n; n=n-1; } if(sum==204) print_int(sum*1234567); else print_int(-9); return 23; }\n', [str(sum(n*n for n in range(1,9))*1234567)], 23))
    cases.append(('scope', '/* unrelated spelling */ int main() {int a=7; {int a=19; print_int(a);} print_int(a); print_int(2+3*4); print_int((2+3)*4); if(!0) if(0) print_int(1); else print_int(8); return 0;}\n', ['19','7','14','20','8'], 0))
    cases.append(('text', 'int main() { puts("quote: \\\" slash: \\\\ tab:\\t utf8: 中文"); puts("int main"); puts(""); return 9; }\n', ['quote: " slash: \\ tab:\t utf8: 中文', 'int main', ''], 9))
    arithmetic = [(-9223372036854775807, 13), (-77, 9), (77, -9), (-77, -9), (1234567890123456789, 12345), (9,0), (-9223372036854775807-1,-1)]
    for index, (left,right) in enumerate(arithmetic):
        literal = '-9223372036854775807-1' if left == -(1<<63) else str(left)
        source = f'int main() {{ int left=({literal}); int right=({right}); print_int(left/right); print_int(left%right); print_int(left+right); print_int(left*right); print_int(left<=right); print_int(left!=right); return {index}; }}\n'
        expected = [divide(left,right), remainder(left,right), signed(left+right), signed(left*right), int(left<=right),int(left!=right)]
        cases.append((f'arith{index}',source,list(map(str,expected)),index))
    source = 'int main() { int x=0; if(x==0) {\n' + '\n'.join(f'x=x+{index};' for index in range(1,81)) + '\n} else x=999; print_int(x); return 71; }\n'
    cases.append(('pages', source, [str(sum(range(1,81)))], 71))
    cases.append(('equal', 'int main() { int original=8; int answer=0; while(original!=0){answer=answer+original*original; original=original+-1;} print_int(answer*1234567); return 23;} // same value\n', cases[0][2], 23))
    cases.append(('predicates','int main(){print_int(5>=5); print_int(5>=6); print_int(2==3); print_int(2!=3); print_int(3>4); print_int(2<=2); print_int(3<2); print_int(!!4); int x; int y; y=x=+17; print_int(x+y); return 255;}\n',['1','0','0','1','0','1','0','1','34'],255))
    prefix='int main(){print_int(123);return 0;} /*'
    source=prefix+'p'*(8192-len(prefix)-3)+'*/\n'
    assert len(source)==8192
    cases.append(('sourcecap',source,['123'],0))
    return cases

def main():
    records = []
    with tempfile.TemporaryDirectory(prefix='lesson14-runtime-',dir=os.environ.get('TMPDIR')) as temporary:
        disk = Path(temporary)/'disk.img'
        shutil.copyfile(BUILD/'disk.img', disk)
        boot = disk.read_bytes()[:512*512]
        guest = Guest('compiler-uart.log', disk)
        expected_files = {}
        try:
            guest.until('14> ')
            guest.cmd('abitest', 'PASS shell argv admission')
            rejected = guest.cmd('./math_test extra', 'exec target=0 result=-4')
            assert 'spawn pid=' not in rejected
            run(guest, './cc --probe', 0, ['PASS ABI2 owner, stack, workspace, staging and protected output'])
            run(guest, './math_test', 37)
            worker = guest.cmd('run exit 44')
            worker_pid = int(re.search(r'run target=3 result=(\d+)',worker)[1])
            guest.cmd(f'wait {worker_pid}',f'wait target={worker_pid} result=44')
            for name, source, expected, status in programs():
                normalized = source.encode()
                paste(guest, name+'.c', normalized)
                assert content(disk, name+'.c') == normalized
                compiler, _ = run(guest, f'./cc {name}.c {name}', 0, busy=True)
                generated = content(disk,name)
                header = native_header(generated)
                if name == 'pages':
                    assert header['code'] > 4096
                execution, _ = run(guest, './'+name, status, expected)
                records.append({'name':name,'compiler':compiler,'execution':execution,'header':header,'expected':expected})
                expected_files[name+'.c'] = normalized
                expected_files[name] = generated
            assert expected_files['loop'] != expected_files['equal']
            # Force independent compiler and native dispatch on hart0 by holding slot1.
            worker = guest.cmd('run spin 0')
            worker_pid = int(re.search(r'run target=1 result=(\d+)',worker)[1])
            run(guest, './cc loop.c even', 0)
            run(guest, './even', 23, programs()[0][2])
            guest.cmd(f'kill {worker_pid}')
            guest.cmd(f'wait {worker_pid}', f'wait target={worker_pid} result=137')
            # Every deterministic frontend failure preserves FULL old output and absence.
            invalid = [
                '', 'int main(){return ;}', 'int main(){double x;}',
                'int main(){print_int("x");}', 'int main(){puts(9);}',
                'int main(){missing=3;}', 'int main(){int x; int x;}',
                'int main(){ {int x=1;} return x;}', 'int main(){1=2;}',
                'int main(){return 9223372036854775808;}', 'int main(){return 1&2;}',
                'int main(){return 1.5;}', '#include <stdio.h>\nint main(){}',
                'int main(){puts("bad\\q");}', 'int main(){puts("bad);}',
                'int main(){/* nope', 'int main(){return 1;} int second(){}',
                'int main(){return '+'('*80+'1'+')'*80+';}',
                'int main(){'+'{'*33+';'+'}'*33+'}',
                'int main(){int '+('x'*32)+'=1;}',
                'int main(){'+''.join('int x%d=0;'%i for i in range(257))+'}',
                'int main(){ puts("'+('x'*1025)+'");}',
                'int main(){int x=0;'+''.join('x=x+1;' for _ in range(600))+'}',
                'int main(){'+';'*4100+'}',
                'int main(){return '+'1+'*200+'1;}',
            ]
            old = expected_files['loop']
            failures = []
            for index, bad in enumerate(invalid):
                name = f'bad{index}.c'
                # Empty raw bodies intentionally do not create files; an empty source
                # is created explicitly by the old shell command for this test only.
                if not bad:
                    guest.cmd('fwrite '+name)
                else:
                    paste(guest,name,bad.encode()+b'\n')
                before_source = content(disk,name)
                for output in ('loop','never'):
                    record, transcript = run(guest,f'./cc {name} {output}',1)
                    assert b'cc: line ' in transcript and b'published native' not in transcript
                    assert content(disk,'loop') == old
                    assert 'never' not in snapshot(disk)['files']
                    assert content(disk,name) == before_source
                    failures.append(record)
            paste(guest,'oversize.c',b' '*8191+b'\n')
            guest.cmd('fappend oversize.c x','fappend target=0 result=1')
            oversized_source=content(disk,'oversize.c')
            assert len(oversized_source)==8193
            for output in ('loop','never'):
                run(guest,f'./cc oversize.c {output}',3)
                check_saved(content(disk,'oversize.c'),oversized_source)
                check_saved(content(disk,'loop'),old)
                assert 'never' not in snapshot(disk)['files']
            run(guest,'./cc',2)
            run(guest,'./cc absent.c never',3)
            assert 'never' not in snapshot(disk)['files']
            run(guest,'./cc absent.c loop',3)
            assert content(disk,'loop') == old
            run(guest,'./cc loop.c loop.c',2)
            assert content(disk,'loop.c') == expected_files['loop.c']
            for protected in ('cc','math_test','math.dll'):
                before = content(disk,protected)
                run(guest,f'./cc loop.c {protected}',4)
                assert content(disk,protected) == before
            # Raw boundary/literal/framing cases. All sent as whole unpaced bursts.
            raw_cases = {
                'exact': b'x'*8191+b'\n',
                'literal': b'\t"quotes" \\slash UTF8:\xe4\xb8\xad\nEND14prefix\nxEND14\nEND14 tail\n',
                'longline': b'q'*7000+b'\n',
                'crlf': b'a\r\nb\rc\n',
            }
            for name,body in raw_cases.items():
                paste(guest,name,body)
                expected = body.replace(b'\r\n',b'\n').replace(b'\r',b'\n')
                assert content(disk,name) == expected
                expected_files[name] = expected
            paste(guest,'custom',b'END14\nEND14x\n',delimiter='ZZ')
            assert content(disk,'custom') == b'END14\nEND14x\n'
            paste(guest,'exact31',raw_cases['exact'],delimiter='D'*31)
            assert content(disk,'exact31') == raw_cases['exact']
            paste(guest,'empty',b'')
            assert 'empty' not in snapshot(disk)['files']
            for index,body in enumerate((b'x'*8192+b'\nshutdown\n', b'a\x00b\nshutdown\n', b'a\x1bb\nshutdown\n', b'a\x03b\nshutdown\n', b'a\x04b\nshutdown\n',b'a\x02b\nshutdown\n')):
                before = disk.read_bytes()
                paste(guest,'literal',body,success=False)
                assert disk.read_bytes() == before, 'rejected paste mutated disk'
                guest.cmd('echo resynchronized','echo: resynchronized')
            guest.cmd('echo ad\x1b[Db', 'echo: abd')
            guest.cmd('stats', 'value=0x0000000000000000')
            guest.shutdown()
        finally:
            guest.close()
        assert disk.read_bytes()[:512*512] == boot
        snapshot(disk)
        # A NEW QEMU process FIRST reads actual persisted source AND native bytes.
        # No formatter, seeder, compiler or same-value overwrite is run here.
        guest = Guest('compiler-cold.log',disk)
        try:
            guest.until('14> ')
            for name in ('loop.c','loop','literal','exact'):
                start = len(guest.all)
                guest.cmd('cat '+name, 'cat target=0 result=0')
                assert expected_files[name].replace(b'\n',b'\r\n') in guest.all[start:], 'cold guest bytes differ: '+name
            cold, _ = run(guest,'./loop',23,programs()[0][2])
            run(guest,'./arith6',6,programs()[9][2])
            guest.shutdown()
        finally:
            guest.close()
        final = snapshot(disk)
        for name,expected in expected_files.items():
            check_saved(final['files'][name]['content'], expected)
        assert disk.read_bytes()[:512*512] == boot
        shutil.copyfile(disk,BUILD/'compiler-verified.img')
        result = {'status':'PASS','programs':records,'negative_compiles':failures,'cold':cold,'raw_cases':list(raw_cases), 'filesystem':report(final)}
        (BUILD/'runtime-results.json').write_text(json.dumps(result,indent=2)+'\n')
    print('PASS guest-native compiler, independent full-int results, negative preservation, raw bounds and cold read-first execution')

if __name__ == '__main__':
    main()
