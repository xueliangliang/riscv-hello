"""Independent serial oracle: correlate each wait with its exact target/status.
No guest PASS banner is accepted as evidence. Also used on archive transcripts.
"""
from pathlib import Path
import re

EVENT = re.compile(r"([a-z-]+) pid=0x([0-9a-f]{16}) value=0x([0-9a-f]{16})")


def verify(text):
    text = text.replace("\r\r\n", "\n").replace("\r\n", "\n")
    assert "FAIL:" not in text
    assert text.count("shutdown: explicit user request") == 1
    assert "both images loaded; jumping to kernel" in text
    processes = {}
    generations = {}
    active = None
    completed = []
    blocked = 0
    high_water = 0
    deferred = set()
    acknowledged = set()
    zombies = {}
    irq_samples = []
    for match in EVENT.finditer(text):
        name, pid, value = match[1], int(match[2], 16), int(match[3], 16)
        if name == "spawn":
            slot = pid & 15
            assert slot < 8 and all((p & 15) != slot for p in processes)
            assert pid >> 4 == generations.get(slot, 0) + 1
            generations[slot] = pid >> 4
            processes[pid] = "live"
            high_water = max(high_water, len(processes))
        elif name == "kill-deferred":
            assert processes[pid] == "live" and value == 1
            deferred.add(pid)
        elif name == "kill-complete":
            assert pid in deferred and value == 1
            acknowledged.add(pid)
        elif name == "zombie":
            assert processes[pid] == "live"
            if pid in deferred:
                assert pid in acknowledged and value == 137
            processes[pid] = "zombie"
            zombies[pid] = value
        elif name == "wait-call":
            assert pid == 16 and active is None and value in processes and value != 16
            phase = "immediate" if processes[value] == "zombie" else "call"
            active = {"target": value, "phase": phase}
        elif name == "wait-block":
            assert pid == 16 and active == {"target": value, "phase": "call"}
            assert processes[value] == "live"
            active["phase"] = "blocked"
            blocked += 1
        elif name == "reap":
            assert active is not None and active["target"] == pid
            assert processes[pid] == "zombie" and zombies[pid] == value
            assert active["phase"] in ("immediate", "returned")
            del processes[pid]
            if active["phase"] == "immediate":
                active["phase"] = "reaped"
            else:
                completed.append((pid, value))
                active = None
        elif name == "wait-return":
            assert pid == 16 and active is not None
            target = active["target"]
            assert zombies[target] == value, "wrong target's wait status"
            if active["phase"] == "blocked":
                assert processes[target] == "zombie"
                active["phase"] = "returned"
            else:
                assert active["phase"] == "reaped"
                completed.append((target, value))
                active = None
        elif name == "rx-irq":
            irq_samples.append((pid, value))
    actual_returns = [(int(a), int(b)) for a, b in re.findall(
        r"(?:^|\n)wait target=(\d+) result=(\d+)\r?\n", text)]
    assert completed == actual_returns and len(completed) == 10
    assert processes == {16: "live"} and high_water == 8 and active is None
    assert blocked >= 1 and deferred == acknowledged and len(deferred) == 1
    assert irq_samples[1][0] > irq_samples[0][0] > 0
    echoes = re.findall(r"(?:^|\n)echo: ([^\r\n]*)\r?\n", text)
    assert echoes == ["delayed", "completed", "old", "new", "draft", "abc", "abc", "crlf", "recovered"], echoes
    assert "unknown: nonsense\n" in text
    assert "unknown: " + "A" * 95 + "\n" in text
    assert "run target=3 result=-3\n" in text
    assert "wait target=999 result=-1\n" in text
    assert "kill target=999 result=-1\n" in text
    return completed


def mutations(text):
    first = next(m for m in EVENT.finditer(text) if m[1] == "wait-call")
    wrong_target = text[:first.start(3)] + "0000000000000010" + text[first.end(3):]
    status = next(m for m in EVENT.finditer(text) if m[1] == "wait-return")
    wrong_status = text[:status.start(3)] + "0000000000000089" + text[status.end(3):]
    mutants = {
        "wrong-target": wrong_target,
        "wrong-status": wrong_status,
        "missing-blocks": re.sub(r"wait-block pid=0x[0-9a-f]+ value=0x[0-9a-f]+", "", text),
        "missing-execution": text.replace("echo: new", "echo: NOT-EXECUTED"),
        "missing-command-result": re.sub(r"wait target=\d+ result=23", "", text),
        "late-fault": text + "FAIL: late fault\n",
    }
    for label, mutant in mutants.items():
        assert mutant != text
        try:
            verify(mutant)
        except AssertionError:
            continue
        raise AssertionError("admitted mutant " + label)
    return "\n".join("REJECTED: " + name for name in mutants) + "\n"


if __name__ == "__main__":
    import sys
    text = Path(sys.argv[1]).read_text()
    print("verified exact wait transactions:", verify(text))
    print(mutations(text), end="")
