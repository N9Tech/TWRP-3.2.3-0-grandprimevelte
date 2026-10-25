# Build the three injected binaries for TWRP 3.2.3 on SM-G531F (Marvell PXA1908).
#   sudo apt-get install gcc-arm-linux-gnueabihf
#   make
CC      := arm-linux-gnueabihf-gcc
ARCH    := -march=armv7-a -mfloat-abi=softfp -mfpu=vfpv3-d16
COMMON  := -O2 -ffreestanding -fno-builtin -nostdlib -nostartfiles -static
# No libc and no libgcc: there is no division in the code and every call is a
# raw syscall (svc 0). Required because these run inside the TWRP ramdisk.

all: libfbfix.so fbprobe fb2txt

# LD_PRELOAD shim: interposes ioctl() on /dev/graphics/fb0 (forces minui's
# single-buffer path) and installs SIGSEGV/SIGBUS/SIGILL/SIGFPE/SIGABRT
# handlers that dump the ARM registers + /proc/self/maps to /tmp/crash.txt.
libfbfix.so: fbfix.c
	$(CC) $(ARCH) -O2 -fPIC -shared -nostdlib -nostartfiles -ffreestanding \
	      -fno-builtin -o $@ $<

# fbprobe: paints the 3 hardware frames white/green/blue and pans between them
fbprobe: fbprobe.c
	$(CC) $(ARCH) $(COMMON) -o $@ $<

# fb2txt: renders the framebuffer as a coarse ASCII map into /tmp/shot.txt
fb2txt: fb2txt.c
	$(CC) $(ARCH) $(COMMON) -o $@ $<

clean:
	rm -f libfbfix.so fbprobe fb2txt
.PHONY: all clean
