"""Host reference operations and exact oracles, independent of guest PASS text."""
from pathlib import Path
import re
from decode import inspect


def pattern(seed, count):
    return bytes((p * 37 + seed * 19 + (p >> 8)) % 256 for p in range(count))


def reference(stage='final'):
    files = {f'f{i:03d}': pattern(i, 8200 + i * 3) for i in range(224)}
    # Model edge operations independently as a mutable byte sequence.
    edge = bytearray(pattern(250, 12293))
    del edge[4092:]
    edge.extend(bytes(6000 - len(edge)))
    edge.extend(pattern(251, 19))
    edge.extend(pattern(252, 13))
    edge.extend(bytes(8190 - len(edge)))
    del edge[8184:]
    edge.extend(bytes(8190 - len(edge)))
    edge.clear()
    edge.extend(bytes(4092))
    edge.extend(bytes(5000 - len(edge)))
    edge.extend(pattern(253, 37))
    edge.extend(pattern(254, 11))
    edge.extend(bytes(8190 - len(edge)))
    files.update(edge=bytes(edge), max=pattern(249, 65536))
    if stage != 'create':
        for i in range(2, 224, 5):
            del files[f'f{i:03d}']
    if stage == 'final':
        for i in range(2, 224, 10):
            files[f'f{i:03d}'] = pattern(i, i + 500)
    return files


def raw_check(source, expected, protected):
    raw = bytes(source) if isinstance(source, (bytes, bytearray)) else Path(source).read_bytes()
    assert raw[:257 * 512] == protected, 'protected boot changed'
    tree = inspect(raw)
    actual = tree['files']
    assert list(actual) == sorted(expected), 'raw exact ordered names/count'
    for name, content in expected.items():
        assert actual[name]['size'] == len(content), (name, 'size mismatch')
        assert actual[name]['content'] == content, (name, 'byte mismatch')
    return tree


def listing(text, expected):
    found = [(name, int(size)) for name, size in re.findall(r'file: ([A-Za-z0-9_.-]+) size=(\d+)\r?\n', text)]
    assert found == [(n, len(expected[n])) for n in sorted(expected)], 'listing exact ordered names/sizes/count'
    return found


def stats(text):
    line = re.search(r'fsinfo: (.*)', text)
    assert line, text
    fields = {name: int(value, 16) for name, value in re.findall(r'(\w+)=0x([0-9a-f]+)', line[1])}
    assert fields.keys() >= {'logical_bytes', 'allocated_capacity', 'free_blocks', 'free_bytes',
                             'holes', 'contiguous_tail', 'nodes', 'files', 'reads', 'writes', 'flushes', 'healthy'}
    return fields


def check_stats(text, tree):
    s = stats(text)
    used = tree['used_blocks']
    assert s['logical_bytes'] == tree['logical_bytes']
    assert s['allocated_capacity'] == used * 4092
    assert s['free_blocks'] == 1024 - used
    assert s['free_bytes'] == (1024 - used) * 4092
    assert s['holes'] == tree['holes']
    assert s['contiguous_tail'] == 1024 - max(tree['data_ids'], default=0)
    assert s['nodes'] == len(tree['nodes']) and s['files'] == len(tree['files'])
    assert s['healthy'] == 1 and s['reads'] > 0 and s['flushes'] > 0
    return s
