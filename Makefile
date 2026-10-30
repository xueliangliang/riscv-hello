CROSS_COMPILE ?= riscv64-linux-gnu-
CC := $(CROSS_COMPILE)gcc
OBJCOPY := $(CROSS_COMPILE)objcopy
READELF := $(CROSS_COMPILE)readelf
OBJDUMP := $(CROSS_COMPILE)objdump
QEMU ?= qemu-system-riscv64
PYTHON ?= python3

MARCH := rv64imac_zicsr_zifencei
MABI := lp64
CFLAGS := -march=$(MARCH) -mabi=$(MABI) -mcmodel=medany -g -ffreestanding -fno-builtin -fno-pic -fno-stack-protector -Wall -Wextra
LESSON02_CFLAGS := $(CFLAGS) -msmall-data-limit=0

.PHONY: all clean tools inspect test test-lesson01 test-lesson02 test-lesson03 lesson02 lesson03
all: build/lesson01.elf build/lesson01.bin build/lesson02.elf build/lesson02.bin \
	build/lesson03/bootloader.elf build/lesson03/kernel.bin build/lesson03/shell.bin \
	build/lesson03/disk.img

build:
	mkdir -p $@

build/lesson02:
	mkdir -p $@

build/lesson03:
	mkdir -p $@

build/start.o: start.S | build
	$(CC) $(CFLAGS) -c -o $@ $<

build/lesson01.elf: build/start.o linker.ld
	$(CC) $(CFLAGS) -nostdlib -static -Wl,--build-id=none -T linker.ld -o $@ build/start.o

build/lesson01.bin: build/lesson01.elf
	$(OBJCOPY) -O binary $< $@

build/lesson02/start.o: lessons/02/start.S | build/lesson02
	$(CC) $(LESSON02_CFLAGS) -c -o $@ $<

build/lesson02/uart.o: lessons/02/uart.c lessons/02/uart.h | build/lesson02
	$(CC) $(LESSON02_CFLAGS) -c -o $@ $<

build/lesson02/hello.o: lessons/02/hello.c lessons/02/uart.h | build/lesson02
	$(CC) $(LESSON02_CFLAGS) -c -o $@ $<

