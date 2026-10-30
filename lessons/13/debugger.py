"""Fresh binary debugger transcripts, including timeout and early cleanup."""
from pathlib import Path
import subprocess


class DebuggerSession:
    """One fresh log and one reaped child, including pre-communicate failures."""
    def __init__(self, log):
        self.log = Path(log)
        self.log.write_bytes(b"")
        self.process = None
        self.output = None

    def __enter__(self):
        return self

    def start(self, argv):
        self.process = subprocess.Popen(argv, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT)

    def collect(self, timeout=15):
        assert self.process is not None, "debugger not started"
        try:
            self.output, _ = self.process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            # communicate() after kill returns the complete accumulated bytes,
            # not just the suffix; do not duplicate TimeoutExpired.output.
            self.process.kill()
            self.output, _ = self.process.communicate()
            self.log.write_bytes(self.output)
            raise
        self.log.write_bytes(self.output)
        return self.output

    def __exit__(self, kind, error, traceback):
        try:
            if self.process is not None and self.output is None:
                if self.process.poll() is None:
                    self.process.kill()
                self.output, _ = self.process.communicate()
                self.log.write_bytes(self.output)
        finally:
            if error is not None:
                with self.log.open("ab") as stream:
                    stream.write(f"\nFAIL GDB gate: {kind.__name__}: {error}\n".encode(errors="replace"))
        return False
