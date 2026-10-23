set pagination off
set confirm off
set remotetimeout 10
hbreak supervisor_main
continue
delete breakpoints
maintenance flush dcache
break trap_dispatch if ((struct TrapFrame *)$a0)->cause == 0x8000000000000009 && ((struct Hart *)$tp)->slot == -1
continue
set $frame = (struct TrapFrame *)$a0
if (($frame->status & 0x100) != 0) || $frame->epc != $idle_pc
  echo FAIL: IRQ not from genuine U idle\n
  quit 1
end
if ((struct Hart *)$tp) != &harts[0] || processes[0].state != 6 || harts[1].slot != -1 || scheduler_owner == 0
  echo FAIL: trusted hart, blocked reader, or entry lock\n
  quit 1
end
if $frame->x[4] != 0x1d1e || *(struct Hart **)((char *)$frame + 288) != &harts[0] || $sscratch != 0
  echo FAIL: user tp or trusted stack metadata\n
  quit 1
end
printf "IRQ idle epc=%#lx user-tp=%#lx trusted-hart=%ld reader-state=%d\n", $frame->epc, $frame->x[4], ((struct Hart *)$tp)->id, processes[0].state
delete breakpoints
break restore_frame if read_wakes > 0 && ((struct Hart *)$tp)->slot == 0
continue
if external_irqs < 1 || read_wakes != 1 || processes[0].state != 2 || processes[0].owner != 0
  echo FAIL: actual IRQ enqueue/wakeup reservation\n
  quit 1
end
if (struct TrapFrame *)$a0 != &processes[0].frame || processes[0].frame.x[10] != 101 || scheduler_owner == 0
  echo FAIL: return character/frame or lock held\n
  quit 1
end
printf "IRQ count=%ld read-wakes=%ld return-byte=%ld lock-owner=%d\n", external_irqs, read_wakes, processes[0].frame.x[10], scheduler_owner
delete breakpoints
tbreak restore_user_return thread 1
continue
if $tp != processes[0].frame.x[4] || $sp != processes[0].frame.x[2] || $sscratch != harts[0].stack_top || ($sstatus & 0x102) != 0
  echo FAIL: restored user tp/SP/sscratch/SIE\n
  quit 1
end
printf "PASS: GDB real idle UART IRQ -> blocked read wake -> U return sp=%#lx tp=%#lx sscratch=%#lx\n", $sp, $tp, $sscratch
detach
quit 0
