#!/usr/bin/env python3
"""
make_hybrid.py - construit un TWRP 3.2+ "hybride" pour Samsung Galaxy Grand
                 Prime VE SM-G531F (Marvell PXA1908) en greffant l'userspace
                 TWRP 3.2+ d'un donneur ARM 32 bits sur le KERNEL + DTB
                 D'ORIGINE du G531F (les seuls binaires Marvell disponibles).

Principe :
  * le noyau 3.14 et le dt.img proviennent TOUJOURS de l'image 3.0.2 du G531F
    (impossible de recompiler : Marvell n'a rien publié) ;
  * le ramdisk (userspace TWRP) est reconstruit selon 2 stratégies :
      A) base = ramdisk G531F 3.0.2 (plomberie appareil : init.rc, ueventd,
         fstab, busybox) + userspace 3.2.3 du donneur (recovery, linker, libs,
         twres)
      B) base = ramdisk du donneur 3.2.3 complet, avec fstab/identité appareil
         réinjectés

Usage :
  python3 make_hybrid.py --donor <twrp-3.2.3-xxx.img> \
                         --base  <twrp-3.0.2-0-grandprimevelte.img> \
                         --outdir <dossier>
"""
import argparse
import gzip
import os
import re
import shutil
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ramdisk_tool  # noqa: E402
import marvell_recovery  # noqa: E402

FSTAB = """\
# /etc/recovery.fstab - Samsung Galaxy Grand Prime VE SM-G531F (grandprimevelte)
# PXA1908 / partitions nommees sous /dev/block/platform/soc.2
/efs                    emmc    /dev/block/platform/soc.2/by-name/EFS      flags=backup=1;display="EFS"
/boot                   emmc    /dev/block/platform/soc.2/by-name/KERNEL
/recovery               emmc    /dev/block/platform/soc.2/by-name/RECOVERY
/cache                  ext4    /dev/block/platform/soc.2/by-name/CACHE
/system                 ext4    /dev/block/platform/soc.2/by-name/SYSTEM
/system_image           emmc    /dev/block/platform/soc.2/by-name/SYSTEM
/data                   ext4    /dev/block/platform/soc.2/by-name/USER
/preload                ext4    /dev/block/platform/soc.2/by-name/HIDDEN      flags=display="Preload"
/nvm                    ext4    /dev/block/platform/soc.2/by-name/NVM
/radio                  emmc    /dev/block/platform/soc.2/by-name/MODEM
/external_sd            vfat    /dev/block/mmcblk1p1   /dev/block/mmcblk1   flags=display="Micro SDcard";storage;wipeingui;removable
/usb-otg                vfat    /dev/block/sda1        /dev/block/sda       flags=display="USB-OTG";storage;wipeingui;removable
"""

IDENTITY = """\
ro.product.brand=samsung
ro.product.device=grandprimevelte
ro.product.model=SM-G531F
ro.product.name=omni_grandprimevelte
ro.build.product=grandprimevelte
ro.build.fingerprint=samsung/grandprimevelte/grandprimevelte:5.1.1/LMY47X/G531FXXU1APG2:user/release-keys
ro.board.platform=mrvl
ro.hardware=pxa1908
"""


def sh(cmd):
    subprocess.run(cmd, shell=True, check=True)


def unpack_img(img, dest):
    if os.path.isdir(dest):
        shutil.rmtree(dest)
    marvell_recovery.unpack(img, dest)
    return dest


def extract_rd(imgdir, rddir):
    if os.path.isdir(rddir):
        shutil.rmtree(rddir)
    ramdisk_tool.extract(os.path.join(imgdir, "ramdisk.gz"), rddir)


def copy_tree(src, dst):
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst, symlinks=True)


def patch_adbd_service(root):
    p = os.path.join(root, "init.rc")
    s = open(p).read()
    s2 = re.sub(r"service adbd /sbin/adbe( recovery)?\n",
                "service adbd /sbin/adbd --device_banner=recovery\n", s)
    if s2 != s:
        open(p, "w").write(s2)
        print("    init.rc : service adbd -> /sbin/adbd")
    return s2 != s


