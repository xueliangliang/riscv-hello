# Lesson 08 — 两个 hart 真正执行用户进程：启动顺序、锁与生命周期

这一步不是给 QEMU 增加 `-smp 2` 和两行启动输出。两个 hart 都从真实磁盘
加载的同一用户映像运行 U-mode worker；两个不主动让出的循环都受到 Sstc
抢占；两个并发 worker 争用同一把用户锁，完成 **8000 次无丢失的共享计数更新**。
内核的进程表、调度、wait/reap 和 remote kill 则由另一把全局内核锁保护。

这是 QEMU 上的软件/体系结构实验，**不是硬件、隔离、安全性或加速比证明**。
Lesson01–07 的源码和路径保持不变；本章只复用其只读的 UART、磁盘格式和
lesson03 的 C/virtio loader，拥有新的 boot entry、M/S entry、trap 和 runtime。

## 运行

从仓库目录执行；初次获取可以使用：

```sh
git clone https://github.com/xueliangliang/riscv-hello.git
cd riscv-hello
make lesson08
make test-lesson08
make inspect-lesson08
make test-lesson08-gdb       # 需要 gdb-multiarch
```

全部回归：`make clean all`、`make test inspect`。生成物和日志都在 `build/`。
本章实测工具为 QEMU 10.2.1、`riscv64-linux-gnu-` 工具链和 Python 3；没有 OpenSBI。
自动测试实际调用以下命令（磁盘以只读方式挂载）：

```sh
qemu-system-riscv64 -machine virt -accel tcg,thread=multi \
  -cpu rv64,sstc=true -smp 2 -m 128M -bios none \
  -display none -serial stdio -monitor none \
  -global virtio-mmio.force-legacy=false \
  -kernel build/lesson08/bootloader.elf \
  -drive file=build/lesson08/disk.img,if=none,format=raw,id=disk,readonly=on \
  -device virtio-blk-device,drive=disk -no-reboot
```

`-kernel` 是 **bootloader ELF**，不是内核或用户 ELF。后两者只由 virtio-block
读取的磁盘内容提供。boot record、LBA 连续性、容量和每个 payload 的 64KiB
上限仍由 lesson03 loader 与 image builder 检查。没有文件系统。

## 先读启动路径，再读 scheduler

```text
hart0                                      hart1
boot.S: 读 mhartid                          boot.S: 读 mhartid
建立 loader gp/sp，清 loader BSS             不用 gp/sp、不清 BSS、不调用 C
lesson03 C: 唯一 virtio loader               轮询 MSIP1（0x02000004）
读入 kernel + user；本地 fence.i             |
跳入 kernel start.S                         |
只在 hart0 清 kernel BSS                    |
建立本 hart S/M stack + M CSRs              |
mret -> supervisor_main                    |
清 user BSS，初始化 controller              |
fence iorw,iorw -> MSIP1=1 ----------------> 读到 1；fence iorw,iorw
                                           清自己的 MSIP；本地 fence.i
                                           跳入 kernel start.S，不再清 BSS
                                           建立自己的 S/M stack + M CSRs
                                           mret -> supervisor_main
本地 fence.i；配置本 hart stvec/sie           本地 fence.i；配置本 hart stvec/sie
锁内调度，解锁，再恢复 U frame               锁内调度，解锁，再恢复 U frame
```

这里 MSIP 是**显式内存映射启动握手**，不是 S-mode IPI 中断服务。MIE 没有开启
MSIE；secondary 轮询寄存器而不依赖中断或共享栈。hart0 发布前的 I/O/memory
fence 与 hart1 观察后的 fence 建立顺序：两份磁盘数据、kernel/user BSS 和初始
进程都已存在，hart1 才能进入加载好的指令。额外 hart 在接触共享状态前停住。
这份 entry 明确只支持 hart0/1，不是通用 CPU discovery。

`fence.i` 只作用于执行它的 hart。因此 loader 的 hart0 fence 不够：hart1 在
跳进 kernel **之前**自己 fence，两个 hart 在进入用户代码前也各自 fence。

### 每个 hart 都必须设置的内容

- 独立 4KiB M trap stack、16KiB S stack（顶端保留 16 字节元数据）。
- `mtvec/mscratch`、`stvec/sscratch`、`satp=0` 和本地 privilege CSR。
- flat NAPOT PMP RWX、`medeleg` 中 illegal instruction/U ecall、STIP delegation。
- `mcounteren.TM=1`、`menvcfg.STCE=1`、本地 `stimecmp` 和 `sie.STIE`。
- `Hart.slot`、deadline、timer/idle 统计。共享 timebase 为 10MHz；100000 time
  units 是本实验一个 10ms tick。实际定时行为不是主机性能承诺。

