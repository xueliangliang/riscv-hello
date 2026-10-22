CROSS_COMPILE ?= riscv64-linux-gnu-
CC := $(CROSS_COMPILE)gcc
OBJCOPY := $(CROSS_COMPILE)objcopy
READELF := $(CROSS_COMPILE)readelf
OBJDUMP := $(CROSS_COMPILE)objdump
QEMU ?= qemu-system-riscv64

MARCH := rv64imac_zicsr_zifencei
MABI := lp64
CFLAGS := -march=$(MARCH) -mabi=$(MABI) -mcmodel=medany -g -ffreestanding -fno-builtin -fno-pic -fno-stack-protector -Wall -Wextra
LESSON02_CFLAGS := $(CFLAGS) -msmall-data-limit=0

.PHONY: all clean tools inspect test test-lesson01 test-lesson02 lesson02
all: build/lesson01.elf build/lesson01.bin build/lesson02.elf build/lesson02.bin

build:
	mkdir -p $@

build/lesson02:
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

tools:
	@$(CC) --version | sed -n '1p'
	@$(READELF) --version | sed -n '1p'
	@$(QEMU) --version | sed -n '1p'

inspect: build/lesson01.elf build/lesson01.bin build/lesson02.elf build/lesson02.bin
	$(READELF) -h -lW build/lesson01.elf
	$(OBJDUMP) -d build/lesson01.elf
	$(READELF) -h -lW build/lesson02.elf
	$(OBJDUMP) -d build/lesson02.elf
	@printf '\nLesson 01 ELF bytes: '; stat -c %s build/lesson01.elf
	@printf 'Lesson 01 raw binary bytes: '; stat -c %s build/lesson01.bin
	@printf 'Lesson 02 ELF bytes: '; stat -c %s build/lesson02.elf
	@printf 'Lesson 02 raw binary bytes: '; stat -c %s build/lesson02.bin

test-lesson01: build/lesson01.elf
	QEMU="$(QEMU)" READELF="$(READELF)" ./tests/run-qemu.sh build/lesson01.elf

test-lesson02: build/lesson02.elf
	QEMU="$(QEMU)" READELF="$(READELF)" ./tests/run-qemu.sh build/lesson02.elf "Lesson 02: C main entered with a valid stack." "PASS: C runtime, stack, BSS, initialized data, and UART verified."

test: test-lesson01 test-lesson02

clean:
	rm -rf build
