"""Scenario bodies split out to keep PTY transport independent and readable."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
from decode import decode, inspect, report
from oracle import pattern, reference, raw_check, listing, check_stats, stats


def rejects(function):
    try:
        function()
    except AssertionError:
        return
    raise AssertionError('oracle accepted mutated evidence')


def run_scenarios(Guest, directory, assert_cat, assert_write, assert_rm):
    fixture = Path('build/lesson11/disk.img')
    protected = fixture.read_bytes()[:257 * 512]
    disk = directory / 'tree.img'
    shutil.copyfile(fixture, disk)
    stage_trees = {}
    records = {}
    def boot(name, commands, expected, verify=False):
        g = Guest(name + '.log', str(disk))
        try:
            output = g.until('11> ')
            assert 'both images loaded' in output and 'mounted BPTFS11' in output
            assert 'hart-online pid=0x0000000000000001' in output
            for text, marker in commands:
                records[text] = g.cmd(text, marker, seconds=180)
            if verify:
                g.cmd('fsverify', 'fsverify: persisted binary chains and exact EOF PASS', seconds=180)
            records[name + '-list'] = g.cmd('ls')
            listing(records[name + '-list'], expected)
            statistics = g.cmd('fsinfo')
            g.shutdown()
        finally:
            g.close()
        tree = raw_check(disk, expected, protected)
        check_stats(statistics, tree)
        stage_trees[name] = tree
        shutil.copyfile(disk, f'build/lesson11/evidence-{name}.img')
        return tree
    created = boot('create', [('fstest create', 'fstest: create stage PASS')], reference('create'))
    assert created['height'] >= 3, 'did not split internal/root levels'
    assert sum(n['type'] == 2 for n in created['nodes'].values()) >= 3
    assert len(created['leaves']) > 8
    removed = boot('delete', [('fstest delete', 'fstest: deleted middle data blocks PASS')], reference('delete'))
    freed = set(created['data_ids']) - set(removed['data_ids'])
    deleted_ids = {block for i in range(2, 224, 5) for block in created['files'][f'f{i:03d}']['blocks']}
    assert freed == deleted_ids, 'deletion did not reclaim exact payload blocks'
    high = max(removed['data_ids'])
    assert removed['holes'] == sum(i not in removed['data_ids'] for i in range(1, high + 1))
    assert removed['holes'] > 0 and set(removed['nodes']) == set(created['nodes'])
    final = boot('recreate', [('fstest recreate', 'fstest: reclaimed allocation PASS')], reference(), verify=True)
    allocated = set(final['data_ids']) - set(removed['data_ids'])
    assert allocated <= freed and allocated, 'recreate did not reuse freed physical IDs'
    packed = boot('defrag', [('defrag', 'defrag target=0 result=0')], reference(), verify=True)
    assert packed['data_ids'] == list(range(1, final['used_blocks'] + 1))
    assert packed['holes'] == 0 and packed['used_blocks'] == final['used_blocks']
    assert set(packed['nodes']) == set(final['nodes']), 'metadata unexpectedly compacted'
    assert any(packed['files'][n]['blocks'] != final['files'][n]['blocks'] for n in final['files']), 'no actual defrag movement'
    for number in (1, 2):
        before = disk.read_bytes()
        boot(f'cold-{number}', [], reference(), verify=True)
        assert disk.read_bytes() == before, 'cold read-only APIs wrote image'
    # A separate real shell/editor/process image. Its raw bytes are independent
    # from the mass test's U-side assertions.
    shell = directory / 'shell.img'
    shutil.copyfile(fixture, shell)
    g = Guest('shell.log', str(shell))
    expected = {}
    try:
        g.until('11> ')
        g.cmd('help', 'fstest [create|delete|recreate] fsverify fspressure fsnodes')
        before = g.cmd('stats')
        assert g.read(0.8) == '' and g.process.poll() is None
        g.cmd('echo delayed', 'echo: delayed\r\n')
        after = g.cmd('stats')
        for counter in ('rx-irq', 'rx-wait'):
            get = lambda t: tuple(int(x, 16) for x in re.search(rf'{counter} pid=0x([0-9a-f]+) value=0x([0-9a-f]+)', t).groups())
            assert all(a > b for a, b in zip(get(after), get(before)))
        g.cmd('ec\t complete', 'echo: complete\r\n')
        g.cmd('echo old', 'echo: old\r\n')
        g.cmd('\x1b[A\x7f\x7f\x7fnew', 'echo: new\r\n')
        g.cmd('echo ac\x1b[Db\x1b[C', 'echo: abc\r\n')
        g.cmd('echo abX\x1b[D\x1b[3~c', 'echo: abc\r\n')
        g.cmd('echo ' + 'x' * 110, 'echo: ' + 'x' * 90 + '\r\n')
        for kind, arg, status in [('sleep', 20, 23), ('exit', 31, 31)]:
            output = g.cmd(f'run {kind} {arg}')
            pid = int(re.search(r'run target=\d+ result=(\d+)', output)[1])
            g.cmd(f'wait {pid}', f'wait target={pid} result={status}')
        output = g.cmd('run spin')
        pid = int(re.search(r'run target=1 result=(\d+)', output)[1])
        g.cmd('sleep 2')
        g.cmd(f'kill {pid}')
        g.cmd(f'wait {pid}', f'wait target={pid} result=137')
        g.cmd('fwrite alpha longer-original-value', 'fwrite target=0 result=21')
        records['write'] = g.cmd('fwrite alpha xyz')
        assert_write(records['write'], 3)
        records['cat'] = g.cmd('cat alpha')
        assert_cat(records['cat'], b'xyz')
        g.cmd('fappend alpha ABC', 'fappend target=0 result=3')
        assert_cat(g.cmd('cat alpha'), b'xyzABC')
        g.cmd('fseek alpha 2 Q', 'fseek target=0 result=1')
        assert_cat(g.cmd('cat alpha'), b'xyQABC')
        g.cmd('ftruncate alpha 4', 'ftruncate target=0 result=0')
        expected['alpha'] = b'xyQA'
        records['coldcat'] = g.cmd('cat alpha')
        assert_cat(records['coldcat'], expected['alpha'])
        g.cmd('fwrite doomed delete-me')
        records['rm'] = g.cmd('rm doomed')
        assert_rm(records['rm'])
        records['listing'] = g.cmd('ls')
        listing(records['listing'], expected)
        g.shutdown()
    finally:
        g.close()
    raw_check(shell, expected, protected)
    g = Guest('shell-cold.log', str(shell))
    try:
        g.until('11> ')
        records['coldcat'] = g.cmd('cat alpha')
        assert_cat(records['coldcat'], expected['alpha'])
        g.shutdown()
    finally:
        g.close()
    raw_check(shell, expected, protected)
    # Mutate captured successful observations, not invented success strings.
    rejects(lambda: assert_cat(records['cat'].replace('xyz\r\ncat', 'xyX\r\ncat'), b'xyz'))
    rejects(lambda: assert_cat(records['cat'].replace('xyz\r\ncat', 'xyzOLD\r\ncat'), b'xyz'))
    rejects(lambda: assert_cat(records['cat'].replace('result=0', 'result=-14'), b'xyz'))
    rejects(lambda: assert_write(records['write'].replace('result=3', 'result=2'), 3))
    rejects(lambda: assert_rm(records['rm'].replace('result=0', 'result=-14')))
    rejects(lambda: listing(records['listing'].replace('size=4', 'size=5'), expected))
    rejects(lambda: listing(records['listing'] + 'file: alpha size=4\r\n', expected))
    rejects(lambda: assert_cat(records['coldcat'].replace('xyQA\r\ncat', 'xyQX\r\ncat'), expected['alpha']))
    damaged = bytearray(shell.read_bytes())
    tree = inspect(damaged)
    block = tree['files']['alpha']['head']
    offset = (2048 + (block - 1) * 8) * 512
    damaged[offset + 4] ^= 1
    rejects(lambda: raw_check(damaged, expected, protected))
    damaged = bytearray(shell.read_bytes())
    damaged[offset + 8] = 1
    rejects(lambda: raw_check(damaged, expected, protected))
    damaged = bytearray(shell.read_bytes())
    struct.pack_into('<I', damaged, offset, block)
    rejects(lambda: raw_check(damaged, expected, protected))
    Path('build/lesson11/oracle-mutations.log').write_text('PASS actual output: bytes/suffix/EOF/write-count/rm-status/list-size/list-duplicate/cold-bytes; raw content/padding/chain mutations rejected\n')
    Path('build/lesson11/raw-decoder.json').write_text(json.dumps({n: report(t) for n, t in stage_trees.items()}, indent=2) + '\n')
    return stage_trees


def malformed(Guest, directory):
    base = Path('build/lesson11/evidence-recreate.img').read_bytes()
    tree = inspect(base)
    root = tree['nodes'][tree['root']]['offset']
    leaf = tree['nodes'][tree['leaves'][0]]['offset']
    record = tree['files']['f000']['record_offset']
    second = tree['files']['f001']['record_offset']
    first_block = tree['files']['f000']['head']
    block_offset = (2048 + (first_block - 1) * 8) * 512
    def word(offset, value):
        return lambda raw: struct.pack_into('<I', raw, offset, value)
    def byte(offset, value):
        return lambda raw: raw.__setitem__(offset, value)
    def copy_record(raw):
        raw[second:second + 32] = raw[record:record + 32]
    def crosslink(raw):
        raw[second + 32:second + 44] = raw[record + 32:record + 44]
    mutations = {
        'magic': byte(512 * 512, 0),
        'version': word(512 * 512 + 8, 2),
        'super-reserved': byte(512 * 512 + 44, 1),
        'root-range': word(512 * 512 + 28, 513),
        'file-count': word(512 * 512 + 32, 0),
        'epoch-zero': word(512 * 512 + 36, 0),
        'node-bitmap-missing': byte(513 * 512, 0),
        'node-bitmap-extra': byte(513 * 512 + 63, 128),
        'bitmap-reserved': byte(514 * 512 + 128, 1),
        'data-bitmap-missing': byte(514 * 512, 0),
        'data-bitmap-extra': byte(514 * 512 + 127, 128),
        'internal-type': word(root, 3),
        'internal-overcount': word(root + 4, 9),
        'internal-child-range': word(root + 16 + 32, 513),
        'internal-cycle': word(root + 16 + 32, tree['root']),
        'internal-duplicate-owner': word(root + 16 + 36 + 32, struct.unpack_from('<I', base, root + 16 + 32)[0]),
        'internal-lower-fence': byte(root + 16, ord('z')),
        'internal-equal-fence': lambda raw: raw.__setitem__(slice(root + 52, root + 84), raw[root + 16:root + 48]),
        'leaf-link': word(leaf + 8, 0),
        'leaf-overcount': word(leaf + 4, 8),
        'leaf-reserved': word(leaf + 12, 1),
        'leaf-unused': byte(leaf + 511, 1),
        'name-padding': byte(record + 5, 1),
        'unsafe-name': byte(record, 47),
        'duplicate-name': copy_record,
        'oversize': word(record + 32, 65537),
        'head-range': word(record + 36, 1025),
        'wrong-tail': word(record + 40, first_block),
        'record-reserved': byte(record + 63, 1),
        'data-link-cycle': word(block_offset, first_block),
        'data-link-range': word(block_offset, 1025),
        'data-short-chain': word(block_offset, 0),
        'data-crosslink': crosslink,
    }
    last = tree['files']['f000']['tail']
    tail_offset = (2048 + (last - 1) * 8) * 512
    used = tree['files']['f000']['size'] % 4092
    mutations['data-tail-padding'] = byte(tail_offset + 4 + used, 1)
    for name, mutate in mutations.items():
        image = bytearray(base)
        mutate(image)
        rejects(lambda: inspect(image))
        disk = directory / f'bad-{name}.img'
        disk.write_bytes(image)
        negative(Guest, name, disk)
    return len(mutations)


def negative(Guest, name, disk, options=None):
    before = hashlib.sha256(Path(disk).read_bytes()).digest()
    g = Guest(f'negative-{name}.log', str(disk), True, options)
    try:
        g.until('FAIL: filesystem mount rejected', 15)
        g.process.wait(timeout=3)
        assert g.process.returncode == 1 and b'11> ' not in g.all
    finally:
        g.close()
    assert hashlib.sha256(Path(disk).read_bytes()).digest() == before, name
    return g.all


def pressure(Guest, directory):
    disk = directory / 'pressure.img'
    shutil.copyfile('build/lesson11/disk.img', disk)
    g = Guest('pressure.log', str(disk))
    try:
        g.until('11> ')
        g.cmd('fspressure', 'fspressure: 512 files 1024 blocks preflight reuse PASS', seconds=180)
        output = g.cmd('fsinfo')
        g.shutdown()
    finally:
        g.close()
    expected = {f'f{i:03d}': bytes(65536) if i < 60 else bytes(4 * 4092) if i == 60 else b'' for i in range(512)}
    expected['f030'] = pattern(245, 65536)
    tree = raw_check(disk, expected, Path('build/lesson11/disk.img').read_bytes()[:257 * 512])
    assert tree['used_blocks'] == 1024 and len(tree['files']) == 512
    check_stats(output, tree)
    shutil.copyfile(disk, 'build/lesson11/evidence-pressure.img')
    return tree

def node_pressure(Guest, directory):
    disk = directory / 'nodes.img'
    shutil.copyfile('build/lesson11/disk.img', disk)
    g = Guest('nodes.log', str(disk))
    try:
        g.until('11> ')
        output = g.cmd('fsnodes', ' PASS', seconds=240)
        match = re.search(r'fsnodes: stop (\d+) (\d+) PASS', output)
        assert match, output
        round_number, count = map(int, match.groups())
        expected = {f'n{round_number:03d}{i:02d}': b'' for i in range(count)}
        listing(g.cmd('ls'), expected)
        g.shutdown()
    finally:
        g.close()
    tree = raw_check(disk, expected, Path('build/lesson11/disk.img').read_bytes()[:257 * 512])
    assert len(tree['nodes']) >= 505 and tree['height'] >= 3
    assert not tree['data_ids'] and len(tree['files']) < 16
    shutil.copyfile(disk, 'build/lesson11/evidence-nodes.img')
    before = disk.read_bytes()
    g = Guest('nodes-cold.log', str(disk))
    try:
        g.until('11> ')
        listing(g.cmd('ls'), expected)
        g.shutdown()
    finally:
        g.close()
    assert disk.read_bytes() == before
    return tree
