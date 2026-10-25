# TWRP 3.2.3-0 for Samsung Galaxy Grand Prime VE (SM-G531F / `grandprimevelte`)

Marvell PXA1908 · 1 GB RAM · 540×960 · Android 5.1.1 · **rev. 11, tested on hardware**

Official TWRP never went past **2.8.7.1** for this device and the newest build that ever
booted was a 3.0.2. This produces a working **3.2.3-0** by grafting the TWRP 3.2.3 userspace
onto the *stock* G531F kernel, then fixing three device-specific bugs. They are documented
below because they will bite anyone porting TWRP to another PXA1908 / `mmp-fb` device.

---

## 1. Why a hybrid image

Marvell never released PXA1908 kernel sources, so the kernel cannot be rebuilt. The image
keeps the stock kernel and `dt.img` **byte for byte** and only replaces the ramdisk with a
TWRP 3.2.3 one (donor: an official 32-bit ARM 3.2.3 build).

```
[ 2048-byte Marvell "ANDROID!" header ]
[ kernel   6 294 393 B   @ 0x10008000 ]   <- stock G531F, untouched
[ ramdisk  ~4.8 MB gzip  @ 0x11000000 ]   <- TWRP 3.2.3 userspace
[ dt.img     129 024 B   @ 0x10f00000 ]   <- stock G531F, untouched
```

`verify_image.py` checks both hashes at build time. Partition is 16 MB, image is 11.2 MB.

## 2. Bug #1 — the triple-buffered framebuffer (`mmp-fb`)

Measured on the device (`/sys/class/graphics/fb0`):

```
xres 540  yres 960   xres_virtual 544  yres_virtual 2880   (= 3 frames)
line_length 2176 (544 * 4, 4 px of padding per line)
smem_len 6266880     bpp 32   R@0 G@8 B@16
```

minui's double-buffer test is `yres * line_length * 2 <= smem_len`
(`minuitwrp/graphics_fbdev.cpp`). 960·2176·2 = 4 177 920 ≤ 6 266 880 is true, so it enables
double buffering and flips with `yoffset = n * 960` inside a **triple** buffer. The driver
accepts the ioctl but keeps scanning frame 0 → frozen logo or grey band.

`libfbfix.so` (LD_PRELOAD) reports `smem_len = line_length * yres` — room for exactly one
frame — while keeping the real `line_length` (**never hardcode 2160**, this panel is 2176:
wrong stride gives a diagonal, corrupted picture). minui then takes its single-buffer path
and `memcpy`s into fb0 with the correct stride. `fbprobe` proved it by painting hardware
frames 0/1/2 white/green/blue and panning with `FBIOPAN_DISPLAY`.

## 3. Bug #2 — the kernel silently truncates the initramfs (the real blocker)

**The stock kernel unpacks only ~86 % of the cpio archive and reports no error.**
Measured with a boot-time listing: `/twres/fonts` contained one font, `/twres/images` zero
files. The archive is 15 034 368 bytes; unpacking stops at **13 021 016**, exactly after
`twres/fonts/DroidSansFallback.ttf`. Everything past that never exists at runtime:

| Missing on device | TWRP symptom |
|---|---|
| theme PNGs | grey band, no logo |
| fonts | `Failed to load truetype face /twres/fonts/RobotoCondensed-Regular.ttf: 1` |
| `languages/en.xml` and the other 21 languages | **SIGSEGV right after `Loading page main2`** — the log simply stops, because TWRP's stdio buffer dies with the crash |

**Fix:** the theme no longer sits at the end of the cpio. The whole `twres` tree ships as
`/sbin/theme.tar` (65 files, 645 120 B) — `/sbin` is at the *beginning* of the archive and is
always unpacked — and `/sbin/fbfix_run.sh` rebuilds `/twres` at every boot before exec'ing
recovery. Unused CJK fonts (4.4 MB) and 19 languages were dropped, bringing the ramdisk to
**4.80 MB** (cpio 9.40 MB), far below the 13 MB cliff.