没有 CLINT MTIP relay、SBI timer 或 PLIC timer claim。`stimecmp` 写入后的 STIP
撤销可能延迟，所以早于当前 deadline 的 timer trap 原样返回，不算新的 tick。

## 不能相信 user tp

S-mode 不读取 `mhartid`。M entry 把 hart ID 通过 `a0`、本 hart 的 stack top
通过 `a1` 传给 `supervisor_main`。初始化后，stack top 的保留区保存 `Hart *`。

U trap 的顺序是：交换到 `sscratch` 指定的 S stack，保存所有整数寄存器（包括
**用户 tp**），再从 `frame + 288` 处的可信栈元数据加载 kernel tp。C 用 kernel
`tp -> Hart` 找到本地 current。恢复时先用 kernel tp 设置本 hart `sscratch`，
然后恢复用户 tp，最后 `sret`。两个 spinner 故意把 tp 设成 `0xdeadbeef`；每次
有效 timer 样本和 GDB 都检查它没有被 hart ID 或内核指针覆盖。

288-byte frame 的 offsets 由 `runtime.h` 与 `trap.S` 共同定义：x0–x31 共
256 字节，随后 sepc、sstatus、scause、stval 各 8 字节。trap-stack frame 只是
临时输入；每个进程拥有一份完整 frame。只保存 RV64 整数上下文，不支持
FPU/vector 上下文。内核 C、trap、调度和轮询 idle 中 SIE 始终关闭，不允许嵌套
中断；意外 S/M exception 是显式失败，不会按 U context 悄悄继续。

## 共享表、独占 RUNNING 与 affinity

本章选择**固定 affinity**：`hart = slot & 1`，controller 的 slot0 在 hart0，
slot1/3/5/7 在 hart1，slot2/4/6 在 hart0。八个 process slots 不等于两个 hart。
没有 migration、load balancing 或工作窃取；一个 hart idle 时也不会执行另一个
hart 的 READY 进程。这使本地 icache 与当前帧所有权容易追踪，**不宣称 SMP 加速**。
以后若加入迁移/动态代码加载，必须重新处理每个执行 hart 的 `fence.i` 契约。

内核锁使用 RISC-V A 扩展的 acquire exchange 和 release store：

1. 获锁后才读写 process table、生命周期、调度和相关统计；正常 UART 输出也在
   同一锁内，所以日志具有可用作 host oracle 的全局串行顺序。
2. RUNNING 进程必须有 `owner == hart.id`，且满足 affinity。调度不会选择别的
   hart 的进程，更不会让两个 hart 同时恢复同一 frame。
3. trap 完整保存 frame 后，才可能将 RUNNING 改为 READY。spawn 也在初始化
   frame、stack、显式实例 data 后才发布 READY。
4. 选择下一进程时在锁内设 RUNNING/owner。**先解锁，再恢复寄存器/sret**；此时
   RUNNING reservation 仍在，另一个 hart 不能重选或回收该 frame。
5. 无任务时 `Hart.slot=-1`，idle 放锁、短暂轮询、重新获锁并扫描 sleepers/READY。
   没有 deadlock 自动退出或 legacy timeout。另一 hart 始终可以 spawn/kill/wake。
   这是持久的 **busy-poll idle**，不是 WFI、低功耗或 interrupt-driven console。

全局锁有意串行化 S-mode 工作；没有公平性或严格实时上界承诺。用户自旋锁与
内核锁不是同一把锁：用户临界区可以被 timer 抢占，内核持锁代码不能被 S timer
重入。不要将未来 UART 输入 busy-wait 放进这把锁；本章不实现 lesson09 输入。

### 状态与 remote kill

```text
FREE --spawn/init--> READY --reserve--> RUNNING --timer--> READY
                                      | sleep           | wait(live child)
                                      v                 v
                                   SLEEPING           WAITING
                                      | deadline        | exact child exit
                                      +----> READY <----+
RUNNING --exit / owner acknowledges pending kill--> ZOMBIE --wait/reap--> FREE
READY/SLEEPING --parent kill--> ZOMBIE
```

