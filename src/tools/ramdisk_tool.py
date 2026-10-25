#!/usr/bin/env python3
"""
ramdisk_tool.py - extraction / reconstruction de ramdisk Android (cpio newc)
Sans dépendance externe (gzip via zlib, lz4 non géré).

  python3 ramdisk_tool.py extract <ramdisk.(gz|cpio)> <dossier>
  python3 ramdisk_tool.py pack    <dossier> <ramdisk_out.gz> [--gzip-level N]

Gère : dossiers, fichiers, liens symboliques, liens durs, permissions,
propriétaires forcés à root:root (0:0) comme dans un ramdisk Samsung.
"""
import gzip
import os
import stat
import struct
import sys

MAGIC = b"070701"


def _entries(buf):
    off = 0
    while True:
        if buf[off:off + 6] != MAGIC:
            break
        f = lambda i: int(buf[off + 6 + i * 8: off + 6 + (i + 1) * 8], 16)
        ino, mode, uid, gid, nlink, mtime, fsize = (f(0), f(1), f(2), f(3),
                                                   f(4), f(5), f(6))
        devmaj, devmin, rmaj, rmin = f(7), f(8), f(9), f(10)
        namesize, chk = f(11), f(12)
        name = buf[off + 110: off + 110 + namesize - 1].decode("utf-8", "replace")
        pad = (4 - ((110 + namesize) % 4)) % 4
        dstart = off + 110 + namesize + pad
        data = buf[dstart:dstart + fsize]
        yield dict(name=name, mode=mode, uid=uid, gid=gid, nlink=nlink,
                   mtime=mtime, devmaj=devmaj, devmin=devmin, rmaj=rmaj,
                   rmin=rmin, ino=ino, data=data)
        off = dstart + fsize
        off = (4 - (off % 4)) % 4 + off
        if name == "TRAILER!!!":
            break


def extract(src, outdir):
    raw = open(src, "rb").read()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    elif raw[:4] == b"\x02\x21\x4c\x18" or raw[:4] == b"\x04\x22\x4d\x18":
        raise SystemExit("ramdisk LZ4 : installe python-lz4 ou convertis-le d'abord "
                         "(lz4 -d)")
    if raw[:6] != MAGIC:
        raise SystemExit("ce n'est pas un cpio newc (magic %r)" % raw[:6])
    os.makedirs(outdir, exist_ok=True)
    n = 0
    for e in _entries(raw):
        name = e["name"]
        if name == "TRAILER!!!":
            break
        rel = name.lstrip("./")
        if not rel:
            continue
        dest = os.path.join(outdir, rel)
        fmt = stat.S_IFMT(e["mode"])
        if fmt == stat.S_IFDIR:
            os.makedirs(dest, exist_ok=True)
        elif fmt == stat.S_IFLNK:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            if os.path.lexists(dest):
                os.remove(dest)
            os.symlink(e["data"].decode(), dest)
            n += 1
            continue
        elif fmt == stat.S_IFCHR or fmt == stat.S_IFBLK:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            continue          # périphériques : recréés par ueventd, ignorés
        else:
            os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
            open(dest, "wb").write(e["data"])
            n += 1
        os.chmod(dest, stat.S_IMODE(e["mode"]) | stat.S_IRWXU)
    print("extrait : %d fichiers -> %s/" % (n, outdir))


def _rec(path, base):
    for root, dirs, files in os.walk(path):
        dirs.sort()
        rel_root = os.path.relpath(root, base)
        if rel_root == ".":
            rel_root = ""
        for d in list(dirs):
            p = os.path.join(root, d)
            if os.path.islink(p):
                files.append(d)
                dirs.remove(d)
        for f in sorted(files):
            p = os.path.join(root, f)
            rel = os.path.join(rel_root, f) if rel_root else f
            st = os.lstat(p)
            if stat.S_ISLNK(st.st_mode):
                yield rel, 0o120777, os.readlink(p).encode(), st
            elif stat.S_ISREG(st.st_mode):
                yield rel, (st.st_mode & 0o7777) | stat.S_IFREG, open(p, "rb").read(), st
        for d in sorted(dirs):
            p = os.path.join(root, d)
            rel = os.path.join(rel_root, d) if rel_root else d
            yield rel + "/", 0o040755 | stat.S_IFDIR, b"", os.lstat(p)


def _hdr(name, mode, size, ino, nlink=1, mtime=0):
    n = name.encode() + b"\0"
    h = MAGIC + b"".join(
        b"%08X" % v for v in (ino, mode, 0, 0, nlink, mtime, size, 0, 0, 0, 0,
                              len(n), 0))
    out = h + n
    out += b"\0" * ((4 - (len(out) % 4)) % 4)
    return out


def pack(srcdir, outpath, level=9):
    ino = 300000
    buf = bytearray()
    base = os.path.abspath(srcdir)
    for rel, mode, data, st in _rec(base, base):
        ino += 1
        buf += _hdr(rel, mode, len(data), ino, mtime=int(st.st_mtime))
        buf += data
        buf += b"\0" * ((4 - (len(data) % 4)) % 4)
    buf += _hdr("TRAILER!!!", 0, 0, ino + 1)
    buf += b"\0" * ((512 - (len(buf) % 512)) % 512)
    with gzip.GzipFile(filename="", mode="wb", fileobj=open(outpath, "wb"),
                       mtime=0, compresslevel=level) as g:
        g.write(bytes(buf))
    print("créé : %s (%d octets, %d octets de cpio)"
          % (outpath, os.path.getsize(outpath), len(buf)))


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print(__doc__)
        raise SystemExit(2)
    if sys.argv[1] == "extract":
        extract(sys.argv[2], sys.argv[3])
    elif sys.argv[1] == "pack":
        lvl = 9
        if "--gzip-level" in sys.argv:
            lvl = int(sys.argv[sys.argv.index("--gzip-level") + 1])
        pack(sys.argv[2], sys.argv[3], lvl)
    else:
        print(__doc__)
        raise SystemExit(2)
