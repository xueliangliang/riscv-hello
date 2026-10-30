"""Strict ctypes bridge to the actual lesson13 C filesystem/journal."""
import ctypes as c
from pathlib import Path
import subprocess

class Native:
    def __init__(self, image):
        target=Path('build/lesson13/storage.so')
        sources=[Path('lessons/13')/name for name in ('model.c','native-fs.c','journal.c','workload.c','snapshot.c')]
        if not target.exists() or any(p.stat().st_mtime>target.stat().st_mtime for p in sources+[Path("lessons/13/fs.c")]):
            subprocess.run(['cc','-shared','-fPIC','-O1','-Wall','-Wextra','-Werror','-Ilessons/13','-Ilessons/02',
                            *map(str,sources),'-o',str(target)],check=True)
        self.lib=c.CDLL(str(target.resolve()))
        signatures={
            'model_load':([c.c_void_p],None), 'model_disk':([c.c_void_p],None),
            'model_run':([c.c_uint],c.c_long),
            'model_trace_overflow':([],c.c_uint),
            'model_fault':([c.c_int,c.c_long,c.c_uint,c.c_int],None),
            'test_live_handles':([],c.c_uint),
            'fs_open':([c.c_char_p,c.c_uint],c.c_long),
            'fs_write':([c.c_long,c.c_void_p,c.c_uint],c.c_long),
            'fs_read':([c.c_long,c.c_void_p,c.c_uint],c.c_long),
            'fs_close':([c.c_long],c.c_long),
            'fs_remove':([c.c_char_p],c.c_long),
            'snapshot_read':([c.c_char_p,c.c_void_p,c.c_uint],c.c_long)}
        for name,(args,result) in signatures.items():
            fn=getattr(self.lib,name)
            fn.argtypes=args
            fn.restype=result
        data=Path(image).read_bytes()
        assert len(data)==8*1024*1024
        self.lib.model_load(data)
        assert self.lib.model_run(0)==0
        self.check()
    def check(self):
        assert not self.lib.model_trace_overflow(), 'native trace overflow'
    def put(self,name,data):
        h=self.lib.fs_open(name.encode(),1)
        assert h>=0,(name,h)
        try:
            for start in range(0,len(data),4096):
                part=data[start:start+4096]
                assert self.lib.fs_write(h,part,len(part))==len(part)
                self.check()
        finally:
            assert self.lib.fs_close(h)==0
        self.check()
    def save(self,path):
        self.check()
        out=c.create_string_buffer(8*1024*1024)
        self.lib.model_disk(out)
        Path(path).write_bytes(out.raw)