build/lesson02.elf: build/lesson02/start.o build/lesson02/uart.o build/lesson02/hello.o lessons/02/linker.ld
	$(CC) $(LESSON02_CFLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/02/linker.ld -o $@ build/lesson02/start.o build/lesson02/uart.o build/lesson02/hello.o

build/lesson02.bin: build/lesson02.elf
	$(OBJCOPY) -O binary $< $@

lesson02: build/lesson02.elf build/lesson02.bin

build/lesson03/bootloader.o: lessons/03/bootloader.c lessons/03/boot_record.h lessons/03/virtio_blk.h lessons/02/uart.h | build/lesson03
	$(CC) $(LESSON02_CFLAGS) -Ilessons/02 -Ilessons/03 -c -o $@ $<

build/lesson03/virtio_blk.o: lessons/03/virtio_blk.c lessons/03/virtio_blk.h | build/lesson03
	$(CC) $(LESSON02_CFLAGS) -Ilessons/03 -c -o $@ $<

build/lesson03/kernel.o: lessons/03/kernel.c lessons/02/uart.h | build/lesson03
	$(CC) $(LESSON02_CFLAGS) -Ilessons/02 -c -o $@ $<

build/lesson03/shell.o: lessons/03/shell.c lessons/02/uart.h | build/lesson03
	$(CC) $(LESSON02_CFLAGS) -Ilessons/02 -c -o $@ $<

build/lesson03/bootloader.elf: build/lesson02/start.o build/lesson02/uart.o build/lesson03/bootloader.o build/lesson03/virtio_blk.o lessons/02/linker.ld
	$(CC) $(LESSON02_CFLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/02/linker.ld -o $@ build/lesson02/start.o build/lesson02/uart.o build/lesson03/bootloader.o build/lesson03/virtio_blk.o

build/lesson03/kernel.elf: build/lesson02/start.o build/lesson02/uart.o build/lesson03/kernel.o lessons/03/kernel.ld
	$(CC) $(LESSON02_CFLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/03/kernel.ld -o $@ build/lesson02/start.o build/lesson02/uart.o build/lesson03/kernel.o

build/lesson03/shell.elf: build/lesson02/uart.o build/lesson03/shell.o lessons/03/shell.ld
	$(CC) $(LESSON02_CFLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/03/shell.ld -o $@ build/lesson03/shell.o build/lesson02/uart.o

build/lesson03/kernel.bin: build/lesson03/kernel.elf
	$(OBJCOPY) -O binary $< $@
	test "$$(stat -c %s $@)" -le 65536

build/lesson03/shell.bin: build/lesson03/shell.elf
	$(OBJCOPY) -O binary $< $@
	test "$$(stat -c %s $@)" -le 65536

build/lesson03/disk.img: build/lesson03/kernel.bin build/lesson03/shell.bin tools/make-disk-image.py
	$(PYTHON) tools/make-disk-image.py build/lesson03/kernel.bin build/lesson03/shell.bin $@

build/lesson03/disk-bad-magic.img: build/lesson03/kernel.bin build/lesson03/shell.bin tools/make-disk-image.py
	$(PYTHON) tools/make-disk-image.py build/lesson03/kernel.bin build/lesson03/shell.bin $@ --corrupt-magic

lesson03: build/lesson03/bootloader.elf build/lesson03/kernel.bin build/lesson03/shell.bin build/lesson03/disk.img

tools:
	@$(CC) --version | sed -n '1p'
	@$(READELF) --version | sed -n '1p'
	@$(QEMU) --version | sed -n '1p'
	@$(PYTHON) --version

inspect: build/lesson01.elf build/lesson01.bin build/lesson02.elf build/lesson02.bin build/lesson03/bootloader.elf build/lesson03/kernel.elf build/lesson03/shell.elf
	$(READELF) -h -lW build/lesson01.elf
	$(OBJDUMP) -d build/lesson01.elf
	$(READELF) -h -lW build/lesson02.elf
	$(OBJDUMP) -d build/lesson02.elf
	$(READELF) -h -lW build/lesson03/bootloader.elf
	$(READELF) -h -lW build/lesson03/kernel.elf
	$(READELF) -h -lW build/lesson03/shell.elf
	@printf '\nLesson 01 ELF bytes: '; stat -c %s build/lesson01.elf
	@printf 'Lesson 01 raw binary bytes: '; stat -c %s build/lesson01.bin
	@printf 'Lesson 02 ELF bytes: '; stat -c %s build/lesson02.elf
	@printf 'Lesson 02 raw binary bytes: '; stat -c %s build/lesson02.bin
	@printf 'Lesson 03 bootloader ELF bytes: '; stat -c %s build/lesson03/bootloader.elf
	@printf 'Lesson 03 kernel raw bytes: '; stat -c %s build/lesson03/kernel.bin
	@printf 'Lesson 03 shell raw bytes: '; stat -c %s build/lesson03/shell.bin

test-lesson01: build/lesson01.elf
	QEMU="$(QEMU)" READELF="$(READELF)" ./tests/run-qemu.sh build/lesson01.elf

test-lesson02: build/lesson02.elf
	QEMU="$(QEMU)" READELF="$(READELF)" ./tests/run-qemu.sh build/lesson02.elf "Lesson 02: C main entered with a valid stack." "PASS: C runtime, stack, BSS, initialized data, and UART verified."

test-lesson03: build/lesson03/bootloader.elf build/lesson03/disk.img build/lesson03/disk-bad-magic.img
	QEMU="$(QEMU)" READELF="$(READELF)" ./tests/run-lesson03.sh build/lesson03/bootloader.elf build/lesson03/disk.img build/lesson03/disk-bad-magic.img

test: test-lesson01 test-lesson02 test-lesson03

# Lessons 04+: reuse lesson03's unmodified bootloader and disk format.
PRIV_CFLAGS := $(LESSON02_CFLAGS) -fno-unwind-tables -fno-asynchronous-unwind-tables -Ilessons/02 -Ilessons/04
PRIV_COMMON := build/lesson04/start.o build/lesson04/trap.o build/lesson04/runtime.o build/lesson02/uart.o

build/lesson04:
	mkdir -p $@

build/lesson04/%.o: lessons/04/%.S | build/lesson04
	$(CC) $(PRIV_CFLAGS) -c -o $@ $<

build/lesson04/%.o: lessons/04/%.c lessons/04/runtime.h | build/lesson04
	$(CC) $(PRIV_CFLAGS) -c -o $@ $<

build/lesson04/kernel.elf: $(PRIV_COMMON) build/lesson04/kernel.o lessons/03/kernel.ld
	$(CC) $(PRIV_CFLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/03/kernel.ld -o $@ $(PRIV_COMMON) build/lesson04/kernel.o

build/lesson04/user.elf: build/lesson04/user.o lessons/04/user.ld
	$(CC) $(PRIV_CFLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/04/user.ld -o $@ $<

build/lesson04/user-bad-cause.o: lessons/04/user.S | build/lesson04
	$(CC) $(PRIV_CFLAGS) -DBAD_CAUSE -c -o $@ $<

build/lesson04/user-bad-pc.o: lessons/04/user.S | build/lesson04
	$(CC) $(PRIV_CFLAGS) -DBAD_PC -c -o $@ $<

build/lesson04/user-%.elf: build/lesson04/user-%.o lessons/04/user.ld
	$(CC) $(PRIV_CFLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/04/user.ld -o $@ $<

build/lesson04/%.bin: build/lesson04/%.elf
	$(OBJCOPY) -O binary $< $@
	test "$$(stat -c %s $@)" -le 65536

build/lesson04/disk.img: build/lesson04/kernel.bin build/lesson04/user.bin tools/make-disk-image.py
	$(PYTHON) tools/make-disk-image.py $< build/lesson04/user.bin $@

build/lesson04/disk-%.img: build/lesson04/kernel.bin build/lesson04/user-%.bin tools/make-disk-image.py
	$(PYTHON) tools/make-disk-image.py $< build/lesson04/user-$*.bin $@

.PHONY: lesson04 test-lesson04 inspect-lesson04
lesson04: build/lesson03/bootloader.elf build/lesson04/disk.img
all: lesson04

test-lesson04: lesson04 build/lesson04/disk-bad-cause.img build/lesson04/disk-bad-pc.img
	QEMU="$(QEMU)" $(PYTHON) tests/run-privilege.py 04

test: test-lesson04

inspect-lesson04: build/lesson04/kernel.elf build/lesson04/user.elf
	$(READELF) -h -lW build/lesson04/kernel.elf build/lesson04/user.elf
	$(OBJDUMP) -d build/lesson04/kernel.elf build/lesson04/user.elf

inspect: inspect-lesson04

build/lesson05:
	mkdir -p $@

build/lesson05/%.o: lessons/05/%.c lessons/05/libc.h lessons/05/abi.h lessons/04/runtime.h | build/lesson05
	$(CC) $(PRIV_CFLAGS) -Ilessons/05 -c -o $@ $<

build/lesson05/user-start.o: lessons/05/user-start.S | build/lesson05
	$(CC) $(PRIV_CFLAGS) -c -o $@ $<

build/lesson05/kernel.elf: $(PRIV_COMMON) build/lesson05/kernel.o lessons/03/kernel.ld
	$(CC) $(PRIV_CFLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/03/kernel.ld -o $@ $(PRIV_COMMON) build/lesson05/kernel.o

build/lesson05/user.elf: build/lesson05/user-start.o build/lesson05/user.o build/lesson05/libc.o lessons/04/user.ld
	$(CC) $(PRIV_CFLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/04/user.ld -o $@ build/lesson05/user-start.o build/lesson05/user.o build/lesson05/libc.o

build/lesson05/user-bad-exit.o: lessons/05/user.c lessons/05/libc.h lessons/05/abi.h | build/lesson05
	$(CC) $(PRIV_CFLAGS) -Ilessons/05 -DBAD_EXIT -c -o $@ $<

build/lesson05/user-bad-trap.o: lessons/05/user.c lessons/05/libc.h lessons/05/abi.h | build/lesson05
	$(CC) $(PRIV_CFLAGS) -Ilessons/05 -DBAD_TRAP -c -o $@ $<

build/lesson05/user-%.elf: build/lesson05/user-%.o build/lesson05/user-start.o build/lesson05/libc.o lessons/04/user.ld
	$(CC) $(PRIV_CFLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/04/user.ld -o $@ build/lesson05/user-start.o $< build/lesson05/libc.o

build/lesson05/%.bin: build/lesson05/%.elf
	$(OBJCOPY) -O binary $< $@
	test "$$(stat -c %s $@)" -le 65536

build/lesson05/disk.img: build/lesson05/kernel.bin build/lesson05/user.bin tools/make-disk-image.py
	$(PYTHON) tools/make-disk-image.py $< build/lesson05/user.bin $@

build/lesson05/disk-%.img: build/lesson05/kernel.bin build/lesson05/user-%.bin tools/make-disk-image.py
	$(PYTHON) tools/make-disk-image.py $< build/lesson05/user-$*.bin $@

.PHONY: lesson05 test-lesson05 inspect-lesson05
lesson05: build/lesson03/bootloader.elf build/lesson05/disk.img
all: lesson05

test-lesson05: lesson05 build/lesson05/disk-bad-exit.img build/lesson05/disk-bad-trap.img
	QEMU="$(QEMU)" $(PYTHON) tests/run-privilege.py 05

test: test-lesson05

inspect-lesson05: build/lesson05/kernel.elf build/lesson05/user.elf
	$(READELF) -h -lW build/lesson05/kernel.elf build/lesson05/user.elf
	$(OBJDUMP) -d build/lesson05/kernel.elf build/lesson05/user.elf

inspect: inspect-lesson05

clean:
	rm -rf build

# Lesson06 owns its interrupt-enabled entry/epilogue; prior runtimes stay fixed.
TIMER_COMMON := build/lesson06/start.o build/lesson04/runtime.o build/lesson02/uart.o
TIMER_FLAGS := $(PRIV_CFLAGS) -Ibuild/lesson06
TIMER_VARIANTS := bad-context bad-pc omit-pc

build/lesson06:
	mkdir -p $@

build/lesson06/%.o: lessons/06/%.S | build/lesson06
	$(CC) $(TIMER_FLAGS) -c -o $@ $<

build/lesson06/user.elf: build/lesson06/user.o lessons/04/user.ld
	$(CC) $(TIMER_FLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/04/user.ld -o $@ $<

build/lesson06/user-symbols.h: build/lesson06/user.elf lessons/06/symbols.py
	$(PYTHON) lessons/06/symbols.py $(CROSS_COMPILE)nm $< $@

build/lesson06/kernel.o: lessons/06/kernel.c build/lesson06/user-symbols.h lessons/04/runtime.h
	$(CC) $(TIMER_FLAGS) -c -o $@ $<

build/lesson06/trap-bad-context.o: lessons/06/trap.S | build/lesson06
	$(CC) $(TIMER_FLAGS) -DBAD_CONTEXT -c -o $@ $<

build/lesson06/trap-bad-pc.o: lessons/06/trap.S | build/lesson06
	$(CC) $(TIMER_FLAGS) -DBAD_PC -c -o $@ $<

build/lesson06/trap-omit-pc.o: lessons/06/trap.S | build/lesson06
	$(CC) $(TIMER_FLAGS) -DOMIT_PC -c -o $@ $<

build/lesson06/kernel.elf: $(TIMER_COMMON) build/lesson06/trap.o build/lesson06/kernel.o lessons/03/kernel.ld
	$(CC) $(TIMER_FLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/03/kernel.ld -o $@ $(TIMER_COMMON) build/lesson06/trap.o build/lesson06/kernel.o

build/lesson06/kernel-%.elf: $(TIMER_COMMON) build/lesson06/trap-%.o build/lesson06/kernel.o lessons/03/kernel.ld
	$(CC) $(TIMER_FLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/03/kernel.ld -o $@ $(TIMER_COMMON) build/lesson06/trap-$*.o build/lesson06/kernel.o

build/lesson06/%.bin: build/lesson06/%.elf
	$(OBJCOPY) -O binary $< $@
	test "$$(stat -c %s $@)" -le 65536

build/lesson06/disk.img: build/lesson06/kernel.bin build/lesson06/user.bin tools/make-disk-image.py
	$(PYTHON) tools/make-disk-image.py $< build/lesson06/user.bin $@

build/lesson06/disk-%.img: build/lesson06/kernel-%.bin build/lesson06/user.bin tools/make-disk-image.py
	$(PYTHON) tools/make-disk-image.py $< build/lesson06/user.bin $@

.PHONY: lesson06 test-lesson06 inspect-lesson06
lesson06: build/lesson03/bootloader.elf build/lesson06/disk.img
all: lesson06

test-lesson06: lesson06 $(addprefix build/lesson06/disk-,$(addsuffix .img,$(TIMER_VARIANTS)))
	QEMU="$(QEMU)" NM="$(CROSS_COMPILE)nm" OBJDUMP="$(OBJDUMP)" $(PYTHON) lessons/06/test.py

test: test-lesson06

inspect-lesson06: build/lesson06/kernel.elf build/lesson06/user.elf
	$(READELF) -h -lW build/lesson06/kernel.elf build/lesson06/user.elf
	$(OBJDUMP) -d build/lesson06/kernel.elf build/lesson06/user.elf

inspect: inspect-lesson06

# Lesson07 owns all scheduling/runtime files; lesson03 remains the only -kernel.
SCHED_FLAGS := $(LESSON02_CFLAGS) -O1 -fno-unwind-tables -fno-asynchronous-unwind-tables -Ilessons/02 -Ilessons/07 -Ibuild/lesson07
SCHED_COMMON := build/lesson07/start.o build/lesson07/runtime.o build/lesson07/kernel.o build/lesson02/uart.o

build/lesson07:
	mkdir -p $@

build/lesson07/%.o: lessons/07/%.S | build/lesson07
	$(CC) $(SCHED_FLAGS) -c -o $@ $<

build/lesson07/%.o: lessons/07/%.c lessons/07/abi.h lessons/07/runtime.h lessons/07/process.h lessons/07/syscall.h | build/lesson07
	$(CC) $(SCHED_FLAGS) -c -o $@ $<

build/lesson07/user.elf: build/lesson07/user-start.o build/lesson07/user.o build/lesson07/workers.o build/lesson07/syscall.o lessons/07/user.ld
	$(CC) $(SCHED_FLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/07/user.ld -o $@ $(filter %.o,$^)

build/lesson07/user-symbols.h: build/lesson07/user.elf lessons/07/symbols.py
	$(PYTHON) lessons/07/symbols.py $(CROSS_COMPILE)nm $< $@

build/lesson07/kernel.o: build/lesson07/user-symbols.h

build/lesson07/kernel.elf: $(SCHED_COMMON) build/lesson07/trap.o lessons/03/kernel.ld
	$(CC) $(SCHED_FLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/03/kernel.ld -o $@ $(filter %.o,$^)

build/lesson07/trap-bad-context.o: lessons/07/trap.S | build/lesson07
	$(CC) $(SCHED_FLAGS) -DBAD_CONTEXT -c -o $@ $<

build/lesson07/kernel-bad-context.elf: $(SCHED_COMMON) build/lesson07/trap-bad-context.o lessons/03/kernel.ld
	$(CC) $(SCHED_FLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/03/kernel.ld -o $@ $(filter %.o,$^)

build/lesson07/%.bin: build/lesson07/%.elf
	$(OBJCOPY) -O binary $< $@
	test "$$(stat -c %s $@)" -le 65536

build/lesson07/disk.img: build/lesson07/kernel.bin build/lesson07/user.bin tools/make-disk-image.py
	$(PYTHON) tools/make-disk-image.py $< build/lesson07/user.bin $@

build/lesson07/disk-bad-context.img: build/lesson07/kernel-bad-context.bin build/lesson07/user.bin tools/make-disk-image.py
	$(PYTHON) tools/make-disk-image.py $< build/lesson07/user.bin $@

.PHONY: lesson07 test-lesson07 inspect-lesson07
lesson07: build/lesson03/bootloader.elf build/lesson07/disk.img
all: lesson07

test-lesson07: lesson07 build/lesson07/disk-bad-context.img
	QEMU="$(QEMU)" NM="$(CROSS_COMPILE)nm" OBJDUMP="$(OBJDUMP)" $(PYTHON) lessons/07/test.py

test: test-lesson07

inspect-lesson07: build/lesson07/kernel.elf build/lesson07/user.elf
	$(READELF) -h -lW build/lesson07/kernel.elf build/lesson07/user.elf
	$(OBJDUMP) -d build/lesson07/kernel.elf build/lesson07/user.elf

inspect: inspect-lesson07

.PHONY: test-lesson07-gdb
test-lesson07-gdb: lesson07
	$(PYTHON) lessons/07/gdb-test.py

# Lesson08 has a hart-filtering boot wrapper; unchanged lesson03 C loads disk.
SMP_FLAGS := $(LESSON02_CFLAGS) -O1 -fno-unwind-tables -fno-asynchronous-unwind-tables -Ilessons/02 -Ilessons/08 -Ibuild/lesson08
SMP_COMMON := build/lesson08/start.o build/lesson08/runtime.o build/lesson08/kernel.o build/lesson02/uart.o

build/lesson08:
	mkdir -p $@

build/lesson08/%.o: lessons/08/%.S | build/lesson08
	$(CC) $(SMP_FLAGS) -c -o $@ $<

build/lesson08/%.o: lessons/08/%.c lessons/08/abi.h lessons/08/runtime.h lessons/08/process.h lessons/08/syscall.h | build/lesson08
	$(CC) $(SMP_FLAGS) -c -o $@ $<

build/lesson08/user.elf: build/lesson08/user-start.o build/lesson08/user.o build/lesson08/workers.o build/lesson08/syscall.o lessons/08/user.ld
	$(CC) $(SMP_FLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/08/user.ld -o $@ $(filter %.o,$^)

build/lesson08/user-symbols.h: build/lesson08/user.elf lessons/08/symbols.py
	$(PYTHON) lessons/08/symbols.py $(CROSS_COMPILE)nm $< $@

build/lesson08/kernel.o: build/lesson08/user-symbols.h

build/lesson08/kernel.elf: $(SMP_COMMON) build/lesson08/trap.o lessons/08/kernel.ld
	$(CC) $(SMP_FLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/08/kernel.ld -o $@ $(filter %.o,$^)

build/lesson08/trap-bad-context.o: lessons/08/trap.S | build/lesson08
	$(CC) $(SMP_FLAGS) -DBAD_CONTEXT -c -o $@ $<

build/lesson08/kernel-bad-context.elf: $(SMP_COMMON) build/lesson08/trap-bad-context.o lessons/08/kernel.ld
	$(CC) $(SMP_FLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/08/kernel.ld -o $@ $(filter %.o,$^)

build/lesson08/%.bin: build/lesson08/%.elf
	$(OBJCOPY) -O binary $< $@
	test "$$(stat -c %s $@)" -le 65536

build/lesson08/disk.img: build/lesson08/kernel.bin build/lesson08/user.bin tools/make-disk-image.py
	$(PYTHON) tools/make-disk-image.py $< build/lesson08/user.bin $@

build/lesson08/disk-bad-context.img: build/lesson08/kernel-bad-context.bin build/lesson08/user.bin tools/make-disk-image.py
	$(PYTHON) tools/make-disk-image.py $< build/lesson08/user.bin $@

.PHONY: lesson08 test-lesson08 inspect-lesson08
lesson08: build/lesson08/bootloader.elf build/lesson08/disk.img
all: lesson08

test-lesson08: lesson08 build/lesson08/disk-bad-context.img build/lesson08/disk-bad-lock.img
	QEMU="$(QEMU)" NM="$(CROSS_COMPILE)nm" OBJDUMP="$(OBJDUMP)" $(PYTHON) lessons/08/test.py

test: test-lesson08

inspect-lesson08: build/lesson08/bootloader.elf build/lesson08/kernel.elf build/lesson08/user.elf
	$(READELF) -h -lW $^
	$(OBJDUMP) -d $^

inspect: inspect-lesson08


build/lesson08/bootloader.elf: build/lesson08/boot.o build/lesson02/uart.o build/lesson03/bootloader.o build/lesson03/virtio_blk.o lessons/02/linker.ld
	$(CC) $(SMP_FLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/02/linker.ld -o $@ $(filter %.o,$^)

# Same U payload and symbol layout; only initialization selects broken locking.
build/lesson08/kernel-bad-lock.o: lessons/08/kernel.c build/lesson08/user-symbols.h lessons/08/process.h lessons/08/abi.h lessons/08/runtime.h
	$(CC) $(SMP_FLAGS) -DBAD_LOCK -c -o $@ $<

build/lesson08/kernel-bad-lock.elf: $(filter-out build/lesson08/kernel.o,$(SMP_COMMON)) build/lesson08/kernel-bad-lock.o build/lesson08/trap.o lessons/08/kernel.ld
	$(CC) $(SMP_FLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/08/kernel.ld -o $@ $(filter %.o,$^)

build/lesson08/disk-bad-lock.img: build/lesson08/kernel-bad-lock.bin build/lesson08/user.bin tools/make-disk-image.py
	$(PYTHON) tools/make-disk-image.py $< build/lesson08/user.bin $@

.PHONY: test-lesson08-gdb
test-lesson08-gdb: lesson08
	$(PYTHON) lessons/08/gdb-runner-test.py
	$(PYTHON) lessons/08/gdb-test.py

.PHONY: test-lesson09-gdb
test-lesson09-gdb: lesson09
	$(PYTHON) lessons/09/gdb-runner-test.py
	QEMU="$(QEMU)" $(PYTHON) lessons/09/gdb-test.py

# Lesson09: own disk-boot runtime and interactive payload.
CONSOLE_FLAGS := $(LESSON02_CFLAGS) -O1 -fno-unwind-tables -fno-asynchronous-unwind-tables -Ilessons/02 -Ilessons/09 -Ibuild/lesson09
CONSOLE_COMMON := build/lesson09/start.o build/lesson09/runtime.o build/lesson09/trap.o build/lesson02/uart.o
build/lesson09:
	mkdir -p $@
build/lesson09/%.o: lessons/09/%.S | build/lesson09
	$(CC) $(CONSOLE_FLAGS) -c -o $@ $<
build/lesson09/%.o: lessons/09/%.c lessons/09/abi.h lessons/09/process.h lessons/09/runtime.h lessons/09/syscall.h | build/lesson09
	$(CC) $(CONSOLE_FLAGS) -c -o $@ $<
build/lesson09/user.elf: build/lesson09/user-start.o build/lesson09/user.o build/lesson09/syscall.o lessons/09/user.ld
	$(CC) $(CONSOLE_FLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/09/user.ld -o $@ $(filter %.o,$^)
build/lesson09/user-symbols.h: build/lesson09/user.elf lessons/09/symbols.py
	$(PYTHON) lessons/09/symbols.py $(CROSS_COMPILE)nm $< $@
build/lesson09/kernel.o: build/lesson09/user-symbols.h
build/lesson09/kernel.elf: $(CONSOLE_COMMON) build/lesson09/kernel.o lessons/09/kernel.ld
	$(CC) $(CONSOLE_FLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/09/kernel.ld -o $@ $(filter %.o,$^)
build/lesson09/kernel-bad-irq.o: lessons/09/kernel.c build/lesson09/user-symbols.h | build/lesson09
	$(CC) $(CONSOLE_FLAGS) -DBAD_IRQ -c -o $@ $<
build/lesson09/kernel-bad-irq.elf: $(CONSOLE_COMMON) build/lesson09/kernel-bad-irq.o lessons/09/kernel.ld
	$(CC) $(CONSOLE_FLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/09/kernel.ld -o $@ $(filter %.o,$^)
build/lesson09/bootloader.elf: build/lesson09/boot.o build/lesson02/uart.o build/lesson03/bootloader.o build/lesson03/virtio_blk.o lessons/02/linker.ld
	$(CC) $(CONSOLE_FLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/02/linker.ld -o $@ $(filter %.o,$^)
build/lesson09/%.bin: build/lesson09/%.elf
	$(OBJCOPY) -O binary $< $@
	test "$$(stat -c %s $@)" -le 65536
build/lesson09/disk.img: build/lesson09/kernel.bin build/lesson09/user.bin tools/make-disk-image.py
	$(PYTHON) tools/make-disk-image.py $< build/lesson09/user.bin $@
build/lesson09/disk-bad-irq.img: build/lesson09/kernel-bad-irq.bin build/lesson09/user.bin tools/make-disk-image.py
	$(PYTHON) tools/make-disk-image.py $< build/lesson09/user.bin $@
.PHONY: lesson09 test-lesson09 inspect-lesson09 run-lesson09
lesson09: build/lesson09/bootloader.elf build/lesson09/disk.img
all: lesson09
test-lesson09: lesson09 build/lesson09/disk-bad-irq.img
	QEMU="$(QEMU)" $(PYTHON) lessons/09/test.py
test: test-lesson09
inspect-lesson09: build/lesson09/bootloader.elf build/lesson09/kernel.elf build/lesson09/user.elf
	$(READELF) -h -lW $^
	$(OBJDUMP) -d $^
inspect: inspect-lesson09
run-lesson09: lesson09
	$(PYTHON) lessons/09/run.py

# Lesson10: independent runtime queue and persistent FlatFS fixture.
FLAT_FLAGS := $(LESSON02_CFLAGS) -O1 -fno-unwind-tables -fno-asynchronous-unwind-tables -Ilessons/02 -Ilessons/10 -Ibuild/lesson10
FLAT_COMMON := build/lesson10/start.o build/lesson10/runtime.o build/lesson10/trap.o build/lesson10/fs.o build/lesson02/uart.o
build/lesson10:
	mkdir -p $@
build/lesson10/%.o: lessons/10/%.S | build/lesson10
	$(CC) $(FLAT_FLAGS) -c -o $@ $<
build/lesson10/%.o: lessons/10/%.c $(wildcard lessons/10/*.h) | build/lesson10
	$(CC) $(FLAT_FLAGS) -c -o $@ $<
build/lesson10/user.elf: build/lesson10/user-start.o build/lesson10/user.o build/lesson10/filetest.o build/lesson10/syscall.o lessons/10/user.ld
	$(CC) $(FLAT_FLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/10/user.ld -o $@ $(filter %.o,$^)
build/lesson10/user-symbols.h: build/lesson10/user.elf lessons/10/symbols.py
	$(PYTHON) lessons/10/symbols.py $(CROSS_COMPILE)nm $< $@
build/lesson10/kernel.o: build/lesson10/user-symbols.h
build/lesson10/kernel.elf: $(FLAT_COMMON) build/lesson10/block.o build/lesson10/kernel.o lessons/10/kernel.ld
	$(CC) $(FLAT_FLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/10/kernel.ld -o $@ $(filter %.o,$^)
build/lesson10/block-no-flush.o: lessons/10/block.c lessons/10/block.h | build/lesson10
	$(CC) $(FLAT_FLAGS) -DNO_FLUSH -c -o $@ $<
build/lesson10/kernel-no-flush.elf: $(FLAT_COMMON) build/lesson10/block-no-flush.o build/lesson10/kernel.o lessons/10/kernel.ld
	$(CC) $(FLAT_FLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/10/kernel.ld -o $@ $(filter %.o,$^)
build/lesson10/bootloader.elf: build/lesson10/boot.o build/lesson02/uart.o build/lesson03/bootloader.o build/lesson03/virtio_blk.o lessons/02/linker.ld
	$(CC) $(FLAT_FLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/02/linker.ld -o $@ $(filter %.o,$^)
build/lesson10/%.bin: build/lesson10/%.elf
	$(OBJCOPY) -O binary $< $@
	test "$$(stat -c %s $@)" -le 65536
build/lesson10/disk.img: build/lesson10/kernel.bin build/lesson10/user.bin tools/make-disk-image.py lessons/10/format.py
	$(PYTHON) lessons/10/format.py build/lesson10/kernel.bin build/lesson10/user.bin $@
build/lesson10/disk-no-flush.img: build/lesson10/kernel-no-flush.bin build/lesson10/user.bin tools/make-disk-image.py lessons/10/format.py
	$(PYTHON) lessons/10/format.py build/lesson10/kernel-no-flush.bin build/lesson10/user.bin $@
.PHONY: lesson10 run-lesson10 reset-lesson10 test-lesson10 inspect-lesson10
lesson10: build/lesson10/bootloader.elf build/lesson10/disk.img
all: lesson10
run-lesson10: lesson10
	QEMU="$(QEMU)" $(PYTHON) lessons/10/run.py $(LESSON10_ARGS)
reset-lesson10: lesson10
	$(PYTHON) lessons/10/run.py --reset
# --reset is explicit destructive replacement, protected by the same host lock.
test-lesson10: lesson10 build/lesson10/disk-no-flush.img
	QEMU="$(QEMU)" $(PYTHON) lessons/10/test.py
test: test-lesson10
inspect-lesson10: build/lesson10/bootloader.elf build/lesson10/kernel.elf build/lesson10/user.elf
	$(READELF) -h -lW $^
	$(OBJDUMP) -d $^
inspect: inspect-lesson10

.PHONY: test-lesson10-gdb
# Truncate before building: neither a build failure nor a runner failure may
# leave the previous run's PASS behind.
test-lesson10-gdb:
	@mkdir -p build/lesson10
	$(PYTHON) lessons/10/fresh-log.py build/lesson10/gdb-flush.log
	+$(MAKE) --no-print-directory lesson10
	$(PYTHON) lessons/10/gdb-runner-test.py
	QEMU="$(QEMU)" $(PYTHON) lessons/10/gdb-test.py

# Lesson11: independent runtime queue and persistent FlatFS fixture.
BPT_FLAGS := $(LESSON02_CFLAGS) -O1 -fno-unwind-tables -fno-asynchronous-unwind-tables -Ilessons/02 -Ilessons/11 -Ibuild/lesson11
BPT_COMMON := build/lesson11/start.o build/lesson11/runtime.o build/lesson11/trap.o build/lesson11/fs.o build/lesson02/uart.o
build/lesson11:
	mkdir -p $@
build/lesson11/%.o: lessons/11/%.S | build/lesson11
	$(CC) $(BPT_FLAGS) -c -o $@ $<
build/lesson11/%.o: lessons/11/%.c $(wildcard lessons/11/*.h) | build/lesson11
	$(CC) $(BPT_FLAGS) -c -o $@ $<
build/lesson11/user.elf: build/lesson11/user-start.o build/lesson11/user.o build/lesson11/filetest.o build/lesson11/syscall.o lessons/11/user.ld
	$(CC) $(BPT_FLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/11/user.ld -o $@ $(filter %.o,$^)
build/lesson11/user-symbols.h: build/lesson11/user.elf lessons/11/symbols.py
	$(PYTHON) lessons/11/symbols.py $(CROSS_COMPILE)nm $< $@
build/lesson11/kernel.o: build/lesson11/user-symbols.h
build/lesson11/kernel.elf: $(BPT_COMMON) build/lesson11/block.o build/lesson11/kernel.o lessons/11/kernel.ld
	$(CC) $(BPT_FLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/11/kernel.ld -o $@ $(filter %.o,$^)
build/lesson11/block-no-flush.o: lessons/11/block.c lessons/11/block.h | build/lesson11
	$(CC) $(BPT_FLAGS) -DNO_FLUSH -c -o $@ $<
build/lesson11/kernel-no-flush.elf: $(BPT_COMMON) build/lesson11/block-no-flush.o build/lesson11/kernel.o lessons/11/kernel.ld
	$(CC) $(BPT_FLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/11/kernel.ld -o $@ $(filter %.o,$^)
build/lesson11/bootloader.elf: build/lesson11/boot.o build/lesson02/uart.o build/lesson03/bootloader.o build/lesson03/virtio_blk.o lessons/02/linker.ld
	$(CC) $(BPT_FLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/02/linker.ld -o $@ $(filter %.o,$^)
build/lesson11/%.bin: build/lesson11/%.elf
	$(OBJCOPY) -O binary $< $@
	test "$$(stat -c %s $@)" -le 65536
build/lesson11/disk.img: build/lesson11/kernel.bin build/lesson11/user.bin tools/make-disk-image.py lessons/11/format.py
	$(PYTHON) lessons/11/format.py build/lesson11/kernel.bin build/lesson11/user.bin $@
build/lesson11/disk-no-flush.img: build/lesson11/kernel-no-flush.bin build/lesson11/user.bin tools/make-disk-image.py lessons/11/format.py
	$(PYTHON) lessons/11/format.py build/lesson11/kernel-no-flush.bin build/lesson11/user.bin $@
.PHONY: lesson11 run-lesson11 reset-lesson11 test-lesson11 inspect-lesson11
lesson11: build/lesson11/bootloader.elf build/lesson11/disk.img
all: lesson11
run-lesson11: lesson11
	QEMU="$(QEMU)" $(PYTHON) lessons/11/run.py $(LESSON11_ARGS)
reset-lesson11: lesson11
	$(PYTHON) lessons/11/run.py --reset
# --reset is explicit destructive replacement, protected by the same host lock.
test-lesson11: lesson11 lesson10 build/lesson11/disk-no-flush.img
	QEMU="$(QEMU)" $(PYTHON) lessons/11/epoch-test.py
	QEMU="$(QEMU)" $(PYTHON) lessons/11/test.py
test: test-lesson11
inspect-lesson11: build/lesson11/bootloader.elf build/lesson11/kernel.elf build/lesson11/user.elf
	$(READELF) -h -lW $^
	$(OBJDUMP) -d $^
inspect: inspect-lesson11

.PHONY: test-lesson11-gdb
# Truncate before building: neither a build failure nor a runner failure may
# leave the previous run's PASS behind.
test-lesson11-gdb:
	@mkdir -p build/lesson11
	$(PYTHON) lessons/11/fresh-log.py build/lesson11/gdb-flush.log
	+$(MAKE) --no-print-directory lesson11
	$(PYTHON) lessons/11/gdb-runner-test.py
	QEMU="$(QEMU)" $(PYTHON) lessons/11/gdb-test.py

# Lesson12: bounded full-data redo journal over the B+ tree filesystem.
REDO_FLAGS := $(LESSON02_CFLAGS) -O1 -fno-unwind-tables -fno-asynchronous-unwind-tables -Ilessons/02 -Ilessons/12 -Ibuild/lesson12
REDO_COMMON := build/lesson12/start.o build/lesson12/runtime.o build/lesson12/trap.o build/lesson12/fs.o build/lesson12/journal.o build/lesson02/uart.o
build/lesson12:
	mkdir -p $@
build/lesson12/%.o: lessons/12/%.S | build/lesson12
	$(CC) $(REDO_FLAGS) -c -o $@ $<
build/lesson12/%.o: lessons/12/%.c $(wildcard lessons/12/*.h) | build/lesson12
	$(CC) $(REDO_FLAGS) -c -o $@ $<
build/lesson12/user.elf: build/lesson12/user-start.o build/lesson12/user.o build/lesson12/filetest.o build/lesson12/syscall.o lessons/12/user.ld
	$(CC) $(REDO_FLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/12/user.ld -o $@ $(filter %.o,$^)
build/lesson12/user-symbols.h: build/lesson12/user.elf lessons/12/symbols.py
	$(PYTHON) lessons/12/symbols.py $(CROSS_COMPILE)nm $< $@
build/lesson12/kernel.o: build/lesson12/user-symbols.h
build/lesson12/kernel.elf: $(REDO_COMMON) build/lesson12/block.o build/lesson12/kernel.o lessons/12/kernel.ld
	$(CC) $(REDO_FLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/12/kernel.ld -o $@ $(filter %.o,$^)
build/lesson12/block-no-flush.o: lessons/12/block.c lessons/12/block.h | build/lesson12
	$(CC) $(REDO_FLAGS) -DNO_FLUSH -c -o $@ $<
build/lesson12/kernel-no-flush.elf: $(REDO_COMMON) build/lesson12/block-no-flush.o build/lesson12/kernel.o lessons/12/kernel.ld
	$(CC) $(REDO_FLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/12/kernel.ld -o $@ $(filter %.o,$^)
build/lesson12/bootloader.elf: build/lesson12/boot.o build/lesson02/uart.o build/lesson03/bootloader.o build/lesson03/virtio_blk.o lessons/02/linker.ld
	$(CC) $(REDO_FLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/02/linker.ld -o $@ $(filter %.o,$^)
build/lesson12/%.bin: build/lesson12/%.elf
	$(OBJCOPY) -O binary $< $@
	test "$$(stat -c %s $@)" -le 65536
build/lesson12/disk.img: build/lesson12/kernel.bin build/lesson12/user.bin tools/make-disk-image.py lessons/12/format.py
	$(PYTHON) lessons/12/format.py build/lesson12/kernel.bin build/lesson12/user.bin $@
build/lesson12/disk-no-flush.img: build/lesson12/kernel-no-flush.bin build/lesson12/user.bin tools/make-disk-image.py lessons/12/format.py
	$(PYTHON) lessons/12/format.py build/lesson12/kernel-no-flush.bin build/lesson12/user.bin $@
.PHONY: lesson12 run-lesson12 reset-lesson12 test-lesson12 inspect-lesson12
lesson12: build/lesson12/bootloader.elf build/lesson12/disk.img
all: lesson12
run-lesson12: lesson12
	QEMU="$(QEMU)" $(PYTHON) lessons/12/run.py $(LESSON12_ARGS)
reset-lesson12: lesson12
	$(PYTHON) lessons/12/run.py --reset
# --reset is explicit destructive replacement, protected by the same host lock.
test-lesson12:
	QEMU="$(QEMU)" CC="$(CC)" OBJCOPY="$(OBJCOPY)" $(PYTHON) lessons/12/gate.py
test: test-lesson12
inspect-lesson12: build/lesson12/bootloader.elf build/lesson12/kernel.elf build/lesson12/user.elf
	$(READELF) -h -lW $^
	$(OBJDUMP) -d $^
inspect: inspect-lesson12

.PHONY: test-lesson12-gdb
# Truncate before building: neither a build failure nor a runner failure may
# leave the previous run's PASS behind.
test-lesson12-gdb:
	@mkdir -p build/lesson12
	$(PYTHON) lessons/12/fresh-log.py build/lesson12/gdb-flush.log
	+$(MAKE) --no-print-directory lesson12
	$(PYTHON) lessons/12/gdb-runner-test.py
	QEMU="$(QEMU)" $(PYTHON) lessons/12/gdb-test.py

# Lesson13: bounded full-data redo journal over the B+ tree filesystem.
LOADER_FLAGS := $(LESSON02_CFLAGS) -O1 -fno-unwind-tables -fno-asynchronous-unwind-tables -Ilessons/02 -Ilessons/13 -Ibuild/lesson13
LOADER_COMMON := build/lesson13/start.o build/lesson13/runtime.o build/lesson13/trap.o build/lesson13/fs.o build/lesson13/journal.o build/lesson02/uart.o
build/lesson13:
	mkdir -p $@
build/lesson13/%.o: lessons/13/%.S | build/lesson13
	$(CC) $(LOADER_FLAGS) -c -o $@ $<
build/lesson13/%.o: lessons/13/%.c $(wildcard lessons/13/*.h) | build/lesson13
	$(CC) $(LOADER_FLAGS) -c -o $@ $<
build/lesson13/user.elf: build/lesson13/user-start.o build/lesson13/user.o build/lesson13/filetest.o build/lesson13/syscall.o lessons/13/user.ld
	$(CC) $(LOADER_FLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/13/user.ld -o $@ $(filter %.o,$^)
build/lesson13/user-symbols.h: build/lesson13/user.elf lessons/13/symbols.py
	$(PYTHON) lessons/13/symbols.py $(CROSS_COMPILE)nm $< $@
build/lesson13/kernel.o: build/lesson13/user-symbols.h
build/lesson13/kernel.elf: $(LOADER_COMMON) build/lesson13/block.o build/lesson13/kernel.o build/lesson13/formats.o build/lesson13/snapshot.o lessons/13/kernel.ld
	$(CC) $(LOADER_FLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/13/kernel.ld -o $@ $(filter %.o,$^)
build/lesson13/block-no-flush.o: lessons/13/block.c lessons/13/block.h | build/lesson13
	$(CC) $(LOADER_FLAGS) -DNO_FLUSH -c -o $@ $<
build/lesson13/kernel-no-flush.elf: $(LOADER_COMMON) build/lesson13/block-no-flush.o build/lesson13/kernel.o build/lesson13/formats.o build/lesson13/snapshot.o lessons/13/kernel.ld
	$(CC) $(LOADER_FLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/13/kernel.ld -o $@ $(filter %.o,$^)
build/lesson13/bootloader.elf: build/lesson13/boot.o build/lesson02/uart.o build/lesson03/bootloader.o build/lesson03/virtio_blk.o lessons/02/linker.ld
	$(CC) $(LOADER_FLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/02/linker.ld -o $@ $(filter %.o,$^)
build/lesson13/%.bin: build/lesson13/%.elf
	$(OBJCOPY) -O binary $< $@
	test "$$(stat -c %s $@)" -le 65536
build/lesson13/disk.img: build/lesson13/kernel.bin build/lesson13/user.bin build/lesson13/math_test.exec build/lesson13/math.dll lessons/13/seed.py lessons/13/native.py tools/make-disk-image.py lessons/13/format.py
	$(PYTHON) lessons/13/seed.py build/lesson13/kernel.bin build/lesson13/user.bin $@
build/lesson13/disk-no-flush.img: build/lesson13/kernel-no-flush.bin build/lesson13/user.bin tools/make-disk-image.py lessons/13/format.py
	$(PYTHON) lessons/13/format.py build/lesson13/kernel-no-flush.bin build/lesson13/user.bin $@
.PHONY: lesson13 run-lesson13 reset-lesson13 test-lesson13 inspect-lesson13
lesson13: build/lesson13/bootloader.elf build/lesson13/disk.img
all: lesson13
run-lesson13: lesson13
	QEMU="$(QEMU)" $(PYTHON) lessons/13/run.py $(LESSON13_ARGS)
reset-lesson13: lesson13
	$(PYTHON) lessons/13/run.py --reset
# --reset is explicit destructive replacement, protected by the same host lock.
test-lesson13:
	QEMU="$(QEMU)" CC="$(CC)" $(PYTHON) lessons/13/gate.py
test: test-lesson13
inspect-lesson13: build/lesson13/bootloader.elf build/lesson13/kernel.elf build/lesson13/user.elf build/lesson13/math_test.elf build/lesson13/math.elf
	$(READELF) -h -lW $^
	$(OBJDUMP) -d $^
inspect: inspect-lesson13

# Pure PIC module and fixed-address ordinary-file application are NOT linked
# into the kernel/shell. They enter runtime exclusively via filesystem reads.
DLL_FLAGS := $(filter-out -fno-pic,$(LOADER_FLAGS)) -fPIC -fvisibility=hidden
build/lesson13/math_dll.o: lessons/13/math_dll.c | build/lesson13
	$(CC) $(DLL_FLAGS) -c -o $@ $<
build/lesson13/math_alt.o: lessons/13/math_dll.c | build/lesson13
	$(CC) $(DLL_FLAGS) -DALTERNATE -c -o $@ $<
build/lesson13/math.elf: build/lesson13/math_dll.o lessons/13/module.ld
	$(CC) $(DLL_FLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/13/module.ld -o $@ $<
build/lesson13/math-alt.elf: build/lesson13/math_alt.o lessons/13/module.ld
	$(CC) $(DLL_FLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/13/module.ld -o $@ $<
build/lesson13/math.dll: build/lesson13/math.elf lessons/13/pack.py
	$(OBJCOPY) -O binary --only-section=.text $< build/lesson13/math.text
	CROSS_COMPILE="$(CROSS_COMPILE)" $(PYTHON) lessons/13/pack.py module $< build/lesson13/math.text $@
build/lesson13/math-alt.dll: build/lesson13/math-alt.elf lessons/13/pack.py
	$(OBJCOPY) -O binary --only-section=.text $< build/lesson13/math-alt.text
	CROSS_COMPILE="$(CROSS_COMPILE)" $(PYTHON) lessons/13/pack.py module $< build/lesson13/math-alt.text $@
build/lesson13/math_test.elf: build/lesson13/app-start.o build/lesson13/math_test.o build/lesson13/module_loader.o build/lesson13/formats.o build/lesson13/syscall.o lessons/13/app.ld
	$(CC) $(LOADER_FLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/13/app.ld -o $@ $(filter %.o,$^)
build/lesson13/math_test.exec: build/lesson13/math_test.elf lessons/13/pack.py
	$(OBJCOPY) -O binary $< build/lesson13/math_test.raw
	CROSS_COMPILE="$(CROSS_COMPILE)" $(PYTHON) lessons/13/pack.py executable $< build/lesson13/math_test.raw $@

.PHONY: test-lesson13-gdb test-lesson13-evidence
# No prerequisites: invalidate evidence BEFORE even a recursive build fails.
test-lesson13-gdb:
	@mkdir -p build/lesson13
	$(PYTHON) lessons/13/fresh-log.py build/lesson13/gdb-loader.log
	+$(MAKE) --no-print-directory lesson13
	QEMU="$(QEMU)" $(PYTHON) lessons/13/gdb-test.py
test-lesson13-evidence:
	$(PYTHON) lessons/13/evidence-test.py

build/lesson13/io_test.elf: build/lesson13/app-start.o build/lesson13/io_test.o build/lesson13/module_loader.o build/lesson13/formats.o build/lesson13/syscall.o lessons/13/app.ld
	$(CC) $(LOADER_FLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/13/app.ld -o $@ $(filter %.o,$^)
build/lesson13/io_test.exec: build/lesson13/io_test.elf lessons/13/pack.py
	$(OBJCOPY) -O binary $< build/lesson13/io_test.raw
	CROSS_COMPILE="$(CROSS_COMPILE)" $(PYTHON) lessons/13/pack.py executable $< build/lesson13/io_test.raw $@

# Lesson14: bounded full-data redo journal over the B+ tree filesystem.
COMPILER_FLAGS := $(LESSON02_CFLAGS) -O1 -fno-unwind-tables -fno-asynchronous-unwind-tables -Ilessons/02 -Ilessons/14 -Ibuild/lesson14
COMPILER_COMMON := build/lesson14/start.o build/lesson14/runtime.o build/lesson14/trap.o build/lesson14/fs.o build/lesson14/journal.o build/lesson02/uart.o
build/lesson14:
	mkdir -p $@
build/lesson14/%.o: lessons/14/%.S | build/lesson14
	$(CC) $(COMPILER_FLAGS) -c -o $@ $<
build/lesson14/%.o: lessons/14/%.c $(wildcard lessons/14/*.h) | build/lesson14
	$(CC) $(COMPILER_FLAGS) -c -o $@ $<
build/lesson14/user.elf: build/lesson14/user-start.o build/lesson14/user.o build/lesson14/filetest.o build/lesson14/syscall.o lessons/14/user.ld
	$(CC) $(COMPILER_FLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/14/user.ld -o $@ $(filter %.o,$^)
build/lesson14/user-symbols.h: build/lesson14/user.elf lessons/14/symbols.py
	$(PYTHON) lessons/14/symbols.py $(CROSS_COMPILE)nm $< $@
build/lesson14/kernel.o: build/lesson14/user-symbols.h
build/lesson14/kernel.elf: $(COMPILER_COMMON) build/lesson14/block.o build/lesson14/kernel.o build/lesson14/formats.o build/lesson14/snapshot.o lessons/14/kernel.ld
	$(CC) $(COMPILER_FLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/14/kernel.ld -o $@ $(filter %.o,$^)
build/lesson14/block-no-flush.o: lessons/14/block.c lessons/14/block.h | build/lesson14
	$(CC) $(COMPILER_FLAGS) -DNO_FLUSH -c -o $@ $<
build/lesson14/kernel-no-flush.elf: $(COMPILER_COMMON) build/lesson14/block-no-flush.o build/lesson14/kernel.o build/lesson14/formats.o build/lesson14/snapshot.o lessons/14/kernel.ld
	$(CC) $(COMPILER_FLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/14/kernel.ld -o $@ $(filter %.o,$^)
build/lesson14/bootloader.elf: build/lesson14/boot.o build/lesson02/uart.o build/lesson03/bootloader.o build/lesson03/virtio_blk.o lessons/02/linker.ld
	$(CC) $(COMPILER_FLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/02/linker.ld -o $@ $(filter %.o,$^)
build/lesson14/%.bin: build/lesson14/%.elf
	$(OBJCOPY) -O binary $< $@
	test "$$(stat -c %s $@)" -le 65536
build/lesson14/disk.img: build/lesson14/kernel.bin build/lesson14/user.bin build/lesson14/math_test.exec build/lesson14/math.dll build/lesson14/cc.exec lessons/14/seed.py lessons/14/native.py tools/make-disk-image.py lessons/14/format.py
	$(PYTHON) lessons/14/seed.py build/lesson14/kernel.bin build/lesson14/user.bin $@
build/lesson14/disk-no-flush.img: build/lesson14/kernel-no-flush.bin build/lesson14/user.bin tools/make-disk-image.py lessons/14/format.py
	$(PYTHON) lessons/14/format.py build/lesson14/kernel-no-flush.bin build/lesson14/user.bin $@
.PHONY: lesson14 run-lesson14 reset-lesson14 test-lesson14 inspect-lesson14
lesson14: build/lesson14/bootloader.elf build/lesson14/disk.img
all: lesson14
run-lesson14: lesson14
	QEMU="$(QEMU)" $(PYTHON) lessons/14/run.py $(LESSON14_ARGS)
reset-lesson14: lesson14
	$(PYTHON) lessons/14/run.py --reset $(LESSON14_ARGS)
# --reset is explicit destructive replacement, protected by the same host lock.
test-lesson14:
	QEMU="$(QEMU)" CC="$(CC)" $(PYTHON) lessons/14/gate.py
test: test-lesson14
inspect-lesson14: build/lesson14/bootloader.elf build/lesson14/kernel.elf build/lesson14/user.elf build/lesson14/math_test.elf build/lesson14/math.elf build/lesson14/cc.elf
	$(READELF) -h -lW $(filter %.elf,$^)
	$(OBJDUMP) -d $(filter %.elf,$^)
inspect: inspect-lesson14

# Pure PIC module and fixed-address ordinary-file application are NOT linked
# into the kernel/shell. They enter runtime exclusively via filesystem reads.
INTEGER_DLL_FLAGS := $(filter-out -fno-pic,$(COMPILER_FLAGS)) -fPIC -fvisibility=hidden
build/lesson14/math_dll.o: lessons/14/math_dll.c | build/lesson14
	$(CC) $(INTEGER_DLL_FLAGS) -c -o $@ $<
build/lesson14/math_alt.o: lessons/14/math_dll.c | build/lesson14
	$(CC) $(INTEGER_DLL_FLAGS) -DALTERNATE -c -o $@ $<
build/lesson14/math.elf: build/lesson14/math_dll.o lessons/14/module.ld
	$(CC) $(INTEGER_DLL_FLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/14/module.ld -o $@ $<
build/lesson14/math-alt.elf: build/lesson14/math_alt.o lessons/14/module.ld
	$(CC) $(INTEGER_DLL_FLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/14/module.ld -o $@ $<
build/lesson14/math.dll: build/lesson14/math.elf lessons/14/pack.py
	$(OBJCOPY) -O binary --only-section=.text $< build/lesson14/math.text
	CROSS_COMPILE="$(CROSS_COMPILE)" $(PYTHON) lessons/14/pack.py module $< build/lesson14/math.text $@
build/lesson14/math-alt.dll: build/lesson14/math-alt.elf lessons/14/pack.py
	$(OBJCOPY) -O binary --only-section=.text $< build/lesson14/math-alt.text
	CROSS_COMPILE="$(CROSS_COMPILE)" $(PYTHON) lessons/14/pack.py module $< build/lesson14/math-alt.text $@
build/lesson14/math_test.elf: build/lesson14/app-start.o build/lesson14/math_test.o build/lesson14/module_loader.o build/lesson14/formats.o build/lesson14/syscall.o lessons/14/app.ld
	$(CC) $(COMPILER_FLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/14/app.ld -o $@ $(filter %.o,$^)
build/lesson14/math_test.exec: build/lesson14/math_test.elf lessons/14/pack.py
	$(OBJCOPY) -O binary $< build/lesson14/math_test.raw
	CROSS_COMPILE="$(CROSS_COMPILE)" $(PYTHON) lessons/14/pack.py executable $< build/lesson14/math_test.raw $@

.PHONY: test-lesson14-gdb test-lesson14-evidence
# No prerequisites: invalidate evidence BEFORE even a recursive build fails.
test-lesson14-gdb:
	@mkdir -p build/lesson14
	$(PYTHON) lessons/14/fresh-log.py build/lesson14/gdb-loader.log
	+$(MAKE) --no-print-directory lesson14
	QEMU="$(QEMU)" $(PYTHON) lessons/14/gdb-test.py
test-lesson14-evidence:
	$(PYTHON) lessons/14/evidence-test.py

build/lesson14/io_test.elf: build/lesson14/app-start.o build/lesson14/io_test.o build/lesson14/module_loader.o build/lesson14/formats.o build/lesson14/syscall.o lessons/14/app.ld
	$(CC) $(COMPILER_FLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/14/app.ld -o $@ $(filter %.o,$^)
build/lesson14/io_test.exec: build/lesson14/io_test.elf lessons/14/pack.py
	$(OBJCOPY) -O binary $< build/lesson14/io_test.raw
	CROSS_COMPILE="$(CROSS_COMPILE)" $(PYTHON) lessons/14/pack.py executable $< build/lesson14/io_test.raw $@


# ABI2 compiler: static buffers have a larger memory bound, not a larger file.
build/lesson14/integer-runtime.elf: build/lesson14/integer-runtime.o
	$(CC) $(COMPILER_FLAGS) -nostdlib -static -Wl,--build-id=none,-Ttext=0,-e,integer_runtime_begin -o $@ $<
build/lesson14/integer-runtime.h: build/lesson14/integer-runtime.elf lessons/14/runtime-pack.py
	$(OBJCOPY) -O binary --only-section=.text $< build/lesson14/integer-runtime.raw
	CROSS_COMPILE="$(CROSS_COMPILE)" $(PYTHON) lessons/14/runtime-pack.py $< build/lesson14/integer-runtime.raw $@
build/lesson14/cc.o: build/lesson14/integer-runtime.h
build/lesson14/cc.o: COMPILER_FLAGS += -fstack-usage
build/lesson14/cc.elf: build/lesson14/cc-start.o build/lesson14/cc.o build/lesson14/formats.o build/lesson14/syscall.o lessons/14/cc.ld
	$(CC) $(COMPILER_FLAGS) -nostdlib -static -Wl,--build-id=none,-Map,build/lesson14/cc.map -T lessons/14/cc.ld -o $@ $(filter %.o,$^)
build/lesson14/cc.exec: build/lesson14/cc.elf lessons/14/pack.py
	$(OBJCOPY) -O binary $< build/lesson14/cc.raw
	CROSS_COMPILE="$(CROSS_COMPILE)" $(PYTHON) lessons/14/pack.py compiler $< build/lesson14/cc.raw $@

.PHONY: resource-lesson14
inspect-lesson14: resource-lesson14
resource-lesson14: lesson14
	$(PYTHON) lessons/14/resource-test.py

SOFT_SOURCES := adddf3 subdf3 muldf3 divdf3 comparedf2 negdf2 fixdfdi fixunsdfdi floatdidf floatundidf floatsidf floatunsidf fixdfsi fixunsdfsi clzdi2 clzsi2 fp_mode
SOFT_OBJECTS := $(addprefix build/lesson15/soft-,$(addsuffix .o,$(SOFT_SOURCES)))

# Lesson15: bounded full-data redo journal over the B+ tree filesystem.
SOFT_COMPILER_FLAGS := $(LESSON02_CFLAGS) -O1 -fno-unwind-tables -fno-asynchronous-unwind-tables -Ilessons/02 -Ilessons/15 -Ibuild/lesson15
SOFT_COMPILER_COMMON := build/lesson15/start.o build/lesson15/runtime.o build/lesson15/trap.o build/lesson15/fs.o build/lesson15/journal.o build/lesson02/uart.o
build/lesson15:
	mkdir -p $@
build/lesson15/%.o: lessons/15/%.S | build/lesson15
	$(CC) $(SOFT_COMPILER_FLAGS) -c -o $@ $<
build/lesson15/%.o: lessons/15/%.c $(wildcard lessons/15/*.h) | build/lesson15
	$(CC) $(SOFT_COMPILER_FLAGS) -c -o $@ $<
build/lesson15/user.elf: build/lesson15/user-start.o build/lesson15/user.o build/lesson15/filetest.o build/lesson15/syscall.o lessons/15/user.ld
	$(CC) $(SOFT_COMPILER_FLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/15/user.ld -o $@ $(filter %.o,$^)
build/lesson15/user-symbols.h: build/lesson15/user.elf lessons/15/symbols.py
	$(PYTHON) lessons/15/symbols.py $(CROSS_COMPILE)nm $< $@
build/lesson15/kernel.o: build/lesson15/user-symbols.h
build/lesson15/kernel.elf: $(SOFT_COMPILER_COMMON) build/lesson15/block.o build/lesson15/kernel.o build/lesson15/formats.o build/lesson15/snapshot.o lessons/15/kernel.ld
	$(CC) $(SOFT_COMPILER_FLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/15/kernel.ld -o $@ $(filter %.o,$^)
build/lesson15/block-no-flush.o: lessons/15/block.c lessons/15/block.h | build/lesson15
	$(CC) $(SOFT_COMPILER_FLAGS) -DNO_FLUSH -c -o $@ $<
build/lesson15/kernel-no-flush.elf: $(SOFT_COMPILER_COMMON) build/lesson15/block-no-flush.o build/lesson15/kernel.o build/lesson15/formats.o build/lesson15/snapshot.o lessons/15/kernel.ld
	$(CC) $(SOFT_COMPILER_FLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/15/kernel.ld -o $@ $(filter %.o,$^)
build/lesson15/bootloader.elf: build/lesson15/boot.o build/lesson02/uart.o build/lesson03/bootloader.o build/lesson03/virtio_blk.o lessons/02/linker.ld
	$(CC) $(SOFT_COMPILER_FLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/02/linker.ld -o $@ $(filter %.o,$^)
build/lesson15/%.bin: build/lesson15/%.elf
	$(OBJCOPY) -O binary $< $@
	test "$$(stat -c %s $@)" -le 65536
build/lesson15/disk.img: build/lesson15/kernel.bin build/lesson15/user.bin build/lesson15/math_test.exec build/lesson15/math.dll build/lesson15/cc.exec lessons/15/seed.py lessons/15/native.py tools/make-disk-image.py lessons/15/format.py
	$(PYTHON) lessons/15/seed.py build/lesson15/kernel.bin build/lesson15/user.bin $@
build/lesson15/disk-no-flush.img: build/lesson15/kernel-no-flush.bin build/lesson15/user.bin tools/make-disk-image.py lessons/15/format.py
	$(PYTHON) lessons/15/format.py build/lesson15/kernel-no-flush.bin build/lesson15/user.bin $@
.PHONY: lesson15 run-lesson15 reset-lesson15 test-lesson15 inspect-lesson15
lesson15: build/lesson15/bootloader.elf build/lesson15/disk.img
all: lesson15
run-lesson15: lesson15
	QEMU="$(QEMU)" $(PYTHON) lessons/15/run.py $(LESSON15_ARGS)
reset-lesson15: lesson15
	$(PYTHON) lessons/15/run.py --reset $(LESSON15_ARGS)
# --reset is explicit destructive replacement, protected by the same host lock.
test-lesson15:
	QEMU="$(QEMU)" CC="$(CC)" $(PYTHON) lessons/15/gate.py
test: test-lesson15
inspect-lesson15: build/lesson15/bootloader.elf build/lesson15/kernel.elf build/lesson15/user.elf build/lesson15/math_test.elf build/lesson15/math.elf build/lesson15/cc.elf
	$(READELF) -h -lW $(filter %.elf,$^)
	$(OBJDUMP) -d $(filter %.elf,$^)
inspect: inspect-lesson15

# Pure PIC module and fixed-address ordinary-file application are NOT linked
# into the kernel/shell. They enter runtime exclusively via filesystem reads.
SOFT_DLL_FLAGS := $(filter-out -fno-pic,$(SOFT_COMPILER_FLAGS)) -fPIC -fvisibility=hidden
build/lesson15/math_dll.o: lessons/15/math_dll.c | build/lesson15
	$(CC) $(SOFT_DLL_FLAGS) -c -o $@ $<
build/lesson15/math_alt.o: lessons/15/math_dll.c | build/lesson15
	$(CC) $(SOFT_DLL_FLAGS) -DALTERNATE -c -o $@ $<
build/lesson15/math.elf: build/lesson15/math_dll.o lessons/15/module.ld
	$(CC) $(SOFT_DLL_FLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/15/module.ld -o $@ $<
build/lesson15/math-alt.elf: build/lesson15/math_alt.o lessons/15/module.ld
	$(CC) $(SOFT_DLL_FLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/15/module.ld -o $@ $<
build/lesson15/math.dll: build/lesson15/math.elf lessons/15/pack.py
	$(OBJCOPY) -O binary --only-section=.text $< build/lesson15/math.text
	CROSS_COMPILE="$(CROSS_COMPILE)" $(PYTHON) lessons/15/pack.py module $< build/lesson15/math.text $@
build/lesson15/math-alt.dll: build/lesson15/math-alt.elf lessons/15/pack.py
	$(OBJCOPY) -O binary --only-section=.text $< build/lesson15/math-alt.text
	CROSS_COMPILE="$(CROSS_COMPILE)" $(PYTHON) lessons/15/pack.py module $< build/lesson15/math-alt.text $@
build/lesson15/math_test.elf: build/lesson15/app-start.o build/lesson15/math_test.o build/lesson15/module_loader.o build/lesson15/formats.o build/lesson15/syscall.o lessons/15/app.ld
	$(CC) $(SOFT_COMPILER_FLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/15/app.ld -o $@ $(filter %.o,$^)
build/lesson15/math_test.exec: build/lesson15/math_test.elf lessons/15/pack.py
	$(OBJCOPY) -O binary $< build/lesson15/math_test.raw
	CROSS_COMPILE="$(CROSS_COMPILE)" $(PYTHON) lessons/15/pack.py executable $< build/lesson15/math_test.raw $@

.PHONY: test-lesson15-gdb test-lesson15-evidence
# No prerequisites: invalidate evidence BEFORE even a recursive build fails.
test-lesson15-gdb:
	@mkdir -p build/lesson15
	$(PYTHON) lessons/15/fresh-log.py build/lesson15/gdb-loader.log
	+$(MAKE) --no-print-directory lesson15
	QEMU="$(QEMU)" $(PYTHON) lessons/15/gdb-test.py
test-lesson15-evidence:
	$(PYTHON) lessons/15/evidence-test.py

build/lesson15/io_test.elf: build/lesson15/app-start.o build/lesson15/io_test.o build/lesson15/module_loader.o build/lesson15/formats.o build/lesson15/syscall.o lessons/15/app.ld
	$(CC) $(SOFT_COMPILER_FLAGS) -nostdlib -static -Wl,--build-id=none -T lessons/15/app.ld -o $@ $(filter %.o,$^)
build/lesson15/io_test.exec: build/lesson15/io_test.elf lessons/15/pack.py
	$(OBJCOPY) -O binary $< build/lesson15/io_test.raw
	CROSS_COMPILE="$(CROSS_COMPILE)" $(PYTHON) lessons/15/pack.py executable $< build/lesson15/io_test.raw $@


# ABI2 compiler: static buffers have a larger memory bound, not a larger file.
build/lesson15/integer-runtime.elf: build/lesson15/integer-runtime.o
	$(CC) $(SOFT_COMPILER_FLAGS) -nostdlib -static -Wl,--build-id=none,-Ttext=0,-e,integer_runtime_begin -o $@ $<
build/lesson15/integer-runtime.h: build/lesson15/integer-runtime.elf lessons/15/runtime-pack.py
	$(OBJCOPY) -O binary --only-section=.text $< build/lesson15/integer-runtime.raw
	CROSS_COMPILE="$(CROSS_COMPILE)" $(PYTHON) lessons/15/runtime-pack.py $< build/lesson15/integer-runtime.raw $@
build/lesson15/cc.o: build/lesson15/integer-runtime.h
build/lesson15/cc.o: SOFT_COMPILER_FLAGS += -fstack-usage
build/lesson15/cc.elf: build/lesson15/cc-start.o build/lesson15/cc.o build/lesson15/formats.o build/lesson15/syscall.o lessons/15/cc.ld $(SOFT_OBJECTS)
	$(CC) $(SOFT_COMPILER_FLAGS) -nostdlib -static -Wl,--build-id=none,-Map,build/lesson15/cc.map -T lessons/15/cc.ld -o $@ $(filter %.o,$^)
build/lesson15/cc.exec: build/lesson15/cc.elf lessons/15/pack.py
	$(OBJCOPY) -O binary $< build/lesson15/cc.raw
	CROSS_COMPILE="$(CROSS_COMPILE)" $(PYTHON) lessons/15/pack.py compiler $< build/lesson15/cc.raw $@

.PHONY: resource-lesson15
inspect-lesson15: resource-lesson15
resource-lesson15: lesson15
	$(PYTHON) lessons/15/resource-test.py

# Explicit upstream builtin closure: no system libc or LP64D libgcc.

SOFT_HEADERS := $(wildcard lessons/15/softfloat/*.h lessons/15/softfloat/*.inc)
build/lesson15/soft-%.o: lessons/15/softfloat/%.c $(SOFT_HEADERS) | build/lesson15
	$(CC) $(SOFT_COMPILER_FLAGS) -Os -nostdinc -isystem $(shell $(CC) -print-file-name=include) -D_LIBC_LIMITS_H_ -c -o $@ $<
build/lesson15/runtime15.elf: build/lesson15/runtime15.o build/lesson15/formats.o build/lesson15/module_loader.o build/lesson15/syscall.o $(SOFT_OBJECTS) lessons/15/runtime15.ld
	$(CC) $(SOFT_COMPILER_FLAGS) -nostdlib -static -Wl,--build-id=none,-Map,build/lesson15/runtime15.map -T lessons/15/runtime15.ld -o $@ $(filter %.o,$^)
build/lesson15/c_runtime: build/lesson15/runtime15.elf lessons/15/runtime15-pack.py
	$(OBJCOPY) -O binary $< build/lesson15/runtime15.raw
	CROSS_COMPILE="$(CROSS_COMPILE)" $(PYTHON) lessons/15/runtime15-pack.py $< build/lesson15/runtime15.raw $@
build/lesson15/disk.img: build/lesson15/c_runtime
