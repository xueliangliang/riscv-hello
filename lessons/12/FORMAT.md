# BPTFS12：有界全数据 redo 日志

本格式不兼容 BPTFS11；挂载不格式化、不升级、不猜测旧格式。设备恰为
16384 个 512 字节扇区（8 MiB）。原子单位是**一次文件系统 mutator API**，
不是整个 shell fwrite 命令（REPLACE open 与后续各次 write 独立提交）。

## Home 与日志

所有整数显式 little-endian，不把 C struct 写入磁盘。
LBA 0–256 是原有启动记录/kernel/U；512 是 super；513/514 是节点/数据位图；
515–1026 是 512 个节点页；2048–10239 是 1024 个 4096 字节链块。
日志只允许上述 super/位图/节点/数据 home，禁止启动区、空洞、日志自身和设备外地址。
日志 header 位于 12288；descriptor 为 12289–12304（16 扇区，8192 字节）；
最多 1024 个 after-image 位于 12305–13328。其余扇区保留。
每个 descriptor 是 8 字节：home LBA u32、该 image CRC32 u32；未使用 descriptor 全零。
1024 是**唯一 home 扇区数**：重复写覆盖原条目；事务中的读优先返回 staged image。

Super：0..7 `BPTFS12\0`，8 版本 1，12 节点数512，16 数据块数1024，
20 文件数上限512，24 单文件上限65536，28 root，32 文件数，36 非零 epoch，
40 data LBA2048；44..507 零；508 CRC32（覆盖0..507）。
其余节点、位图和链结构沿用 lesson11 的显式布局：叶记录64字节，内部记录36字节，
数据块头4字节 next、payload4092，最后块 EOF 后全零。

Header：0..7 `REDO12\0\0`；8 版本1；12 扇区字节512；16 容量1024；
20 count（1..1024）；24 descriptor CRC（覆盖完整8192字节）；28 设备扇区16384；
32 journal LBA12288；36 image LBA12305；40..507 零；508 header CRC（0..507）。
CRC 为 CRC-32/ISO-HDLC：反射 polynomial 0xedb88320，初值0xffffffff，
逐字节最低位先行，最终 XOR 0xffffffff；与 Python zlib.crc32 一致。
全零 header 唯一表示 clean。非零 malformed header 拒绝且不写盘。
恢复首先检查 home super 的本格式身份/几何/CRC（不检查树），再完整检查 header、
descriptor、所有 image CRC、去重和白名单，**完成全部验证之后**才写任何 home。

## 顺序与失败

commit：descriptor+images → FLUSH → header WRITE → FLUSH → 全部 home WRITE
→ FLUSH → 全零 header WRITE → FLUSH。只有 clear 已 durable 才能重用日志。
恢复：全部 redo → home FLUSH → clear WRITE → clear FLUSH → 完整 home 树验证。
恢复中断可重放；干净只读二次启动不改变磁盘。空事务无任何设备请求。

假设512字节写原子、成功 FLUSH 诚实且有序；不覆盖扇区撕裂、撒谎固件或真实断电。
QEMU finisher 是确定性软件中断，不是设备掉电实验。native backend 另外区分 volatile
和 durable 字节，断电丢弃未 flush 写入。失败 WRITE/FLUSH **可能已经持久化**；
尤其尝试 commit-header WRITE 后，返回错误不证明 PRE 状态。真实 I/O 错误 sticky，
必须重新挂载恢复。超过1024个唯一扇区返回 F_LIMIT=-17，完整恢复 RAM/cache/handle/
cursor，磁盘不变，仍健康；不拆分超大 defrag。数据、链接、树、位图、super 全部 journal。
无堆扩容：日志与事务快照都是静态 BSS；linker 必须断言末尾低于 U base 0x80400000。
