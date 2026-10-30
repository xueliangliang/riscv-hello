#!/usr/bin/env python3
"""Real GDB: receiving-hart fence, U entry and executed module pointer bytes."""
import os
from pathlib import Path
import shutil
import socket
import tempfile
from debugger import DebuggerSession
from guest import Guest
from run import command


def main():
    with DebuggerSession('build/lesson13/gdb-loader.log') as session:
        with tempfile.TemporaryDirectory(prefix='lesson13-gdb-',dir=os.environ.get('TMPDIR')) as temp:
            directory=Path(temp)
            disk=directory/'disk.img'
            shutil.copyfile('build/lesson13/disk.img',disk)
            with socket.socket() as sock:
                sock.bind(('127.0.0.1',0))
                port=sock.getsockname()[1]
            dll=Path('build/lesson13/math.dll').read_bytes()
            script=directory/'loader.gdb'
            script.write_text(f'''set pagination off
set confirm off
set remotetimeout 10
file build/lesson13/kernel.elf
add-symbol-file build/lesson13/math_test.elf
 target remote 127.0.0.1:{port}
python
import gdb
image=bytes.fromhex({dll.hex()!r})
fences=[]
receivers=[]
entries=0
module_entries=0
module_fences=0
calls=[]
installed=set()
failure=None
def integer(expression):
    return int(gdb.parse_and_eval(expression))
def memory(address,size):
    return bytes(gdb.selected_inferior().read_memory(address,size))
class Fence(gdb.Breakpoint):
    def stop(self):
        global failure
        try:
            hart=integer('((struct Hart *)$tp)->id')
            text=gdb.execute('disassemble application_fence',to_string=True)
            assert 'fence.i' in text
            print('RECEIVER FENCE hart=%d pc=%#x'%(hart,integer('$pc')))
            print(text)
            fences.append(hart)
            return False
        except Exception as error:
            failure=error
            return True
class Received(gdb.Breakpoint):
    def stop(self):
        global failure
        try:
            hart=integer('$a0')
            pc=integer('$a1')
            assert fences and fences[-1]==hart
            assert pc==0x80500000
            receivers.append(hart)
            print('AFTER FENCE hart=%d entry=%#x'%(hart,pc))
            return False
        except Exception as error:
            failure=error
            return True
class Entry(gdb.Breakpoint):
    def stop(self):
        global entries,failure
        try:
            assert integer('$pc')==0x80500000
            assert integer('$priv')==0
            entries+=1
            print('U APP ENTRY pc=%#x priv=0'%integer('$pc'))
            print(gdb.execute('x/4i $pc',to_string=True))
            return False
        except Exception as error:
            failure=error
            return True
class ModuleFence(gdb.Breakpoint):
    def stop(self):
        global module_fences,failure
        try:
            assert integer('$priv')==0
            text=gdb.execute('disassemble module_fence',to_string=True)
            assert 'fence.i' in text
            module_fences+=1
            print('U LOCAL MODULE FENCE')
            print(text)
            return False
        except Exception as error:
            failure=error
            return True
class ModuleEntry(gdb.Breakpoint):
    def stop(self):
        global module_entries,failure
        try:
            assert integer('$priv')==0
            module_entries+=1
            print('U MODULE ENTRY pc=%#x priv=0'%integer('$pc'))
            print(gdb.execute('x/4i $pc',to_string=True))
            return False
        except Exception as error:
            failure=error
            return True
class Called(gdb.Breakpoint):
    def stop(self):
        global failure
        try:
            base=integer('$a0')
            pointer=integer('$a1')
            result=integer('$a2')
            assert integer('$priv')==0
            assert module_fences>0
            assert memory(base,len(image))==image,'loaded module differs from FS file'
            table=int.from_bytes(image[16:20],'little')
            offsets=[int.from_bytes(image[table+i*24+16:table+i*24+20],'little') for i in range(4)]
            assert pointer-base in offsets
            assert memory(pointer,2)==image[pointer-base:pointer-base+2]
            if pointer not in installed:
                installed.add(pointer)
                ModuleEntry('*%#x'%pointer,type=gdb.BP_HARDWARE_BREAKPOINT,internal=True)
                print('ACTUAL SYMBOL base=%#x pointer=%#x offset=%#x result=%#x'%(base,pointer,pointer-base,result))
                print(gdb.execute('x/8bx %#x'%pointer,to_string=True))
            calls.append((base,pointer))
            return len(entries_seen())==2 and entries>=2 and module_entries>=2 and len(set(b for b,p in calls))==2
        except Exception as error:
            failure=error
            return True
def entries_seen():
    return set(receivers)
Fence('application_fence',internal=True)
Received('application_received',internal=True)
Entry('*0x80500000',type=gdb.BP_HARDWARE_BREAKPOINT,internal=True)
ModuleFence('module_fence',type=gdb.BP_HARDWARE_BREAKPOINT,internal=True)
Called('module_call_checkpoint',type=gdb.BP_HARDWARE_BREAKPOINT,internal=True)
end
continue
python
assert failure is None,str(failure)
assert set(receivers)=={{0,1}},receivers
assert entries>=2 and module_entries>=2 and module_fences>=4
assert len(set(b for b,p in calls))==2
assert set(fences)=={{0,1}}
print('PASS GDB: receiving-hart fence and U application/module entry, pointer offset and exact loaded bytes')
end
detach
quit
'''.replace('\n target remote','\ntarget remote'))
            g=Guest('gdb-uart.log',str(disk),options=command(disk)+['-S','-gdb',f'tcp:127.0.0.1:{port}'])
            try:
                session.start([os.environ.get('GDB','gdb-multiarch'),'-q','-batch','-x',str(script)])
                g.until('13> ',10)
                g.cmd('./math_test','exec target=0 result=17')
                g.cmd('wait 17','wait target=17 result=37')
                g.cmd('run spin 0','run target=1 result=33')
                g.cmd('./math_test','exec target=0 result=18')
                output=session.collect(timeout=20)
                assert session.process.returncode==0,output
                assert b'PASS GDB: receiving-hart fence' in output,output
                g.cmd('wait 18','wait target=18 result=37')
                g.cmd('kill 33')
                g.cmd('wait 33','wait target=33 result=137')
                g.cmd('echo debugger-continued','echo: debugger-continued')
                g.shutdown()
            finally:
                g.close()
    print('PASS real GDB loader checkpoint and continued UART shutdown')

if __name__=='__main__':
    main()
