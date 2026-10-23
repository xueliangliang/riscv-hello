import subprocess
import sys
from pathlib import Path
symbols = {}
for line in subprocess.check_output([sys.argv[1], "-n", sys.argv[2]], text=True).splitlines():
    fields = line.split()
    if len(fields) == 3:
        symbols[fields[2]] = fields[0]
names = ["user_entry", "worker_main", "spin_worker", "spin_loop", "spin_loop_end",
         "__user_bss_start", "__user_bss_end", "shared_counter"]
Path(sys.argv[3]).write_text("".join(f"#define U_{name.upper()} 0x{symbols[name]}UL\n" for name in names))
