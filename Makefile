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
