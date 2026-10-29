#!/usr/bin/env python3
"""Independent BPTFS11 decoder: no formatter import, no C/native structs."""
import json
import re
import struct
from pathlib import Path


def inspect(source):
    raw = bytes(source) if isinstance(source, (bytes, bytearray)) else Path(source).read_bytes()
    assert len(raw) == 8 * 1024 * 1024, 'image length'
    def u32(offset):
        return struct.unpack_from('<I', raw, offset)[0]
    def bitmap(lba, count):
        start = lba * 512
        assert not any(raw[start + count // 8:start + 512]), 'bitmap reserved'
        return {i + 1 for i in range(count) if raw[start + i // 8] & (1 << (i % 8))}
    def name(offset, empty=False):
        field = raw[offset:offset + 32]
        assert b'\0' in field, 'unterminated name'
        value, padding = field.split(b'\0', 1)
        assert not any(padding), 'name padding'
        assert (empty and not value) or re.fullmatch(rb'[A-Za-z0-9_.-]{1,31}', value), 'name characters'
        return value.decode('ascii')
    super_offset = 512 * 512
    fields = struct.unpack_from('<8s9I', raw, super_offset)
    assert fields[:6] == (b'BPTFS11\0', 1, 512, 1024, 512, 65536), 'super geometry/version'
    root, file_count, epoch, data_lba = fields[6:]
    assert 1 <= root <= 512 and file_count <= 512 and epoch and data_lba == 2048
    assert not any(raw[super_offset + 44:super_offset + 512]), 'super reserved'
    node_map = bitmap(513, 512)
    data_map = bitmap(514, 1024)
    visited = set()
    occupied = set()
    leaves = []
    leaf_links = []
    depths = set()
    entries = {}
    all_names = []
    node_records = {}
    def file_record(offset):
        filename = name(offset)
        assert filename not in entries, 'duplicate filename'
        size, head, tail = struct.unpack_from('<III', raw, offset + 32)
        assert size <= 65536 and not any(raw[offset + 44:offset + 64]), 'record fields'
        count = (size + 4091) // 4092
        ids = []
        content = bytearray()
        current = head
        if count == 0:
            assert head == tail == 0, 'empty chain'
        for index in range(count):
            assert 1 <= current <= 1024 and current in data_map, 'data id/bitmap'
            assert current not in occupied, 'data cycle/crosslink'
            occupied.add(current)
            ids.append(current)
            block = (2048 + (current - 1) * 8) * 512
            next_id = u32(block)
            payload = raw[block + 4:block + 4096]
            used = min(4092, size - len(content))
            content.extend(payload[:used])
            if index + 1 == count:
                assert current == tail and next_id == 0, 'tail/chain length'
                assert not any(payload[used:]), 'nonzero final padding'
            else:
                assert next_id != 0, 'short chain'
            current = next_id
        entries[filename] = {'size': size, 'head': head, 'tail': tail,
                             'blocks': ids, 'content': bytes(content), 'record_offset': offset}
        all_names.append(filename)
        return filename
    def visit(node_id, lower, upper, depth):
        assert 1 <= node_id <= 512 and node_id in node_map and node_id not in visited, 'node ownership/bounds'
        assert depth <= 8, 'height bound'
        visited.add(node_id)
        start = (514 + node_id) * 512
        kind, count, following, reserved = struct.unpack_from('<4I', raw, start)
        assert reserved == 0, 'node reserved'
        node_records[node_id] = {'type': kind, 'count': count, 'offset': start}
        if kind == 1:
            assert count <= 7, 'leaf count'
            depths.add(depth)
            leaves.append(node_id)
            leaf_links.append(following)
            keys = [file_record(start + 16 + 64 * i) for i in range(count)]
            assert keys == sorted(set(keys)), 'leaf order'
            assert all(key >= lower and (upper is None or key < upper) for key in keys), 'leaf fence range'
            used = 16 + count * 64
        else:
            assert kind == 2 and 2 <= count <= 8 and following == 0, 'internal header'
            keys = [name(start + 16 + 36 * i, empty=(i == 0)) for i in range(count)]
            assert keys[0] == lower and keys == sorted(set(keys)), 'internal fence order'
            assert upper is None or keys[-1] < upper, 'internal upper range'
            for i, key in enumerate(keys):
                child = u32(start + 16 + 36 * i + 32)
                visit(child, key, keys[i + 1] if i + 1 < count else upper, depth + 1)
            used = 16 + count * 36
        assert not any(raw[start + used:start + 512]), 'node unused padding'
    visit(root, '', None, 1)
    assert len(depths) == 1, 'unbalanced depths'
    assert all_names == sorted(set(all_names)), 'global name order/duplicates'
    assert len(entries) == file_count, 'file count'
    assert leaf_links == leaves[1:] + [0], 'leaf chain'
    assert visited == node_map, 'unreachable node bitmap'
    assert occupied == data_map, 'unowned data bitmap'
    high = max(occupied, default=0)
    return {'files': entries, 'root': root, 'height': next(iter(depths)),
            'nodes': node_records, 'leaves': leaves, 'data_ids': sorted(occupied),
            'used_blocks': len(occupied), 'holes': high - len(occupied),
            'logical_bytes': sum(e['size'] for e in entries.values()),
            'epoch': epoch}


def decode(source):
    return inspect(source)['files']


def report(value):
    result = dict(value)
    result['files'] = {name: {k: v for k, v in entry.items() if k != 'content'}
                       for name, entry in value['files'].items()}
    return result


if __name__ == '__main__':
    import sys
    print(json.dumps(report(inspect(sys.argv[1])), indent=2))
