# TWRP 3.2.3-0 for Samsung Galaxy Grand Prime VE (SM-G531F / `grandprimevelte`)

Marvell PXA1908 · 1 GB RAM · 540×960 · Android 5.1.1

Official TWRP never went past **2.8.7.1** for this device, and the 3.0.2 build floating around
XDA is the newest that ever booted. This project produces a working **3.2.3-0** by grafting the
TWRP 3.2.3 userspace onto the *stock* G531F kernel, and then fixes two hardware-specific bugs
that made every previous attempt fail. **Both bugs are documented below because they will bite
anyone porting TWRP to another Marvell PXA1908 / mmp-fb device.**

---

## 1. Why a hybrid image

Marvell never released the PXA1908 kernel sources, so the kernel cannot be rebuilt.
The image keeps, byte for byte, the kernel and `dt.img` from the stock G531F recovery
(`recovery.img` of the 3.0.2 build) and only replaces the ramdisk with a TWRP 3.2.3 one
taken from an official 32-bit ARM build (donor: `twrp-3.2.3-0-bacon`).

```
[ 2048-byte Marvell "ANDROID!" header ]
[ kernel   6 294 393 B   @ 0x10008000 ]   <- stock G531F, untouched
[ ramdisk  ~4.8 MB gzip  @ 0x11000000 ]   <- TWRP 3.2.3 userspace
[ dt.img     129 024 B   @ 0x10f00000 ]   <- stock G531F, untouched
```

`verify_image.py` checks both hashes at build time. Partition is 16 MB; the image is ~11 MB.

## 2. Bug #1 — the framebuffer triple buffer (`mmp-fb`)

Measured on the device (`/sys/class/graphics/fb0`):

```
xres 540  yres 960   xres_virtual 544  yres_virtual 2880   (= 3 frames)
line_length 2176 (544 * 4, 4 px of padding per line)
smem_len 6266880     bpp 32   R@0 G@8 B@16
```

minui's test for double buffering is `yres * line_length * 2 <= smem_len`
(see `minuitwrp/graphics_fbdev.cpp`). With 960·2176·2 = 4 177 920 ≤ 6 266 880 it enables
double buffering and "flips" with `yoffset = n * 960` inside a **triple** buffer. The PXA1908
driver accepts the ioctl but keeps scanning frame 0, so TWRP draws into frames nobody displays:
a frozen logo or a grey band.

`libfbfix.so` (LD_PRELOAD) reports `smem_len = line_length * yres` — i.e. room for exactly
one frame — while keeping the real `line_length` (2176, never guess 2160: that produces a
diagonal, corrupted image). minui then takes its single-buffer path: it draws into its own
buffer and `memcpy`s into fb0 with the correct stride. Verified with `fbprobe`, which paints
hardware frames 0/1/2 white/green/blue and pans with `FBIOPAN_DISPLAY`.

## 3. Bug #2 — the kernel silently truncates the initramfs (the real blocker)

This one cost days. **The stock kernel only unpacks ~86 % of the cpio archive and returns no
error.** Measured on the device with a boot-time listing:

```
/twres/fonts : DroidSansFallback.ttf only      /twres/images : 0 files
```

The archive is 15 034 368 bytes; the cut falls exactly after
`twres/fonts/DroidSansFallback.ttf`, at **13 021 016 bytes**. Everything after it — the 57 theme
PNGs, 4 of the 5 fonts, and **all of `twres/languages/` including `en.xml`** — never exists at
runtime. Symptoms, in the order they appeared during debugging:

| Missing on device | TWRP symptom |
|---|---|
| theme PNGs | grey band, no logo |
| fonts | `Failed to load truetype face /twres/fonts/RobotoCondensed-Regular.ttf: 1` |
| `languages/en.xml` | **SIGSEGV right after `Loading page main2`** (log stops, no error) |