`kill(RUNNING)` 只设置 `kill_pending`，保留 state、owner、栈、PID 和 saved frame，
返回 **1 = KILL_DEFERRED**。它不把远程正在使用的内存变成 FREE。owner 下一次
trap 先完整保存帧，再确认请求、生成 status137 的 zombie，并按正常 wait 规则
完成/回收。`kill` 非 RUNNING child 则同步生成 zombie、返回0。重复 kill 一个
尚未确认的 pending child 仍是 deferred；kill 已退出的 zombie 返回 E_ARG。

日志明确区分 `kill`、`kill-deferred`、`kill-complete` 和 `zombie`。完成确认前不
允许 reap 或复用 slot。controller 在 wait 返回后还检查旧实例的计数不再增加。

## ABI 与内存边界

沿用 `a7=number`、`a0/a1=arguments`、`a0=result`、固定 4-byte `ecall`。
异步 timer 的 sepc 不增加；只有 U ecall 增加4。新增接口不复用旧 syscall 编号。

| ID | 接口 | 结果/限制 |
|---|---|---|
| 1 | WRITE(pointer,length) | ≤256 字节；共享 user image 或调用者自己的 stack/data |
| 2 | SPAWN(entry,arg) | 仅 controller；已知 builtin；返回 generation PID |
| 3 | SLEEP(ticks) | 1–1000；阻塞当前进程，不阻塞另一 hart |
| 4 | EXIT(status) | worker；0–255；controller 不能 exit |
| 5 | KILL(childPID) | 0=同步完成，1=远程 RUNNING 请求待确认 |
| 6 | WAIT(childPID) | 精确 child status；等待时阻塞；完成时只 reap 该 child |
| 7/8 | STATE/HITS(childPID) | parent-only snapshot；HITS 为有效 timer trap 次数 |
| 9/10 | DONE/FAIL | 测试 controller 显式成功关机 / assertion 失败 |
| 11 | HART() | 当前执行 hart ID；counter worker 同时留下可信参与证据 |
| 12 | REMOTE_KILLS() | 测试用 deferred 请求计数 |
| 13 | IDLE() | 两个 hart 的 idle pass 总数，受内核锁保护 |

错误是 `E_PID=-1`（不存在/陈旧 PID）、`E_OWNER=-2`、`E_FULL=-3`、`E_ARG=-4`。
PID = generation×16 + slot；generation 不回绕。ZOMBIE 仍占 slot，只有精确 wait
回收才可重新 launch。worker 不建后代，避免本章额外引入 orphan 策略。

| 区域 | 地址/预算 |
|---|---|
| loader | `0x80000000`；只有 hart0 使用旧 loader stack/BSS |
| disk-loaded kernel | `0x80200000`，本章独立 `kernel.ld` |
| M stacks | `machine_stacks`，2×4096 bytes |
| S stacks | `supervisor_stacks`，2×16384 bytes，含各自顶端16-byte metadata |
| user image + shared compiler globals | `0x80400000`–`0x80407000` |
| 显式实例 data | `0x80407000`–`0x80407800`，8×256 bytes |
| user stacks | `0x80408000`–`0x80410000`，8×4096 bytes |

`readelf/nm` 给出本次链接的确切 kernel/BSS/stack symbols；链接断言阻止 kernel
BSS 覆盖 user image，user linker 也断言实例 data 和 stack 的边界。ELF 的 RX/R/RW
headers 可检查，但 flat PMP 让 U 仍能访问整个物理空间：**这不是 W^X 或隔离**。
指针检查只是 WRITE API 的输入检查。普通 C 全局变量仍共享，不是假装给每个
process 重定位 .data/.bss；`shared_counter` 正是有意共享的实例。

## 验证不是看 banner

`test.py` 包括五次独立 disk boot、真实 PTY 启动、两个负镜像、超时拒绝及日志
变异测试。QEMU 正常成功必须 exit0；负镜像必须 **实际打印失败并 exit1**。

- ELF 反汇编确认 spinner 的 loop 只有 add/store/jump，没有 ecall/yield。
  trap 中检查 U-origin、stack、tp、a3/s2 canary、实例 data 和单调进度。
  host 同时要求两个 hart 的动态 saved PC 落在那个 loop 的确切地址范围。
- controller 和长 sleeper 睡眠期间，host 仍观察两个 hart 的 spinner 进度。
- shared counter worker 在独立 hart rendezvous 后，每个执行4000次被锁保护的
  load/delay/store；断言和最后 telemetry 要求 participant mask3、value8000、
  inside0、violations0，以及**非零真实锁争用**，而不是两个 hart 各打印一句话。
- remote RUNNING kill 必须有 deferred→owner completion→zombie 的次序；等待
  完成之前不能回收，之后不能继续用户计数。
