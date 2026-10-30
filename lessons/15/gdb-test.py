#!/usr/bin/env python3
"""Real GDB: compiler and freshly emitted native U entry, exact bytes, both harts."""
from pathlib import Path
import os
import re
import shutil
import socket
import tempfile
from debugger import DebuggerSession
from guest import Guest
from run import command


def check_gdb_output(output):
    entries = re.findall(rb'U NATIVE ENTRY name=(cc|native) hart=([01]) pc=(0x[0-9a-f]+) priv=0 exact_payload=(\d+)', output)
    assert [(name.decode(),int(hart)) for name,hart,pc,size in entries] == [('cc',1),('native',1),('cc',0),('native',0)]
    assert re.findall(rb'RECEIVER FENCE hart=([01])',output) == [b'1',b'1',b'0',b'0']
    compiler_size = Path('build/lesson15/cc.exec').stat().st_size - 48
    assert all(int(size)==compiler_size for name,hart,pc,size in entries if name==b'cc')
    assert all(pc==b'0x80500000' for name,hart,pc,size in entries if name==b'cc')
    assert all(int(size)>=32768 and pc==b'0x80505000' for name,hart,pc,size in entries if name==b'native')
    assert re.findall(rb'ATOMIC INTEGER LINE hart=([01]) exact_write=33333\+LF',output)==[b'1',b'0']
    assert output.count(b'ADMISSION REJECT entire_1MiB_unchanged states_unchanged') == 6
    assert re.findall(rb'ACTUAL DLL EXPORT hart=([01]) argument=0x400a000000000000', output) == [b'1', b'0']
    assert re.findall(rb'RUNTIME MODULE FENCE hart=([01])', output) == [b'1', b'0']
    assert b'PASS GDB: actual compiler and emitted program U entries' in output