def patch_default_prop(root, banner):
    p = os.path.join(root, "default.prop")
    s = open(p).read()
    # supprime les identifiants du donneur
    s = re.sub(r"^ro\.product\.(brand|device|model|name)=.*$", "", s, flags=re.M)
    s = re.sub(r"^ro\.build\.(product|fingerprint)=.*$", "", s, flags=re.M)
    s = re.sub(r"^ro\.bootimage\.build\.fingerprint=.*$", "", s, flags=re.M)
    s = re.sub(r"^ro\.omni\.device=.*$", "", s, flags=re.M)
    s = "\n".join(l for l in s.splitlines() if l.strip() or True)
    s += "\n# --- injecte par make_hybrid.py : identite SM-G531F ---\n" + IDENTITY
    open(p, "w").write(s)


def variant_a(donor_rd, base_rd, out):
    """Base = ramdisk G531F 3.0.2, userspace 3.2.x du donneur."""
    print("  [A] base ramdisk G531F + userspace donneur")
    copy_tree(base_rd, out)

    # 1. virer l'ancien userspace de recovery (binaire + libs + linker)
    sb = os.path.join(out, "sbin")
    for f in os.listdir(sb):
        if f == "recovery" or f.startswith("lib") or f in ("linker", "ld.config.txt", "adbd"):
            os.remove(os.path.join(sb, f))

    # 2. copier le userspace du donneur
    dsb = os.path.join(donor_rd, "sbin")
    n = 0
    for f in os.listdir(dsb):
        src = os.path.join(dsb, f)
        if not os.path.isfile(src):
            continue
        if f == "recovery" or f.startswith("lib") or f in ("linker", "adbd", "ld.config.txt"):
            shutil.copy2(src, os.path.join(sb, f))
            n += 1
    print("    %d fichiers userspace (recovery/linker/libs) copiés" % n)

    # 3. thème TWRP 3.2
    if os.path.isdir(os.path.join(donor_rd, "twres")):
        copy_tree(os.path.join(donor_rd, "twres"), os.path.join(out, "twres"))
        print("    twres/ (thème 3.2) installé")
    # polices / images
    if os.path.isdir(os.path.join(donor_rd, "res")):
        copy_tree(os.path.join(donor_rd, "res"), os.path.join(out, "res"))

    # 4. fstab appareil (les deux noms, contenu identique)
    os.makedirs(os.path.join(out, "etc"), exist_ok=True)
    for name in ("recovery.fstab", "twrp.fstab"):
        open(os.path.join(out, "etc", name), "w").write(FSTAB)

    # 5. ld.config.txt vide (le linker 8.1 le cherche)
    open(os.path.join(sb, "ld.config.txt"), "w").write("")

    patch_adbd_service(out)
    patch_default_prop(out, "A")
    return out


def variant_b(donor_rd, base_rd, out):
    """Base = ramdisk du donneur 3.2.x, plomberie appareil réinjectée."""
    print("  [B] base ramdisk donneur + plomberie G531F")
    copy_tree(donor_rd, out)

    # 1. retirer tout ce qui est spécifique au donneur
    for f in ("init.recovery.bacon.rc", "ueventd.bacon.rc", "fstab.bacon"):
        p = os.path.join(out, f)
        if os.path.exists(p):
            os.remove(p)
    for f in os.listdir(out):
        m = re.match(r"init\.recovery\.(?!usb|service|logd|vold_decrypt)\w+\.rc$", f)
        if m:
            os.remove(os.path.join(out, f))
            print("    supprimé (spécifique donneur) : %s" % f)

    # 2. usb rc de l'appareil (VID/PID Samsung) plutôt que celui du donneur
    src = os.path.join(base_rd, "init.recovery.usb.rc")
    if os.path.exists(src):
        shutil.copy2(src, os.path.join(out, "init.recovery.usb.rc"))
        print("    init.recovery.usb.rc <- G531F")

    # 3. fstab appareil
    os.makedirs(os.path.join(out, "etc"), exist_ok=True)
    for name in ("recovery.fstab", "twrp.fstab"):
        open(os.path.join(out, "etc", name), "w").write(FSTAB)

    patch_default_prop(out, "B")
    return out