- 表容量、未 wait 的 zombie、精确状态、ownership、stale PID、重复 wait、reap
  后 relaunch、非法地址与未知 syscall 都通过 U syscall 路径执行。
  fill 阶段可能包含已退出的远程 child；测试的是所有 occupied slots 都不能复用，
  不是声称七个 EXIT worker 同一时刻都仍 RUNNING。
- 每个有效 wait 都有 `wait-call(parent,target)`。host model 把它与那个 child 的
  状态/status、parent WAITING、wait-return 和 reap 顺序关联；不能用不相关的
  status 列表或 zombie/reap 集合凑 PASS。blocking 与 immediate 路径都必须存在。
- `disk-bad-context.img` 破坏真实恢复的 a3，要求 `FAIL: spin context restore`。
- `disk-bad-lock.img` 使用同一 user payload，但 kernel 启动测试专用的 lock bypass。
  两个 worker 的首次 counter read 被 barrier 固定在两个 store 之前，因此至少
  丢一次更新；必须触发 `shared counter lost update` 和 `FAIL: user assertion`。
  barrier 本身不是所缺失的临界区锁，不会把错误实现又保护起来。
- 日志 mutants 删除 wait-call/wait-block/kill-complete、换 wait target 或 child
  status、伪造 hart/PC、删除容量证据或追加 late failure，都必须被 oracle 拒绝。

主要证据：`positive-0.log`–`positive-4.log`、`pty.log`、`bad-context.log`、
`bad-lock.log`、`oracle-mutations.log`、`timeout-rejected.log`，均在
`build/lesson08/`。各次的 PC、进度、争用、timer/idle 数值不要求相同。

### 实际 GDB 检查

`make test-lesson08-gdb` 分别启动两个真实磁盘 VM，分别检查 hart0/hart1 一次
非零进度的 timer frame：RUNNING/owner、U tp、恢复后的实际 SP/sepc/sscratch、
stack metadata、M stack、PMP/Sstc/delegation 和本地 deadline。随后 detach，两个
hart 一起继续，完整 guest oracle 仍须通过。日志为 `gdb-hart0.log` /
`gdb-hart1.log` 及对应 `gdb-hart*-uart.log`。

三个容易把 debugger 问题当成 scheduler 问题的细节：

1. 先在 kernel entry 用硬件断点等待 **磁盘加载完成**，再刷新 GDB memory cache
   并设需要解码指令的断点；在尚为零的目标内存上解码会认错 instruction size。
2. thread-specific 软件断点仍插在**两个 CPU** 的共同地址。若另一 hart 先到
   `sret`，GDB 虽不会把它报告为目标命中，却会自动只运行那个 CPU、试图单步到
   `pc+4`；`sret` 实际跳到 sepc，目标 hart 则被一直暂停在 epilogue 中。重现时
   remote protocol 确认了这一点；这甚至不要求全局锁被占用。
3. 脚本先在普通 `mv` 上筛选 timer frame，再删除筛选断点，**仅在已解锁、无锁
   获取的直线恢复 epilogue 内开启 `scheduler-locking on`**，随后用一次性
   thread-specific sret 断点检查。这样另一 hart 不会误撞该 sret 断点。不要在
   trap_dispatch/idle/持锁路径上照搬单 hart 执行。最后 detach 恢复两个 CPU，
   完整 guest oracle 仍必须成功；不是跳过 timer 或恢复断言。

GDB 仍保留30秒失败上界，不重试、不延长。若超时，runner 把
`TimeoutExpired.stdout`（即便 `text=True` 也可能是 bytes）解码后写到同一
`gdb-hartN.log` 并打印；对应 UART 日志保留。runner 自身的真实 subprocess
成功/非零退出/超时回归可运行 `python3 lessons/08/gdb-runner-test.py`。

本 hart 解锁不代表 GDB 停下时**全局锁值必须为0**：另一个 hart 可以已经获锁。
所以检查的是 `scheduler_owner != 当前 hart`。本 QEMU 的 GDB register XML 没有
导出 stimecmp，脚本不伪造这个读取；用实际本地 timer trap 与 deadline 交叉验证。

## 尚未做的事

固定 affinity、全局锁与轮询 idle 都是明确的教学取舍。没有 migration、用户地址
隔离、文件系统、UART RX IRQ、getchar wait queue 或交互 shell。后续 console 的
条件检查/等待注册必须与 IRQ enqueue/wakeup 在同一锁契约内完成，避免丢失唤醒；
不能沿用“持全局锁等一个字符”的方式。这里没有提前实现 lesson09。
