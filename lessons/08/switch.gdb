set pagination off
set confirm off
set breakpoint pending off
set schedule-multiple on
set scheduler-locking off
# Install instruction-aware breakpoints only AFTER the loader populated text.
# Before disk boot, those addresses contain zero, not the linked instructions.
hbreak *_start
continue
delete breakpoints
maintenance flush dcache
python
import gdb

class TimerFrame(gdb.Breakpoint):
    def __init__(self):
        # Do not auto-step over a breakpoint on sret. GDB's software-step
        # predictor may choose pc+4, resume only one CPU, and deadlock on a
        # remote-held lock. Filter on the ordinary mv at restore_frame first.
        super().__init__("*restore_frame")

    def stop(self):
        hart = int(gdb.parse_and_eval("$mhartid"))
        target = int(gdb.parse_and_eval("$target_hart"))
        frame = gdb.parse_and_eval("*(struct TrapFrame *)$a0")
        return (hart == target and int(frame["x"][4]) == 0xdeadbeef
                and int(frame["x"][8]) > 0
                and int(frame["cause"]) == ((1 << 63) | 5))

probe = TimerFrame()
end
continue
python
hart = int(gdb.parse_and_eval("$mhartid"))
assert hart == int(gdb.parse_and_eval("$target_hart"))
probe.delete()
# Thread-specific software breakpoints are still inserted on BOTH CPUs.
# A non-target hart hitting sret makes GDB step only that CPU toward pc+4,
# which sret never reaches; the target remains stopped before its epilogue.
# This selected frame is already unlocked, and restore_frame -> sret is
# straight-line assembly with no lock acquisition. Run only this hart until
# the one-shot; detach below resumes BOTH CPUs for the full runtime oracle.
gdb.execute("set scheduler-locking on")
thread = gdb.selected_thread().global_num
gdb.execute(f"tbreak *restore_user_return thread {thread}")
end
continue
python
def reg(name):
    return int(gdb.parse_and_eval("$" + name))
gdb.write("GDB CSR snapshot: " + repr({name: str(gdb.parse_and_eval("$" + name)) for name in ("mhartid", "priv", "tp", "sp", "sepc", "sstatus", "sscratch", "pmpcfg0", "menvcfg", "mcounteren", "mideleg", "sie", "stimecmp", "mscratch", "medeleg", "satp")}) + "\n")
gdb.write("GDB scheduler lock: " + str(gdb.parse_and_eval("scheduler_lock")) + "\n")
assert reg("mhartid") == hart
slot = int(gdb.parse_and_eval(f"harts[{hart}].slot"))
assert slot in (1, 2) and slot % 2 == hart
proc = gdb.parse_and_eval(f"processes[{slot}]")
assert int(proc["state"]) == 2 and int(proc["owner"]) == hart
assert int(proc["frame"]["cause"]) == ((1 << 63) | 5)
assert reg("priv") == 1 and reg("tp") == 0xdeadbeef
assert reg("sepc") == int(proc["frame"]["epc"])
assert 0x80408000 + slot * 4096 <= reg("sp") <= 0x80408000 + (slot + 1) * 4096
assert reg("sp") == int(proc["frame"]["x"][2])
assert reg("a3") == 0x12345 and reg("s2") == 0x54321
assert reg("sstatus") & (256 | 32 | 2) == 32
stack_top = int(gdb.parse_and_eval(f"harts[{hart}].stack_top"))
assert reg("sscratch") == stack_top
assert int(gdb.parse_and_eval(f"*(unsigned long *){stack_top}")) == int(gdb.parse_and_eval(f"&harts[{hart}]"))
# Another hart may already hold the released global lock at this breakpoint.
assert int(gdb.parse_and_eval("scheduler_owner")) != hart
assert reg("pmpcfg0") & 31 == 31
assert reg("menvcfg") & (1 << 63)
assert reg("mcounteren") & 2 and reg("mideleg") & 32
assert reg("sie") & 32
# This QEMU's GDB XML omits stimecmp; inspect local deadline plus real STIP.
assert int(gdb.parse_and_eval(f"harts[{hart}].deadline")) > 0
assert reg("mscratch") == int(gdb.parse_and_eval("&machine_stacks")) + (hart + 1) * 4096
assert reg("medeleg") & 0x104 == 0x104
assert reg("satp") == 0
gdb.write(f"PASS: GDB hart={hart} timer restoration, user tp, own SP/sscratch, unlocked sret and local privilege configuration.\n")
end
# Detach resumes both CPUs, without GDB trying to software-step over sret.
detach
quit 0
