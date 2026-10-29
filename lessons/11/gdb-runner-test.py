#!/usr/bin/env python3
"""Real child outcomes: fresh logs, partial binary output and cleanup/reaping."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

spec = importlib.util.spec_from_file_location("flush_gate", Path(__file__).with_name("gdb-test.py"))
assert spec is not None and spec.loader is not None
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

with tempfile.TemporaryDirectory(prefix="lesson11-runner-", dir=os.environ.get("TMPDIR")) as directory:
    directory = Path(directory)

    # The make target truncates the real gate log before this regression can
    # fail; that helper alone must clear a stale PASS and report its own errors.
    helper = Path(__file__).with_name("fresh-log.py")
    stale = directory / "stale.log"
    stale.write_bytes(b"PASS GDB: actual FLUSH type4 header16 -> status1\n")
    finished = subprocess.run([sys.executable, str(helper), str(stale)],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    assert finished.returncode == 0, finished.stdout
    assert stale.read_bytes() == b"", "fresh-log kept a stale PASS"
    absent = directory / "no-such-directory" / "gate.log"
    finished = subprocess.run([sys.executable, str(helper), str(absent)],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    assert finished.returncode != 0 and b"fresh-log: cannot truncate" in finished.stdout, finished.stdout

    log = directory / "debugger.log"
    for status in (0, 7):
        log.write_bytes(b"STALE PASS GDB\n")
        with gate.DebuggerSession(log) as session:
            assert log.read_bytes() == b""
            session.start([sys.executable, "-c",
                           f"import os; os.write(1,b'stdout\\n'); os.write(2,b'stderr\\xff\\n'); raise SystemExit({status})"])
            assert session.collect() == b"stdout\nstderr\xff\n"
            assert session.process.returncode == status
        assert log.read_bytes() == b"stdout\nstderr\xff\n"
        assert session.process.poll() == status

    try:
        with gate.DebuggerSession(log) as session:
            session.start([sys.executable, "-c",
                           "import os,time; os.write(1,b'partial stdout\\n'); os.write(2,b'partial stderr\\xff\\n'); time.sleep(30)"])
            session.collect(timeout=0.3)
    except subprocess.TimeoutExpired as error:
        assert isinstance(error.output, bytes)
    else:
        raise AssertionError("timeout accepted")
    assert session.process.returncode is not None
    captured = log.read_bytes()
    assert captured.count(b"partial stdout\n") == captured.count(b"partial stderr\xff\n") == 1
    assert b"FAIL GDB gate: TimeoutExpired" in captured and b"STALE" not in captured

    # Exercise main's real early-Guest-error path, before collect(). The
    # marker guarantees output is already in the child's pipe, not a race.
    marker = directory / "ready"
    child = directory / "debugger"
    child.write_text(f"#!{sys.executable}\nimport os,time\nfrom pathlib import Path\nos.write(1,b'early stdout\\n')\nos.write(2,b'early stderr\\xff\\n')\nPath({str(marker)!r}).touch()\ntime.sleep(30)\n")
    child.chmod(0o700)
    original_guest = gate.Guest
    original_session = gate.DebuggerSession
    original_gdb = os.environ.get("GDB")
    sessions = []
    guests = []

    class RecordingSession(original_session):
        def __init__(self, ignored):
            super().__init__(log)
            sessions.append(self)

    class FailingGuest:
        def __init__(self, *args, **kwargs):
            self.closed = False
            guests.append(self)

        def until(self, *args):
            deadline = time.monotonic() + 3
            while not marker.exists():
                assert time.monotonic() < deadline, "child did not start"
                time.sleep(0.01)
            raise AssertionError("early guest failure")

        def close(self):
            self.closed = True

    try:
        gate.Guest = FailingGuest
        gate.DebuggerSession = RecordingSession
        os.environ["GDB"] = str(child)
        log.write_bytes(b"STALE PASS GDB\n")
        try:
            gate.main()
        except AssertionError as error:
            assert str(error) == "early guest failure"
        else:
            raise AssertionError("guest failure accepted")
    finally:
        gate.Guest = original_guest
        gate.DebuggerSession = original_session
        if original_gdb is None:
            os.environ.pop("GDB", None)
        else:
            os.environ["GDB"] = original_gdb
    assert guests[0].closed and sessions[0].process.returncode is not None
    captured = log.read_bytes()
    assert captured.startswith(b"early stdout\nearly stderr\xff\n")
    assert b"FAIL GDB gate: AssertionError: early guest failure" in captured
    assert b"STALE" not in captured

    # Failure even before launch must replace yesterday's success.
    try:
        with gate.DebuggerSession(log) as session:
            session.start([str(directory / "missing-debugger")])
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("missing debugger accepted")
    assert b"FAIL GDB gate: FileNotFoundError" in log.read_bytes()
    assert b"early stdout" not in log.read_bytes()

print("PASS lesson11 debugger runner: stale-PASS truncation helper, success/nonzero, timeout, early guest failure, launch failure; fresh logs and reaped children")
