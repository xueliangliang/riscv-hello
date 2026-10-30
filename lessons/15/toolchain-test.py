#!/usr/bin/env python3
"""Prove selected CC actually produces fresh soft-float RV64 bytes before build."""
from pathlib import Path
import os
import shlex
import subprocess
import sys
import tempfile

cc = shlex.split(sys.argv[1])
machine = subprocess.check_output([*cc,'-dumpmachine'],text=True).strip()
assert machine.startswith('riscv64'), ('not a riscv64 compiler',machine)
with tempfile.TemporaryDirectory(prefix='lesson15-toolchain-',dir=os.environ.get('TMPDIR')) as temporary:
    directory = Path(temporary)
    source = directory/'probe.S'
    executable = directory/'probe.elf'
    source.write_text('.text\n.globl _start\n_start:\n li a0,0\n li a7,93\n ecall\n')
    subprocess.run([*cc,'-march=rv64imac_zicsr_zifencei','-mabi=lp64','-nostdlib','-static',
                    '-Wl,--build-id=none,-e,_start',str(source),'-o',str(executable)],check=True)
    assert executable.is_file() and executable.read_bytes().startswith(b'\x7fELF'), 'compiler produced no fresh ELF'
    header = subprocess.check_output(['riscv64-linux-gnu-readelf','-h','-A',str(executable)],text=True)
    assert 'soft-float ABI' in header
    subprocess.run(['qemu-riscv64','-cpu','rv64,f=false,d=false,zfa=false',str(executable)],check=True,timeout=10)
print('PASS selected CC produces fresh executable RV64/lp64 bytes, F/D disabled execution')
