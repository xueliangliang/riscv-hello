# Lesson 11：有边界的 B+ 树文件系统

本课是独立的 **BPTFS11** 后端，不是把第 10 课的线性目录换一个名字。
查找从持久化 root 开始，在内部页比较完整名称的 lower fence，再进入叶页。
插入会真实分裂叶页、内部页及根页；叶链用于 U 态分页枚举。
没有目录、删除合并/再平衡、日志、断电原子性或生产级恢复。
第 10 课源文件、磁盘和 `make lesson10/run-lesson10/test-lesson10` 保持独立。

## 构建与运行

```sh
make lesson11
make run-lesson11
# 明确破坏性重置，仅重置本课保存的盘：
make reset-lesson11
# 换一份独立磁盘；不存在时才从 fixture 安装一次：
make run-lesson11 LESSON11_ARGS='--disk state/lesson11/demo.img'
make test-lesson11
make inspect-lesson11
make test-lesson11-gdb
```

`build/lesson11/disk.img` 是可重复构建的 8 MiB fixture；默认运行盘是
`state/lesson11/disk.img`。构建及 `make clean` 不改保存盘。启动器对复制、
重置及整个 VM 生命周期持有同一非阻塞主机锁，暂存文件 fsync 后原子安装。
已有错误格式磁盘被拒绝，不格式化、不迁移。直接执行 QEMU 会绕过启动器锁。
fixture 不是已挂载用户数据的备份；不要用 format.py 修复保存盘。

唯一 `-kernel` 是双 hart 过滤启动 wrapper + 第 03 课未修改的 C loader；
内核和 U payload 均从磁盘加载。保留 UART PLIC 中断接收、128 字节 RX 环、
U idle、两个 hart 上的进程及 run/kill/wait。没有主机模拟 shell 命令。
存储同步轮询持有调度锁，会延迟两个 hart 的调度与 UART IRQ；RX 缓冲不是
流控。测试逐条命令等待完成，不向忙碌内核灌入任意长的输入。

## Shell

* `ls`：U 程序每次取七个目录项，循环到返回零；打印真实名称和十进制 size。
* `fwrite NAME TEXT`：REPLACE open 立即截断，再从零游标写。短覆盖不留旧后缀。
* `cat NAME` / `fread NAME`：只读 existing；循环 read 到精确 EOF，不隐式创建。
* `fappend NAME TEXT`：RW-existing，忽略旧游标追加到 EOF。
* `fseek NAME OFFSET [TEXT]`：RW-existing，绝对定位，可选择在该位置写 TEXT。
  命令结束关闭 handle；无 TEXT 时仅演示 seek 返回值，不跨命令保存游标。
* `ftruncate NAME SIZE`：RW-existing，缩小回收链，增大补零；本次 handle 游标不变。
* `rm NAME`：删除叶记录并回收数据位图，不回收 B+ 元数据页。
* `defrag`：拒绝仍有打开 handle；按原物理块 ID 升序搬运数据到打包位置，
  翻译链指针与叶 head/tail，更新位图，不仅修改统计数字。
* `fsinfo`：logical_bytes、allocated_capacity、free_blocks/free_bytes、holes、
  contiguous_tail、nodes/files 以及真实 READ/WRITE/FLUSH 成功计数，数字以十六进制输出。

95 字节命令编辑器支持左右移动、删除/退格、四条历史、Tab 补全。测试程序通过
真正 U ecall 在 4096 字节静态缓冲上流式工作；不依赖命令行塞入大文件。
以下命令用于**新鲜可丢弃测试盘**，不是可无损运行的诊断：

```text
fstest                  完整创建、删除、重建及验证
fstest create           只做创建阶段（224 个编号文件、edge、max）
fstest delete           删除编号 2,7,12,...
fstest recreate         重建编号 2,12,22,...，再验证
fsverify                只读验证最终状态
fspressure              文件数和数据位图容量测试（独立 fresh 盘）
fsnodes                 删除/新键插入造成元数据页耗尽（另一 fresh 盘）
```

## 磁盘与算法

完整字节布局及 a0/a1/a2 ABI 见 [FORMAT.md](FORMAT.md)。
节点池 512 个 512 字节页；叶最多七项，内部最多八个孩子，目录最多 512 文件。
数据池 1024 个 4096 字节块，每块四字节 next + 4092 payload；每文件最多
65536 字节，需要最多 17 块。节点与数据位图独立。所有磁盘整数显式 LE 编码，
不序列化原生 C struct；与 FlatFS10、原型 fs_bptree.c 均不兼容。
内核静态缓存包含节点页，不把静态 BSS 称为 heap；链接器拒绝覆盖 0x80400000
用户区。U text/data/BSS 必须在 0x80407000 以下，raw payload 各不超过 64 KiB。

