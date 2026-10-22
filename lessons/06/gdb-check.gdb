# Start QEMU with the README -S/-gdb command first, then:
# gdb-multiarch -q -batch -x lessons/06/gdb-check.gdb
set pagination off
set confirm off
file build/lesson06/kernel.elf
add-symbol-file build/lesson06/user.elf
target remote 127.0.0.1:12346
hbreak timer_interrupt
continue
info registers priv scause sepc sstatus sscratch sp sie
python
import gdb
frame = gdb.parse_and_eval("*frame")
saved_regs = [int(frame["x"][i]) for i in range(32)]
saved_pc = int(frame["epc"])
assert int(gdb.parse_and_eval("$priv")) == 1
assert int(frame["cause"]) == 0x8000000000000005
assert int(frame["status"]) & 0x102 == 0
assert int(gdb.parse_and_eval("$sscratch")) == 0
assert saved_regs[2] == 0x80410000
assert int(gdb.parse_and_eval("&interrupt_loop")) <= saved_pc < int(gdb.parse_and_eval("&interrupt_loop_end"))
print("GDB: captured asynchronous U frame at PC=%#x, SP=%#x" % (saved_pc, saved_regs[2]))
end
delete breakpoints
hbreak restore_user_return
continue
info registers priv sepc sstatus sscratch sp
python
assert int(gdb.parse_and_eval("$sepc")) == saved_pc
assert int(gdb.parse_and_eval("$priv")) == 1
for i in range(1, 32):
    actual = int(gdb.parse_and_eval("$x%d" % i)) & ((1 << 64) - 1)
    assert actual == saved_regs[i], "x%d: %#x != %#x" % (i, actual, saved_regs[i])
print("GDB: all 31 writable integer registers restored exactly before sret")
end
delete breakpoints
# Break at the actual saved U address, not a hardcoded loop instruction.
# Some QEMU/GDB combinations run through SRET on a remote single-step.
hbreak *$sepc
continue
info registers priv pc sp
python
assert int(gdb.parse_and_eval("$priv")) == 0
assert int(gdb.parse_and_eval("$pc")) == saved_pc
assert int(gdb.parse_and_eval("$sp")) == saved_regs[2]
print("GDB PASS: sret resumed U at the exact interrupted PC, no +4")
end
delete breakpoints
continue
