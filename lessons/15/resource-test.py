#!/usr/bin/env python3
"""Measured linked bounds; no broad-RAM admission or heap-growth claims."""
from pathlib import Path
import json
import os
import struct
import subprocess

BUILD=Path('build/lesson15')
prefix=os.environ.get('CROSS_COMPILE','riscv64-linux-gnu-')

def symbols(name):
    text=subprocess.check_output([prefix+'nm','-n',str(BUILD/(name+'.elf'))],text=True)
    assert not subprocess.check_output([prefix+'nm','-u',str(BUILD/(name+'.elf'))]).strip()
    return {parts[2]:int(parts[0],16) for line in text.splitlines() if len(parts:=line.split())==3}

kernel=symbols('kernel')
shell=symbols('user')
compiler=symbols('cc')
boot=symbols('bootloader')
legacy=symbols('math_test')
runtime=symbols('runtime15')
assert runtime['__runtime_bss_begin']==0x80510000
assert runtime['__runtime_payload_end']<=0x80505000
assert runtime['__runtime_bss_end']<=0x80600000
assert runtime['banks']>=0x80510000
assert runtime['banks']+8192<=runtime['__runtime_bss_end']
assert kernel['__bss_end']<0x80400000
assert shell['__user_bss_end']<=0x80407000
assert shell['__taskdata_end']<=0x80408000
assert shell['__user_stacks_end']==0x80410000
assert shell['__app_stack_end']==0x80420000
assert shell['__paste_end']<=0x80424000<0x80500000
assert compiler['__memory_end']<=0x80600000
assert compiler['__payload_end']-0x80500000+48<=65536
assert compiler['__compiler_bss_start']==compiler['__payload_end']
assert kernel['machine_stacks']+8192==kernel['supervisor_stacks']
assert kernel['supervisor_stacks']+32768<=kernel['__bss_end']
assert legacy['__payload_end']<=legacy['banks']<legacy['__memory_end']<=0x80510000
stack_usage={}
for line in (BUILD/'cc.su').read_text().splitlines():
    name,size,kind=line.split('\t')
    assert kind=='static', 'unbounded compiler stack'
    stack_usage[name.rsplit(':',1)[1]]=int(size)
maximum=max(stack_usage.values())
# Deliberately pessimistic sum: parser/statement/codegen phases do not actually
# coexist, but counting all their depth caps still fits the private stack.
conservative_stack=(64+64+128)*maximum+4096
assert conservative_stack<65536
assert 2048+128*16+48<65536
files={name:(BUILD/name).stat().st_size for name in ('kernel.bin','user.bin','cc.exec','integer-runtime.raw','math_test.exec','math.dll','c_runtime')}
for name in ('kernel.bin','user.bin','cc.exec'):
    assert files[name]<=65536
for name in ('cc','integer-runtime','runtime15','kernel','math'):
    attributes=subprocess.check_output([prefix+'readelf','-A',str(BUILD/(name+'.elf'))],text=True)
    arch=next(line for line in attributes.splitlines() if 'Tag_RISCV_arch:' in line)
    assert '_f' not in arch and '_d' not in arch,arch
    assert 'soft-float ABI' in subprocess.check_output([prefix+'readelf','-h',str(BUILD/(name+'.elf'))],text=True)
import re
for name in ('cc','runtime15','math','kernel'):
    assembly=subprocess.check_output([prefix+'objdump','-d',str(BUILD/(name+'.elf'))],text=True)
    assert not re.search(r'\t(?:f(?:add|sub|mul|div|sqrt|cvt|mv|eq|lt|le|class|sgnj|lw|ld|sw|sd)|fl[wd]|fs[wd])\.',assembly),name
result={'status':'PASS','file_bytes':files,
        'boot_bss':[hex(boot['__bss_start']),hex(boot['__bss_end'])],
        'boot_stack':[hex(boot['__stack_bottom']),hex(boot['__stack_top'])],
        'kernel_bss':[hex(kernel['__bss_start']),hex(kernel['__bss_end'])],
        'machine_stacks':[[hex(kernel['machine_stacks']+hart*4096),hex(kernel['machine_stacks']+(hart+1)*4096)] for hart in range(2)],
        'supervisor_stacks':[[hex(kernel['supervisor_stacks']+hart*16384),hex(kernel['supervisor_stacks']+(hart+1)*16384)] for hart in range(2)],
        'idle_stacks':[[hex(kernel['idle_stacks']+hart*256),hex(kernel['idle_stacks']+(hart+1)*256)] for hart in range(2)],
        'file_staging':[hex(kernel['file_staging']),hex(kernel['file_staging']+65536)],
        'RX_ring':[hex(kernel['rx_ring']),hex(kernel['rx_ring']+16384)],
        'shell_low_bss':[hex(shell['__user_bss_start']),hex(shell['__user_bss_end'])],
        'shell_workspace':['0x80420000',hex(shell['__paste_end']),'limit=0x80424000'],
        'compiler_bss':[hex(compiler['__compiler_bss_start']),hex(compiler['__compiler_bss_end'])],
        'compiler_memory_bytes':compiler['__memory_end']-0x80500000,
        'runtime_bss':[hex(runtime['__runtime_bss_begin']),hex(runtime['__runtime_bss_end'])],
        'runtime_functions':[hex(runtime['__functions_begin']),hex(runtime['__functions_end'])],
        'runtime_module_banks':[hex(runtime['banks']),hex(runtime['banks']+8192)],
        'runtime_prefix_bytes':20480,
        'generated_code_region_bytes':32768,
        'generated_strings_base':'0x8050d000',
        'legacy_application_bss':[hex(legacy['__payload_end']),hex(legacy['__memory_end'])],
        'legacy_module_banks':[hex(legacy['banks']),hex(legacy['banks']+8192)],
        'per_slot_data':['0x80407000','0x80407800'],
        'legacy_stacks':['0x80408000','0x80410000'],
        'per_slot_stacks':[[hex(0x80408000+slot*4096),hex(0x80408000+(slot+1)*4096)] for slot in range(8)],
        'ABI2_stack':['0x80410000','0x80420000'],
        'compiler_stack_usage':stack_usage,
        'pessimistic_static_stack_bound':conservative_stack,
        'generated_stack_bound':2048+128*16+48}
(BUILD/'resource-results.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
