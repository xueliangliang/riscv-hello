# BPTFS11 version 1

Independent little-endian format, NOT compatible with FlatFS10 or prototype.
512-byte sectors; 8 MiB image (16384 sectors). Boot LBAs 0–256 protected.
All integer fields u32 LE. IDs one-based, zero=null. Never autoformat.

## Disk layout

LBA 512 super: magic `BPTFS11\0` (8 bytes), followed by nine u32 fields:
version=1, node_count=512, data_count=1024, file_limit=512,
max_size=65536, root ID, live files, directory epoch, data_lba=2048.
Bytes 44–511 zero. Fresh root=1, files=0, epoch=1.
LBA 513 node bitmap: low-bit first, 512 bits, remaining bytes zero.
LBA 514 data bitmap: 1024 bits, remainder zero.
LBAs 515–1026 node pages (ID i => LBA 514+i).
Data ID i => LBA 2048+8*(i-1), 4096 bytes: next ID followed by 4092
payload bytes. Free block/page contents unspecified, no secure erase.

## B+ nodes

Header: type at 0 (1 leaf, 2 internal), count at 4, next-leaf ID at 8
(internal zero), reserved zero at 12. Leaf capacity=7. Records at 16,
64 bytes each: name[32], size at 32, head at 36, tail at 40, reserved
44–63 zero. Names 1–31 ASCII alnum/_/./- then NUL and zero padding.
Full names strictly ordered; unused record/page bytes zero.
Internal capacity=8 children: 36-byte entries at 16 contain lower-fence
name[32] and child ID. Fences strictly increase; first fence along leftmost
path is empty. Route to last fence <= name (equality goes right).
Subtrees obey inherited [lower,upper) ranges. Splits promote right first
fence; a root split persists a new root. Height <=8, uniform leaf depth.
Lazy deletion compacts records but retains empty leaves and safe stale
lower fences. No merge/rebalance or node reclamation. Leaf chain must equal
DFS leaf order including empty leaves.

Mount validates reserved zeros, all bounds/order/inherited ranges, unique
node ownership, exact node bitmap/reachability, uniform depth, leaf chain,
file count, unique data ownership, range/cycle/bitmap checks, exact
ceil(size/4092) chain length/head/tail, and every final block's zero tail.
Mount never writes. No directories, host mount compatibility or journal.

## API contract

Four generation handles; shell only, single open per file. Modes 0=read
existing, 1=create or immediately truncate (REPLACE), 2=RW existing.
Cursor initially zero. Write uses cursor; append always writes EOF and sets
cursor to new EOF. Seek absolute 0..65536. Read with cursor >=size returns
zero. Write past EOF zero-fills gap. Truncate size 0..65536, frees shrink
blocks/zeroes retained tail, zero-fills growth, cursor unchanged.
4096 bytes/call. Allocation preflight is all-or-nothing: F_FULL leaves file
and cursor unchanged. Zero count writes/appends do nothing. REPLACE may have
already truncated before a subsequent invalid write. No rollback/atomicity
on I/O errors; uncertainty poisons mount permanently.

Syscalls (a0,a1,a2): 17 open(name IN,mode,0), 18 read(handle,bytes OUT,count),
19 write(handle,bytes IN,count), 20 flush(handle,0,0), 21 close(handle,0,0),
22 remove(name IN,0,0), 23 reserved/rejected, 24 info(0,0,0),
25 append(handle,bytes IN,count), 26 seek(handle,offset,0),
27 truncate(handle,size,0), 28 list_page(entries OUT,capacity,cursor IN/OUT),
29 defrag(0,0,0). Reserved arguments strictly zero. Owner before pointers;
whole names and buffers must fit one admitted user region. Errors in fs.h.
Listing entry=36 bytes (name[32],u32 size), capacity 1..16. Cursor=two u32:
epoch,index, initially both zero. Returns actual count, zero at EOF; advances
index and stamps current epoch. Any mutation invalidates prior cursors,
including content/size changes. Epoch mismatch/index>file count => F_ARG.
Stable enumeration requires no mutation; ls loops bounded pages in U.

Defrag rejects open handles. Map occupied IDs to ascending packed ranks,
copy ascending source ID (dest<=source), translate links and all leaf heads/
tails, persist bitmap/metadata. Actually moves payload. Metadata stays put.
No power-loss safety or interrupted-operation recovery claims.
Info: logical_bytes=sum sizes, allocated_capacity=used*4092,
free_blocks=1024-used, free_bytes=free_blocks*4092,
holes=highest occupied ID-used, contiguous_tail=1024-highest occupied ID.
Node cache/bitmaps are static kernel BSS, not heap; linker asserts below
user base 0x80400000. Kernel/user raw images each <=64 KiB.