内部条目的 fence 是包含边界的下界。相等名称走右边；删除可留下较旧但安全
的下界与空叶。创建先沿真实树路径计算所需分裂页数，容量不足在修改前返回
F_FULL。handle 保存名称而不是会因叶内移动而失效的 record 指针，四个 generation
handle 拒绝 stale token，一文件单开，shell 所有权检查先于任何指针解引用。
`syscall2` 明确转到 `syscall3(...,0)`，不依赖编译器偶然保留 a2=0。

WRITE 是普通游标写，APPEND 强制 EOF；seek 越 EOF 后写补零；truncate 后游标
可大于 size，所以 READ 必须先判断 cursor>=size 再做减法。增长/写容量预检
是全有或全无的 F_FULL，不伪造 short-write。REPLACE open 已经截断，不因后续
无效 write 回滚。数据与元数据的多个写入不是事务；本课没有 journal。

挂载先完整验证树范围/排序/深度/叶链、节点位图可达性、文件数、数据链
范围/长度/循环/交叉所有权/位图，以及每个尾块的零 padding，验证前不写盘。
I/O 不确定性让 driver 和 mount sticky poison；不循环复用可能仍在 DMA 的
缓冲区。独立 queue 使用静态 DMA 区及有界 rdtime 等待，实际提交 type0 READ、
type1 WRITE、type4 FLUSH，验证 used ID/长度/index/status。FLUSH 的描述符链是
16 字节 header → 1 字节 status，没有可达 data descriptor。内存 fence 不是落盘。

## 自动测试与证据

`test.py` 用 serial PTY 驱动真实 QEMU TCG 双 hart VM。`oracle.py` 用独立的
主机 bytearray 操作模型求预期内容；`decode.py` 不导入 formatter/C code，遍历
所有 raw 内部页/叶页/链与位图，再核对预期完整名称、size、二进制 bytes。

* 224 个键按递增、递减、置换插入，产生多级根/内部/叶分裂；检查全部排序项，
  不是只比较集合。分页容量 1..16，EOF、cursor epoch/index、完整输出区验证。
* 跨 512/4092 边界、NUL/高位字节、4093 写块/257 读块、最大 65536 文件。
  seek/append/truncate 的 0/partial/exact-boundary、gap 补零、缩小后越 EOF 游标。
* invalid names/whole regions/reserved args/counts/handles、单开冲突、generation、
  worker owner-before-pointer；512 文件、1024 数据块、节点池耗尽与无分裂空叶复用。
* 阶段快照独立解码：删中部文件回收的块必须精确相等；重建必须复用释放 ID；
  defrag 后位图必须连续、容量不变且真实链 ID 移动，所有文件内容仍相同。
* 同一 writable image 六次独立 VM，最终两次完整只读 cold verify 不重播 fixture，
  字节级检查整盘不变。额外 shell/容量/节点池测试各用独立 fresh 盘。
* 多种 super/node/bitmap/name/link/cycle/size/duplicate 损坏：host decoder 和真实
  mount 都拒绝，前后整盘哈希不变。只读设备和 NO_FLUSH feature-mask 也拒绝。
* QEMU blkdebug 真正 READ/WRITE/FLUSH IOERR；断言实际请求 type/status，花掉
  once 故障后仍 poison，shutdown 必须失败。不是把超时或源码故障当崩溃恢复。
* 修改真实成功 transcript 的 bytes/EOF/返回数/size/重复项/rm/coldbytes，以及
  raw 内容/padding/链，oracle 必须失败；超时始终失败并清理子进程组。
* 启动器 copy-once/重启/锁冲突/明确 reset/坏盘不改写。fixture 哈希在 finally 校验。

输出在 `build/lesson11/`：`test-result.json`、`raw-decoder.json`、
`oracle-mutations.log`、`evidence-*.img`、阶段和失败 UART 日志。
`make test-lesson11-gdb` 保留真实 device completion checkpoint 的
`gdb-flush.log`，detach 后继续 echo/shutdown；在构建**之前**清空日志，构建或
runner 失败不留下旧 PASS。没有 CI/AWS 部署、自动下载或主机挂载功能。
