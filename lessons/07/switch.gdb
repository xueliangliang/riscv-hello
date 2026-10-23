set pagination off
set confirm off
# The Python runner has loaded kernel.elf and attached to the stopped QEMU.
break *trap_dispatch if current == 1 && processes[2].timer_hits >= 1 && ((struct TrapFrame *)$a0)->cause == 0x8000000000000005
continue
set $oldsp = ((struct TrapFrame *)$a0)->x[2]
set $oldpc = ((struct TrapFrame *)$a0)->epc
printf "A interrupted: pid=%ld pc=%#lx sp=%#lx\n", processes[1].pid, $oldpc, $oldsp
tbreak restore_frame
continue
if current != 2 || $a0 != (unsigned long)&processes[2].frame
    echo FAIL: scheduler did not select B's saved frame\n
    quit 1
end
set $newsp = processes[2].frame.x[2]
set $newpc = processes[2].frame.epc
if $newsp == $oldsp
    echo FAIL: stacks not independent\n
    quit 1
end
printf "B selected: pid=%ld frame=%#lx pc=%#lx sp=%#lx\n", processes[2].pid, $a0, $newpc, $newsp
tbreak restore_user_return
continue
if $sp != $newsp || $sepc != $newpc || ($sstatus & 256) != 0
    echo FAIL: actual epilogue did not restore B\n
    quit 1
end
printf "PASS: GDB observed A timer trap -> B frame -> B SP/sepc at sret.\n"
detach
quit 0
