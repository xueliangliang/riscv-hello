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

clean:
	rm -rf build