The last one is the nasty detail: the log just stops, because TWRP's stdio buffer is lost with
the crash. `libfbfix.so` now installs SIGSEGV/SIGBUS/SIGILL/SIGFPE/SIGABRT handlers that dump
the ARM registers, the fault address, 96 stack words and `/proc/self/maps` to `/tmp/crash.txt`.

**Fix:** the theme no longer lives at the end of the cpio. The whole `twres` tree ships as
`/sbin/theme.tar` (65 files, 645 120 B) — `/sbin` is at the *beginning* of the archive, always
unpacked — and `/sbin/fbfix_run.sh` rebuilds `/twres` at every boot before exec'ing recovery:

```sh
mkdir -p /twres && tar xf /sbin/theme.tar -C /
```

Unused CJK fonts (4.4 MB) and 19 languages were dropped, which brings the ramdisk down to
**4.80 MB** (cpio 9.40 MB) — comfortably below the 13 021 016-byte cliff even if the kernel
limit is never fixed.

## 4. What is in this kit

```
build/      fbfix.c  fbprobe.c  fb2txt.c  Makefile     (all our code: MIT, see LICENSE)
payload/    theme.tar  fbfix_run.sh  fbfix_ctl.sh  fbfix.conf  libfbfix.so
            <- the exact files injected into /sbin of the shipped image
tools/      marvell_recovery.py   Marvell "ANDROID!" image pack/unpack
            ramdisk_tool.py       cpio newc extract/pack, no external deps
            make_hybrid.py        stock kernel+dtb  +  donor TWRP ramdisk
            inject_fbfix.py       injects the payload, rewrites init.rc
            verify_image.py       structure / version / library dependency checks
            make_tar.sh           .img -> Odin AP .tar
docs/       VERIFICATION.txt (controls run on the shipped build), notes (FR)
build.sh    end-to-end reproduction
```

## 5. Build it yourself

```bash
sudo apt-get install gcc-arm-linux-gnueabihf python3
./build.sh <stock-G531F-recovery.img> <twrp-3.2.3-0-arm32-donor.img>
# -> recovery.img + recovery.img.tar (Odin AP)
```

Inputs: the stock G531F recovery (from the 3.0.2 build) and any official 32-bit ARM
TWRP 3.2.3 image (e.g. `twrp-3.2.3-0-bacon.img` from archive.org). Nothing from Marvell
is redistributed here; only the stock kernel already present on the device.

## 6. Flashing

Odin → **AP** → untick *Auto Reboot* and *Re-Partition* → `PASS` → pull the battery →
**Vol+ + Home + Power**.

## 7. Runtime debugging (kept in the image on purpose)

```bash
adb pull /tmp/fb.txt          # boot diagnostics: fb geometry, theme check, ASCII screen dump
adb pull /tmp/crash.txt       # only if TWRP ever crashes: registers + memory map
adb shell sh /sbin/fbfix_ctl.sh info|shot|probe|dump|plain|hook|set
```

`/sbin/fbfix.conf` toggles everything: `mode=1` (framebuffer fix), `pan=1`, `probe=1`
(colour test at boot; set `probe=0` for a fast boot straight into TWRP).

## 8. Credits / licensing

* TWRP recovery userspace, theme and busybox: **TeamWin Recovery Project** (GPLv3) —
  <https://github.com/TeamWin/android_bootable_recovery>, official 3.2.3-0 builds from
  <https://archive.org/details/twrp-3.2.3-0-bacon>.
* Kernel and `dt.img`: Samsung / Marvell, taken unmodified from the stock G531F recovery.
  No kernel source is redistributed because none was ever published by Marvell.
* Everything in `build/`, `payload/*.sh|c`, `tools/`: written for this port, **MIT**.
* `mincrypt/sha.c` from AOSP (Apache-2.0).

The device tree used for the 3.0.2 reference build is TeamWin's
`android_device_samsung_grandprimevelte` (`android-5.1` branch).
