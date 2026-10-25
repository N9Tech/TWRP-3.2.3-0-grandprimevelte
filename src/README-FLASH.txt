TWRP 3.2.3-0 for Samsung Galaxy Grand Prime VE (SM-G531F / grandprimevelte)
================================================================================
Build 2026-10-25 (rev. 11) - tested on hardware, boots straight into TWRP.

Files
-----
  TWRP-3.2.3-0-G531F.img.tar   Odin package - flash with the AP slot
  TWRP-3.2.3-0-G531F.img       same image, raw, for heimdall / dd
  md5sums.txt                  checksums - verify before flashing

  image : 11 225 088 bytes
  md5 .tar : 25e145ae690388246aa280bc29a25a0f
  md5 .img : 86045043fd05ce9ac7f6a3e691aa9a6e

Flashing (Odin)
---------------
  1. BACK UP EFS FIRST (in TWRP: Backup > tick EFS > swipe). It holds your IMEI.
  2. Odin > AP > select TWRP-3.2.3-0-G531F.img.tar
     Untick [Auto Reboot] and [Re-Partition].
  3. Start, wait for PASS.
  4. Pull the battery (do not let it boot to Android), then hold
     Volume Up + Home + Power until the screen lights up.

  You should see the TWRP splash then the main menu, about 6 s in total.
  (Revisions up to 10 ran a white/green/red framebuffer self-test first. It is
  now disabled - /sbin/fbfix.conf has probe=0. Set probe=1 to get it back, or
  run "adb shell sh /sbin/fbfix_ctl.sh probe" at any time.)

Transferring files to the device
--------------------------------
  WORKING   adb push rom.zip /sdcard/       then Install > select the zip
            microSD card                    Install > Storage: Micro SDcard
            adb shell twrp install /sdcard/rom.zip
  WORKING   adb sideload rom.zip            (rev. 10 fixed the FUSE mount point)
  NOT WORKING  MTP (drag & drop in Windows)
            The stock PXA1908 kernel has no USB functionfs
            (CONFIG_USB_FUNCTIONFS is not set), which TWRP needs for MTP.
            This is a kernel limitation, not a bug in this image - use adb push.

If it hangs on the splash screen
--------------------------------
adb is available even then:
    adb pull /tmp/fb.txt          boot diagnostics (fb geometry, theme check, ASCII screen)
    adb pull /tmp/recovery.log    TWRP's own log
    adb pull /tmp/crash.txt       only if TWRP crashed - ARM registers + memory map
Post them in the XDA thread.

Quick settings (no rebuild needed)
----------------------------------
    /sbin/fbfix.conf     mode=1  framebuffer single-buffer shim
                         pan=1   force the display window with FBIOPAN_DISPLAY
                         probe=0 no colour self-test at boot (1 = white/green/red)
    adb shell sh /sbin/fbfix_ctl.sh info|shot|probe|dump|plain|hook|set

Reverting
---------
Flash your own stock recovery back, or restore the recovery backup taken in
TWRP (Backup > Recovery). Nothing else on the device is modified: kernel,
bootloader and every partition are untouched.

License / credits
-----------------
TWRP 3.2.3 userspace, theme and busybox: TeamWin Recovery Project (GPLv3).
Kernel + dt.img: unmodified stock files from this device (Samsung / Marvell).
Framebuffer shim, probes and tooling: MIT - full sources in the source kit.
