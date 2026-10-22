#!/usr/bin/env python3
"""Export only the reviewed user ABI labels, from the independently linked ELF."""
import subprocess
import sys

names = {"interrupt_loop", "interrupt_loop_end", "start_ecall", "exit_ecall", "user_done"}
lines = subprocess.check_output([sys.argv[1], "-n", sys.argv[2]], text=True).splitlines()
found = {}
for line in lines:
    fields = line.split()
    if len(fields) == 3 and fields[2] in names:
        found[fields[2]] = int(fields[0], 16)
if found.keys() != names:
    raise SystemExit("missing user ABI symbols")
with open(sys.argv[3], "w") as output:
    for name, address in sorted(found.items()):
        output.write(f"#define U_{name.upper()} 0x{address:x}UL\n")
