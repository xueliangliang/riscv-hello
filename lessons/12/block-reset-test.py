#!/usr/bin/env python3
"""Run real driver control flow with explicit native MMIO/time substitution.
The reset timeout cannot be induced by stock QEMU. This shim checks ownership
ordering and failed-init quarantine; recovery-test.py separately uses real MMIO.
"""
import os
from pathlib import Path
import re
import subprocess

BUILD = Path('build/lesson12')


def replace_once(source, before, after):
    assert source.count(before) == 1, ('driver transport seam changed', before)
    return source.replace(before, after)


def main():
    source = Path('lessons/12/block.c').read_text()
    source = replace_once(source, '    unsigned long value;\n    __asm__ volatile("rdtime %0" : "=r"(value));\n    return value;',
                          '    return test_clock();')
    source = replace_once(source, 'return device_registers[offset / sizeof(uint32_t)];', 'return test_read(offset);')
    source = replace_once(source, 'device_registers[offset / sizeof(uint32_t)] = value;', 'test_write(offset, value);')
    source = re.sub(r'__asm__ volatile\("fence [^"]*" ::: "memory"\);',
                    '__asm__ volatile("" ::: "memory");', source)
    BUILD.mkdir(parents=True, exist_ok=True)
    (BUILD / 'block-reset-driver.c').write_text(source)
    executable = BUILD / 'block-reset-test'
    subprocess.run([os.environ.get('HOSTCC', 'cc'), '-D_GNU_SOURCE', '-std=c11',
                    '-O1', '-g', '-Wall', '-Wextra', '-Werror', '-Ilessons/02',
                    '-Ilessons/12', '-I' + str(BUILD), 'lessons/12/block-reset-test.c',
                    '-o', str(executable)], check=True)
    completed = subprocess.run([str(executable)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (BUILD / 'block-reset-test.log').write_bytes(completed.stdout)
    print(completed.stdout.decode(), end='')
    assert completed.returncode == 0, completed.returncode


if __name__ == '__main__':
    main()