def elf_needed(path):
    """Liste les DT_NEEDED d'un ELF 32 bits ARM (lecture brute)."""
    d = open(path, "rb").read()
    if d[:4] != b"\x7fELF" or d[4] != 1:
        return []
    le = d[5] == 1
    e = "<" if le else ">"
    e_shoff = struct.unpack_from(e + "I", d, 0x20)[0]
    e_shentsize = struct.unpack_from(e + "H", d, 0x2E)[0]
    e_shnum = struct.unpack_from(e + "H", d, 0x30)[0]
    secs = []
    for i in range(e_shnum):
        off = e_shoff + i * e_shentsize
        sh_type = struct.unpack_from(e + "I", d, off + 4)[0]
        sh_offset, sh_size, sh_link = struct.unpack_from(e + "III", d, off + 16)
        secs.append((sh_type, sh_offset, sh_size, sh_link))
    dyn = next((s for s in secs if s[0] == 6), None)      # SHT_DYNAMIC
    if not dyn:
        return []
    strtab = secs[dyn[3]]
    out = []
    for off in range(dyn[1], dyn[1] + dyn[2], 8):
        tag, val = struct.unpack_from(e + "iI", d, off)
        if tag == 1:                                      # DT_NEEDED
            end = d.index(b"\0", strtab[1] + val)
            out.append(d[strtab[1] + val:end].decode())
    return out


def verify(root, label):
    sb = os.path.join(root, "sbin")
    binp = os.path.join(sb, "recovery")
    need = elf_needed(binp)
    missing = [n for n in need if not os.path.exists(os.path.join(sb, n))]
    have = sorted(os.listdir(sb))
    ver = set(re.findall(rb"3\.\d\.\d-\d", open(binp, "rb").read()))
    print("    %s : recovery=%d o  version=%s  DT_NEEDED=%d  manquantes=%s"
          % (label, os.path.getsize(binp),
             ", ".join(v.decode() for v in ver) or "?", len(need),
             missing or "aucune"))
    for req in ("etc/recovery.fstab", "twres/ui.xml", "twres/portrait.xml",
                "init", "init.rc", "sbin/adbd", "sbin/linker", "sbin/busybox"):
        p = os.path.join(root, req)
        if not os.path.exists(p):
            print("      ATTENTION : %s absent" % req)
    return missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--donor", required=True)
    ap.add_argument("--base", required=True)
    ap.add_argument("--outdir", required=True)
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)
    work = os.path.join(a.outdir, "work")
    os.makedirs(work, exist_ok=True)

    print("== extraction des images ==")
    donor_img = unpack_img(a.donor, os.path.join(work, "donor_img"))
    base_img = unpack_img(a.base, os.path.join(work, "base_img"))
    donor_rd = os.path.join(work, "donor_rd")
    base_rd = os.path.join(work, "base_rd")
    extract_rd(donor_img, donor_rd)
    extract_rd(base_img, base_rd)

    results = {}
    for name, fn in (("A", variant_a), ("B", variant_b)):
        print("== variante %s ==" % name)
        root = os.path.join(work, "root_%s" % name)
        fn(donor_rd, base_rd, root)
        missing = verify(root, name)
        rd = os.path.join(work, "ramdisk_%s.gz" % name)
        ramdisk_tool.pack(root, rd)
        # image finale : kernel + dt du G531F, ramdisk de la variante
        imgdir = os.path.join(work, "img_%s" % name)
        copy_tree(base_img, imgdir)
        shutil.copy2(rd, os.path.join(imgdir, "ramdisk.gz"))
        out_img = os.path.join(a.outdir, "recovery_variant%s.img" % name)
        marvell_recovery.pack(imgdir, out_img)
        results[name] = (out_img, missing)

    print("\n== controle final des images ==")
    for name, (img, missing) in results.items():
        chk = os.path.join(work, "check_%s" % name)
        marvell_recovery.unpack(img, chk)
        same = open(os.path.join(chk, "kernel"), "rb").read() == \
               open(os.path.join(base_img, "kernel"), "rb").read()
        dt_ok = open(os.path.join(chk, "dt.img"), "rb").read() == \
                open(os.path.join(base_img, "dt.img"), "rb").read()
        print("  %s : %s (%d o)  kernel identique=%s  dt.img identique=%s"
              % (name, img, os.path.getsize(img), same, dt_ok))


if __name__ == "__main__":
    main()