`libfbfix.so` also installs SIGSEGV/BUS/ILL/FPE/ABRT handlers that write the ARM registers,
the fault address, 96 stack words and `/proc/self/maps` to `/tmp/crash.txt` — that is how the
missing `en.xml` was finally identified.

## 4. Bug #3 — adb sideload fails at the FUSE mount (fixed in rev. 10)

```
sideload-host file size 304481729 block size 65536
mount: No such file or directory
fuse_sideload umount failed: No such file or directory
adbd status 1
```

`fuse_sideload.cpp` does `mount("/dev/fuse", FUSE_SIDELOAD_HOST_MOUNTPOINT, "fuse", …)` with
`FUSE_SIDELOAD_HOST_MOUNTPOINT = "/sideload"`, then `perror("mount")`. `ENOENT` here means the
**mount point does not exist**. TWRP's own `etc/init.rc` has `mkdir /sideload`; the G531F 3.0.2
ramdisk this port is based on does not. The kernel is fine: `CONFIG_FUSE_FS=y` and
`/dev/fuse` opens without error.

**Fix:** `mkdir /sideload` added to `init.rc` (and `mkdir -p /sideload` in the boot script).

## 5. What does *not* work, and why

**MTP** (`E:[MTP] could not open MTP driver, errno: 2`) is impossible on this kernel:
`# CONFIG_USB_FUNCTIONFS is not set`, and TWRP's MTP needs functionfs (`/dev/usb-ffs/mtp`).
Use `adb push` instead — it works.

## 6. Kit layout

```
build/      fbfix.c  fbprobe.c  fb2txt.c  Makefile      (our code: MIT)
payload/    theme.tar  fbfix_run.sh  fbfix_ctl.sh  fbfix.conf  libfbfix.so
            <- exact files injected into /sbin of the shipped image
tools/      marvell_recovery.py  Marvell "ANDROID!" pack/unpack (round-trips byte-exact)
            ramdisk_tool.py      cpio newc extract/pack, no external deps
            make_hybrid.py       stock kernel+dtb + donor TWRP ramdisk
            inject_fbfix.py      payload injection, init.rc fixes, repack
            verify_image.py      structure / version / library dependency checks
            make_tar.sh          .img -> Odin AP .tar
docs/       VERIFICATION.txt, notes (FR)
build.sh    end-to-end reproduction
```

## 7. Build it yourself

```bash
sudo apt-get install gcc-arm-linux-gnueabihf python3
./build.sh <stock-G531F-recovery.img> <twrp-3.2.3-0-arm32-donor.img>
# -> recovery.img + recovery.img.tar (Odin AP)
```

## 8. Runtime debugging (kept in the image on purpose)

```bash
adb pull /tmp/fb.txt      # boot diagnostics: fb geometry, theme check, ASCII screen dump
adb pull /tmp/crash.txt   # only if TWRP ever crashes: registers + memory map
adb shell sh /sbin/fbfix_ctl.sh info|shot|probe|dump|plain|hook|set
```

`/sbin/fbfix.conf`: `mode=1` framebuffer shim, `pan=1`, `probe=0` (boots straight into TWRP;
`probe=1` runs a white/green/red framebuffer self-test first — handy when porting).
The self-test is also available at any time: `adb shell sh /sbin/fbfix_ctl.sh probe`.

## 9. Credits / licensing

* TWRP userspace, theme, busybox — **TeamWin Recovery Project**, GPLv3.
* Kernel and `dt.img` — Samsung / Marvell, unmodified stock files; no kernel source is
  redistributed because Marvell never published one.
* Everything in `build/`, `payload/*.sh|c`, `tools/` — **MIT** (see LICENSE).
* `mincrypt/sha.c`, `mkbootimg.c` — AOSP, Apache-2.0.
