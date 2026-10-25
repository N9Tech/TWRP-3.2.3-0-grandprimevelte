# Build the three injected binaries for TWRP 3.2.3 on SM-G531F (Marvell PXA1908).
#   sudo apt-get install gcc-arm-linux-gnueabihf
#   make
CC      := arm-linux-gnueabihf-gcc
ARCH    := -march=armv7-a -mfloat-abi=softfp -mfpu=vfpv3-d16
COMMON  := -O2 -ffreestanding -fno-builtin -nostdlib -nostartfiles -static
# NOTE: no libc, no libgcc: the code contains no division and no libc calls,
#       everything goes through raw syscalls (svc 0). This is required because
#       these binaries run inside the TWRP ramdisk where bionic is minimal.

all: libfbfix.so fbprobe fb2txt

# LD_PRELOAD shim: interposes ioctl() on /dev/graphics/fb0 AND installs
# SIGSEGV/SIGBUS/SIGILL/SIGFPE/SIGABRT handlers that dump registers + maps.
libfbfix.so: fbfix.c
	$(CC) $(ARCH) -O2 -fPIC -shared -nostdlib -nostartfiles -ffreestanding \
	      -fno-builtin -o $@ $<

# fbprobe: paints the 3 hardware buffers and pans between them, logs to /tmp/probe.log
fbprobe: fbprobe.c
	$(CC) $(ARCH) $(COMMON) -o $@ $<

# fb2txt: renders the framebuffer as a coarse ASCII map in /tmp/shot.txt
fb2txt: fb2txt.c
	$(CC) $(ARCH) $(COMMON) -o $@ $<

clean:
	rm -f libfbfix.so fbprobe fb2txt
.PHONY: all clean