def main():
    with DebuggerSession('build/lesson15/gdb-loader.log') as session:
        with tempfile.TemporaryDirectory(prefix='lesson15-gdb-',dir=os.environ.get('TMPDIR')) as temporary:
            directory=Path(temporary)
            disk=directory/'disk.img'
            shutil.copyfile('build/lesson15/disk.img',disk)
            import struct
            from native import Native
            from vectors import u32
            runtime=Path('build/lesson15/c_runtime').read_bytes()
            payload=53248
            fixture=struct.pack('<8s10I',b'RVEXEC1\0',1,48+payload,payload,20480,
                                0x80500000,int.from_bytes(runtime[36:40],'little'),3,20484,0,0)
            fixture+=runtime+bytes(payload-len(runtime))
            malformed=[u32(fixture,32,4),u32(fixture,20,256),u32(fixture,44,1),
                       u32(fixture,48+8,2),u32(fixture,48+68,2),u32(fixture,48+64,20480)]
            fs=Native(disk)
            for index,image in enumerate(malformed):
                fs.put('bad'+str(index),image)
            fs.save(disk)
            with socket.socket() as sock:
                sock.bind(('127.0.0.1',0))
                port=sock.getsockname()[1]
            from pack import symbols
            runtime_symbols = symbols('build/lesson15/runtime15.elf')
            script=directory/'compiler.gdb'
            script.write_text(f'''set pagination off
set confirm off
set remotetimeout 10
file build/lesson15/kernel.elf
target remote 127.0.0.1:{port}
python
import gdb,sys,struct
from pathlib import Path
sys.path.insert(0,str(Path('lessons/15').resolve()))
from decode import decode
fences=[]
receivers=[]
entries=[]
exports=[]
module_fences=[]
rejections=[]
integer_writes=[]
admission_bytes=None
admission_states=None
installed=set()
pending=None
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
            print('RECEIVER FENCE hart=%d'%hart)
            print(text)
            fences.append(hart)
            return False
        except Exception as error:
            failure=error
            return True
class NativeEntry(gdb.Breakpoint):
    def stop(self):
        global pending,failure
        try:
            if pending is None:
                return False
            hart,name,image,pc=pending
            if integer('$pc') != pc:
                return False
            assert integer('$priv')==0
            assert memory(0x80500000,len(image)-48)==image[48:]
            assert integer('$sp')==0x80420000
            if name=='cc':
                assert integer('$a0')==3
                argv=integer('$a1')
                assert 0x80407000 <= argv < 0x80407800
                pointers=struct.unpack('<4Q',memory(argv,32))
                assert pointers[3]==0
                assert memory(pointers[0],3)==b'cc\\0'
                assert memory(pointers[1],6)==b'gdb.c\\0'
                assert memory(pointers[2],7)==b'native\\0'
            else:
                assert integer('$a0')==2
                argv=integer('$a1')
                assert 0x80407000 <= argv < 0x80407800
                pointers=struct.unpack('<3Q',memory(argv,24))
                assert pointers[2]==0 and memory(pointers[0],7)==b'native\\0'
                assert memory(pointers[1],7)==b'copied\\0'
                memory_size=int.from_bytes(image[28:32],'little')
                payload_size=len(image)-48
                assert memory(0x80500000+payload_size,memory_size-payload_size)==bytes(memory_size-payload_size)
            print('U NATIVE ENTRY name=%s hart=%d pc=%#x priv=0 exact_payload=%d'%(name,hart,pc,len(image)-48))
            print(gdb.execute('x/8i $pc',to_string=True))
            entries.append((name,hart))
            pending=None
            return False
        except Exception as error:
            failure=error
            return True
class Received(gdb.Breakpoint):
    def stop(self):
        global pending,failure
        try:
            hart=integer('$a0')
            pc=integer('$a1')
            assert fences and fences[-1]==hart
            name='cc' if len(receivers)%2==0 else 'native'
            image=decode({str(disk)!r})[name]['content']
            assert pc==0x80500000+int.from_bytes(image[20:24],'little')
            assert memory(0x80500000,len(image)-48)==image[48:]
            pending=(hart,name,image,pc)
            receivers.append((name,hart))
            if pc not in installed:
                NativeEntry('*%#x'%pc,type=gdb.BP_HARDWARE_BREAKPOINT,internal=True)
                installed.add(pc)
            print('AFTER RECEIVING FENCE name=%s hart=%d entry=%#x'%(name,hart,pc))
            return False
        except Exception as error:
            failure=error
            return True
class ProgramWrite(gdb.Breakpoint):
    def stop(self):
        global failure
        try:
            if not entries or entries[-1][0]!='native':
                return False
            hart=entries[-1][1]
            if hart in integer_writes:
                return False
            pointer=integer('$a0')
            length=integer('$a1')
            assert length==6 and memory(pointer,length)==b'33333\\n', ('non-atomic integer line',length,memory(pointer,length))
            integer_writes.append(hart)
            print('ATOMIC INTEGER LINE hart=%d exact_write=33333+LF'%hart)
            return False
        except Exception as error:
            failure=error
            return True
ProgramWrite('application_write',internal=True)
class Admission(gdb.Breakpoint):
    def stop(self):
        global admission_bytes,admission_states,failure
        try:
            admission_bytes=memory(0x80500000,1048576)
            admission_states=[integer('processes[%d].state'%slot) for slot in range(8)]
            return False
        except Exception as error:
            failure=error
            return True
class Rejected(gdb.Breakpoint):
    def stop(self):
        global failure
        try:
            assert integer('file_slot') == -1
            assert memory(0x80500000,1048576)==admission_bytes
            assert [integer('processes[%d].state'%slot) for slot in range(8)]==admission_states
            rejections.append(1)
            print('ADMISSION REJECT entire_1MiB_unchanged states_unchanged')
            return False
        except Exception as error:
            failure=error
            return True
Admission('application_admission_begin',internal=True)
Rejected('application_rejected',internal=True)
class ModuleFence(gdb.Breakpoint):
    def stop(self):
        global failure
        try:
            if not entries or entries[-1][0]!='native':
                return False
            hart=entries[-1][1]
            assert 'fence.i' in gdb.execute('x/5i $pc',to_string=True)
            module_fences.append(hart)
            print('RUNTIME MODULE FENCE hart=%d'%hart)
            return False
        except Exception as error:
            failure=error
            return True
class Export(gdb.Breakpoint):
    def stop(self):
        global failure
        try:
            hart=entries[-1][1]
            assert integer('$priv')==0
            assert integer('$a0')==0x400a000000000000
            print('ACTUAL DLL EXPORT hart=%d argument=%#x'%(hart,integer('$a0')))
            print(gdb.execute('x/8i $pc',to_string=True))
            exports.append(hart)
            return len(exports)==2
        except Exception as error:
            failure=error
            return True
class Dispatch(gdb.Breakpoint):
    def stop(self):
        global failure
        try:
            if not entries or entries[-1][0]!='native':
                return False
            target=integer('$a0')
            assert integer('$a1')==1
            banks={runtime_symbols['banks']}
            assert banks <= target < banks+8192
            dll=decode({str(disk)!r})['math.dll']['content']
            offset=int.from_bytes(dll[48:52],'little')
            assert memory(target,16)==dll[offset:offset+16]
            if target not in installed:
                Export('*%#x'%target,type=gdb.BP_HARDWARE_BREAKPOINT,internal=True)
                installed.add(target)
            print('VALIDATED API DISPATCH target=%#x'%target)
            return False
        except Exception as error:
            failure=error
            return True
ModuleFence('*{runtime_symbols['module_fence']:#x}',internal=True)
Dispatch('*{runtime_symbols['runtime_math_dispatch']:#x}',internal=True)
Fence('application_fence',internal=True)
Received('application_received',internal=True)
end
continue
python
assert failure is None,str(failure)
assert entries==[('cc',1),('native',1),('cc',0),('native',0)],entries
assert receivers==entries
assert fences==[1,1,0,0]
assert exports==[1,0] and module_fences==[1,0]
assert len(rejections)==6
assert integer_writes==[1,0]
print('PASS GDB: actual compiler and emitted program U entries, exact persisted payload, argv and both receiving-hart fences')
end
detach
quit
''')
            guest=Guest('gdb-uart.log',str(disk),options=command(disk)+['-S','-gdb',f'tcp:127.0.0.1:{port}'])
            try:
                session.start([os.environ.get('GDB','gdb-multiarch'),'-q','-batch','-x',str(script)])
                guest.until('15> ',10)
                for index in range(6):
                    guest.cmd('./bad'+str(index),'exec target=0 result=-4')
                guest.send('fappend gdb.c <<EOF\r\nint main(){int a=9; while(a>3){a=a-1;} print_int(a*11111); print_bits(ceil(3.25)); return 26;}\r\nEOF\r\n')
                guest.until('raw target=0 result=')
                guest.read()
                for index in range(2):
                    result=guest.cmd('./cc gdb.c native')
                    match=re.search(r'exec target=0 result=(\d+)',result)
                    assert match,result
                    pid=int(match[1])
                    guest.cmd(f'wait {pid}',f'wait target={pid} result=0')
                    result=guest.cmd('./native copied')
                    match=re.search(r'exec target=0 result=(\d+)',result)
                    assert match,result
                    pid=int(match[1])
                    if index==1:
                        output=session.collect(timeout=20)
                        assert session.process.returncode==0,output
                        check_gdb_output(output)
                        for before,after in ((b'hart=1',b'hart=0'),(b'priv=0',b'priv=1'),
                                             (b'pc=0x80505000',b'pc=0x80505004'),
                                             (b'exact_payload=53264',b'exact_payload=0')):
                            assert before in output
                            try:
                                check_gdb_output(output.replace(before,after))
                            except AssertionError:
                                pass
                            else:
                                raise AssertionError('captured debugger mutant accepted')
                    guest.cmd(f'wait {pid}',f'wait target={pid} result=26')
                    assert b'33333\r\n' in guest.all
                    if index==0:
                        result=guest.cmd('run spin 0')
                        worker=int(re.search(r'run target=1 result=(\d+)',result)[1])
                guest.cmd(f'kill {worker}')
                guest.cmd(f'wait {worker}',f'wait target={worker} result=137')
                guest.cmd('echo debugger-continued','echo: debugger-continued')
                guest.shutdown()
            finally:
                guest.close()
    print('PASS real GDB guest compiler/native U entries, both local fences, exact payload/argv and continued shutdown')

if __name__=='__main__':
    main()
