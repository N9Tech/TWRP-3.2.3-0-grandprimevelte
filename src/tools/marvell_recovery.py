#!/usr/bin/env python3
"""
marvell_recovery.py - outil de (dé)conditionnement des images de recovery
Samsung / Marvell PXA1908 (Galaxy Grand Prime VE SM-G531F "grandprimevelte")

Format d'image de boot Marvell "helanx" (pxa1928dkb), pagesize 2048 :

  [ header 2048 o ] [ kernel ] [ pad 2048 ] [ ramdisk(.gz) ] [ pad 2048 ] [ dt.img ] [ pad ]

Ce script a été validé en reproduisant à l'identique OCTET POUR OCTET
l'image officieuse twrp-3.0.2-0-grandprimevelte.img (10 336 256 octets).

Aucune dépendance externe.

  python3 marvell_recovery.py unpack <recovery.img> <dossier_sortie>
  python3 marvell_recovery.py pack   <dossier_source> <recovery_out.img>
"""
import hashlib
import os
import struct
import sys

PAGE = 2048
HDR_FMT = "<8sIIIIIIIIII24s512s32s"       # layout actuel (tags avant unused)
HDR_FMT_OLD = "<8sIIIIIIIIII24s512s32s"   # idem mais tags_addr/page_size/dt_size
                                          # permutés (mkbootimg pre-2015)
BASE_DEFAULT = 0x10000000


def _align(n, p=PAGE):
    return (n + p - 1) // p * p


def _read_header(d):
    """Renvoie un dict. Gère la disposition moderne ET l'ancienne (pre-2015)."""
    u = lambda o: struct.unpack_from("<I", d, o)[0]
    modern = u(44)
    legacy = u(36)
    page = modern if modern in (1024, 2048, 4096, 8192, 16384, 32768, 65536, 131072) else legacy
    if page == legacy and modern not in (1024, 2048, 4096, 8192, 16384, 32768, 65536, 131072):
        return dict(layout="pre-2015", pagesize=u(36), tags=u(32), dtsize=u(40),
                    unused=u(44), ksize=u(8), kaddr=u(12), rsize=u(16),
                    raddr=u(20), ssize=u(24), saddr=u(28),
                    name=d[48:64], cmdline=d[64:576])
    return dict(layout="moderne", pagesize=u(44), tags=u(40), dtsize=u(32),
                unused=u(36), ksize=u(8), kaddr=u(12), rsize=u(16),
                raddr=u(20), ssize=u(24), saddr=u(28),
                name=d[48:72], cmdline=d[72:584])


def unpack(img_path, outdir):
    d = open(img_path, "rb").read()
    if d[:8] != b"ANDROID!":
        raise SystemExit("magic != ANDROID!")
    h = _read_header(d)
    magic, ksize, kaddr, rsize, raddr, ssize = (b"ANDROID!", h["ksize"], h["kaddr"],
                                                h["rsize"], h["raddr"], h["ssize"])
    dtsize, unused, tags, pagesize = h["dtsize"], h["unused"], h["tags"], h["pagesize"]
    name, cmdline = h["name"], h["cmdline"]
    if magic != b"ANDROID!":
        raise SystemExit("Ce n'est pas une image Android boot (magic != ANDROID!)")
    os.makedirs(outdir, exist_ok=True)
    off = PAGE
    kernel = d[off:off + ksize]
    off = _align(off + ksize, pagesize)
    ramdisk = d[off:off + rsize]
    off = _align(off + rsize, pagesize)
    second = d[off:off + ssize]
    off = _align(off + ssize, pagesize)
    dt = d[off:off + dtsize]
    off = _align(off + dtsize, pagesize)

    open(os.path.join(outdir, "kernel"), "wb").write(kernel)
    open(os.path.join(outdir, "ramdisk.gz"), "wb").write(ramdisk)
    if dt:
        open(os.path.join(outdir, "dt.img"), "wb").write(dt)
    if second:
        open(os.path.join(outdir, "second"), "wb").write(second)
    open(os.path.join(outdir, "cmdline.txt"), "w").write(
        cmdline.rstrip(b"\0").decode("utf-8", "replace"))
    open(os.path.join(outdir, "layout.txt"), "w").write(
        "kernel_size=%d\nkernel_addr=0x%08x\nramdisk_size=%d\n"
        "ramdisk_addr=0x%08x\nsecond_size=%d\ndt_size=%d\n"
        "tags_addr=0x%08x\npage_size=%d\nname=%s\ncmdline=%s\n"
        "tail_after_last_section=%d\n"
        % (ksize, kaddr, rsize, raddr, ssize, dtsize, tags, pagesize,
           name.rstrip(b"\0").decode("utf-8", "replace"),
           cmdline.rstrip(b"\0").decode("utf-8", "replace"),
           len(d) - off))

    print("Image      : %s (%d octets)" % (img_path, len(d)))
    print("kernel     : %7d octets  @ 0x%08x" % (ksize, kaddr))
    print("ramdisk    : %7d octets  @ 0x%08x" % (rsize, raddr))
    print("dt.img     : %7d octets" % dtsize)
    print("page_size  : %d   tags @ 0x%08x  unused=0x%08x  header=%s"
          % (pagesize, tags, unused, h["layout"]))
    print("cmdline    : %r" % cmdline.rstrip(b"\0").decode("utf-8", "replace"))
    print("-> fichiers extraits dans %s/" % outdir)


def pack(srcdir, out_path, page=PAGE, base=BASE_DEFAULT,
         kernel_offset=0x00008000, ramdisk_offset=0x01000000,
         second_offset=0x00F00000, tags_offset=0x00000100,
         unused=0x03000000):
    def load(fn):
        p = os.path.join(srcdir, fn)
        return open(p, "rb").read() if os.path.exists(p) else b""

    kernel = load("kernel")
    ramdisk = load("ramdisk.gz")
    dt = load("dt.img")
    second = load("second")
    cmdline = load("cmdline.txt").rstrip(b"\r\n")
    if not kernel or not ramdisk:
        raise SystemExit("kernel et ramdisk.gz sont obligatoires")
    if len(cmdline) > 511:
        raise SystemExit("cmdline trop longue")

    # id = SHA1(kernel + kernel_size + ramdisk + ramdisk_size + second + second_size [+ dt + dt_size])
    # (identique au champ "id" écrit par mkbootimg / marvell-mkbootimg)
    sha = hashlib.sha1()
    for blob in (kernel, ramdisk, second):
        sha.update(blob)
        sha.update(struct.pack("<I", len(blob)))
    if dt:
        sha.update(dt)
        sha.update(struct.pack("<I", len(dt)))
    img_id = sha.digest()

    hdr = struct.pack(
        HDR_FMT,
        b"ANDROID!", len(kernel), base + kernel_offset,
        len(ramdisk), base + ramdisk_offset,
        len(second), base + second_offset,
        len(dt), unused, base + tags_offset, page,
        b"", cmdline, img_id)

    out = bytearray()
    out += hdr + b"\0" * (page - len(hdr))
    for blob in (kernel, ramdisk, second, dt):
        if not blob:
            continue
        out += blob
        out += b"\0" * (_align(len(blob), page) - len(blob))
    open(out_path, "wb").write(out)
    print("Image créée : %s (%d octets)" % (out_path, len(out)))


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] not in ("unpack", "pack"):
        print(__doc__)
        raise SystemExit(2)
    if sys.argv[1] == "unpack":
        unpack(sys.argv[2], sys.argv[3])
    else:
        pack(sys.argv[2], sys.argv[3])
