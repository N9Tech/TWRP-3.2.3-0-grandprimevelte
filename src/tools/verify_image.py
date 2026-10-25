#!/usr/bin/env python3
"""
verify_image.py - contrôle d'une image de recovery Marvell (G531F)
Sans appareil : ce script prouve la structure, l'identité de version et la
cohérence des dépendances.

  python3 verify_image.py <recovery.img> [--json]
"""
import contextlib
import io
import json
import os
import re
import stat
import struct
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import marvell_recovery  # noqa: E402
import ramdisk_tool     # noqa: E402
from make_hybrid import elf_needed  # noqa: E402

EXPECT_KERNEL_SIZE = 6294393
EXPECT_DT_SIZE = 129024
RECOVERY_PART_SIZE = 0x105C0000


def analyse(img):
    d = open(img, "rb").read()
    h = marvell_recovery._read_header(d)
    rep = {
        "fichier": os.path.basename(img),
        "taille_octets": len(d),
        "magic": d[:8].decode("latin1"),
        "header": h["layout"],
        "page_size": h["pagesize"],
        "kernel_size": h["ksize"],
        "kernel_addr": hex(h["kaddr"]),
        "ramdisk_size": h["rsize"],
        "ramdisk_addr": hex(h["raddr"]),
        "dt_size": h["dtsize"],
        "tient_dans_partition": len(d) <= RECOVERY_PART_SIZE,
        "problemes": [],
    }
    tmp = tempfile.mkdtemp()
    quiet = contextlib.redirect_stdout(io.StringIO())
    with quiet:
        marvell_recovery.unpack(img, tmp)
    rd = os.path.join(tmp, "ramdisk.gz")
    raw = open(rd, "rb").read()
    rep["ramdisk_compression"] = "gzip" if raw[:2] == b"\x1f\x8b" else "?"
    root = os.path.join(tmp, "root")
    with quiet:
        ramdisk_tool.extract(rd, root)

    sb = os.path.join(root, "sbin")
    binp = os.path.join(sb, "recovery")
    if not os.path.exists(binp):
        rep["problemes"].append("sbin/recovery absent")
        return rep
    b = open(binp, "rb").read()
    rep["recovery_taille"] = len(b)
    rep["twrp_version"] = sorted({v.decode() for v in re.findall(rb"3\.\d\.\d-\d", b)})
    need = elf_needed(binp)
    missing = [n for n in need if not os.path.exists(os.path.join(sb, n))]
    rep["libs_requises"] = len(need)
    rep["libs_manquantes"] = missing
    if missing:
        rep["problemes"].append("libs manquantes : %s" % missing)

    fs = os.path.join(root, "etc", "recovery.fstab")
    if os.path.exists(fs):
        fst = open(fs).read()
        rep["fstab_soc2"] = "/dev/block/platform/soc.2/by-name" in fst
        if not rep["fstab_soc2"]:
            rep["problemes"].append("fstab ne pointe pas vers soc.2")
    else:
        rep["fstab_soc2"] = False
        rep["problemes"].append("etc/recovery.fstab absent")

    # Le theme vit dans /sbin/theme.tar (zone precoce de l'archive : le noyau
    # de ce telephone n'extrait que ~13 Mo des 15 Mo du cpio, donc tout ce qui
    # se trouve en fin d'archive n'existe jamais sur l'appareil).
    tarpath = os.path.join(root, "sbin/theme.tar")
    if os.path.exists(tarpath):
        import tarfile as _tf
        with _tf.open(tarpath) as t:
            names = set(t.getnames())
        rep["theme_tar"] = len([n for n in names if not n.endswith("/")])
        for req in ("twres/ui.xml", "twres/portrait.xml", "twres/splash.xml",
                    "twres/languages/en.xml", "twres/fonts/RobotoCondensed-Regular.ttf",
                    "twres/fonts/DroidSansMono.ttf", "twres/images/splashlogo.png"):
            if req not in names:
                rep["problemes"].append("%s absent de sbin/theme.tar" % req)
        rep["theme_images"] = len([n for n in names if n.startswith("twres/images/") and not n.endswith("/")])
        if rep["theme_images"] != 57:
            rep["problemes"].append("theme.tar : %d images au lieu de 57" % rep["theme_images"])
    else:
        rep["theme_tar"] = 0
        for req in ("twres/ui.xml", "twres/portrait.xml"):
            if not os.path.exists(os.path.join(root, req)):
                rep["problemes"].append("%s absent" % req)

    for req in ("init", "init.rc", "sbin/adbd", "sbin/busybox"):
        if not os.path.exists(os.path.join(root, req)):
            rep["problemes"].append("%s absent" % req)

    if h["ksize"] != EXPECT_KERNEL_SIZE:
        rep["problemes"].append("kernel != noyau G531F d'origine (%d)" % h["ksize"])
    if h["dtsize"] != EXPECT_DT_SIZE:
        rep["problemes"].append("dt.img != dtb G531F d'origine (%d)" % h["dtsize"])
    rep["kernel_origine_g531f"] = h["ksize"] == EXPECT_KERNEL_SIZE
    rep["dtb_origine_g531f"] = h["dtsize"] == EXPECT_DT_SIZE
    return rep


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(2)
    rep = analyse(sys.argv[1])
    if "--json" in sys.argv:
        print(json.dumps(rep, indent=2, ensure_ascii=False))
        return
    for k, v in rep.items():
        print("%-22s : %s" % (k, v))


if __name__ == "__main__":
    main()
