#!/usr/bin/env python3
"""Exercise debugger subprocess logging with real success/failure/timeout children."""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile

spec = importlib.util.spec_from_file_location("gdb_test", Path(__file__).with_name("gdb-test.py"))
assert spec is not None and spec.loader is not None
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

with tempfile.TemporaryDirectory(dir=os.environ["TMPDIR"]) as directory:
    log = Path(directory) / "debugger.log"
    for status in (0, 1):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = gate.run_debugger(
                [sys.executable, "-c", f"print('child status {status}'); raise SystemExit({status})"], log)
        assert result.returncode == status
        assert log.read_text() == output.getvalue() == f"child status {status}\n"
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        try:
            gate.run_debugger(
                [sys.executable, "-c",
                 "import os,time; os.write(1,b'partial stdout\\n'); "
                 "os.write(2,b'partial stderr\\n'); time.sleep(10)"], log, timeout=1)
        except subprocess.TimeoutExpired as error:
            # subprocess returns bytes here even when text=True was requested.
            assert isinstance(error.stdout, bytes)
            assert log.read_text() == "partial stdout\npartial stderr\n"
            assert log.read_text() in output.getvalue()
            assert "FAIL: GDB timed out" in output.getvalue()
        else:
            raise AssertionError("timeout was incorrectly accepted")
print("PASS: debugger success, nonzero exit and real timeout preserve combined output.")
