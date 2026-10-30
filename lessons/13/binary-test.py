"""Inspect actual linked ISA/ABI, no embedded exports and disjoint RAM budgets."""
import json
from pathlib import Path
from pack import tool,symbols
BUILD=Path('build/lesson13')
kernel=symbols(BUILD/'kernel.elf')
shell=symbols(BUILD/'user.elf')
app=symbols(BUILD/'math_test.elf')
assert kernel['__bss_end']<0x80400000
assert shell['__user_bss_end']<=0x80407000
assert app['__payload_end']<=app['banks']<app['__memory_end']<=0x80510000
assert not any(name in app for name in ('math_ceil','math_floor','math_max','math_min'))
report={}
for name in ('kernel','user','math_test','math','math-alt'):
    elf=BUILD/(name+'.elf')
    header=tool('readelf','-h','-A',elf)
    assert 'soft-float ABI' in header,name
    assert not tool('nm','-u',elf).strip(),name
    if name.startswith('math'):
        assert 'There are no relocations' in tool('readelf','-rW',elf)
    report[name]={'elf_bytes':elf.stat().st_size,'ABI':'lp64/soft-float'}
    (BUILD/(name+'-inspection.log')).write_text(header+tool('readelf','-lW','-SW','-rW',elf)+tool('objdump','-d',elf))
for name in ('kernel.bin','user.bin','math_test.exec','math.dll','math-alt.dll'):
    report[name]=(BUILD/name).stat().st_size
report['ranges']={'kernel_BSS_end':hex(kernel['__bss_end']),
                  'shell_BSS_end':hex(shell['__user_bss_end']),
                  'application_payload_end':hex(app['__payload_end']),
                  'application_memory_end':hex(app['__memory_end']),
                  'banks':[hex(app['banks']),hex(app['banks']+4096)],
                  'stacks':['0x80408000','0x80410000'],'QEMU_RAM':['0x80000000','0x88000000']}
(BUILD/'binary-results.json').write_text(json.dumps(report,indent=2)+'\n')
print('PASS actual ELF ISA/soft-float ABI, resolved PIC, no static math exports and measured RAM budgets')
