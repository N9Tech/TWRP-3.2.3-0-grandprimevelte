#!/bin/bash
# Reproduce TWRP-3.2.3-0-G531F.img from the published inputs.
# See README.md, section "How this image is built".
set -e
STOCK=${1:?usage: ./build.sh <stock G531F recovery.img> <TWRP 3.2.3 arm32 donor .img>}
DONOR=${2:?idem}
OUT=.
WORK=$(mktemp -d)
echo "== 1. build the injected binaries (arm-linux-gnueabihf-gcc required)"
make -C build
echo "== 2. graft the TWRP 3.2.3 userspace onto the stock G531F kernel + dtb"
python3 tools/make_hybrid.py --base "$STOCK" --donor "$DONOR" --outdir "$WORK"
# -> "$WORK/recovery_variantA.img" : ramdisk TWRP 3.2.3, kernel + dt.img G531F d'origine
echo "== 3. inject the framebuffer shim, the probes and the theme payload"
python3 tools/inject_fbfix.py --in "$WORK/recovery_variantA.img" --out "$OUT/recovery.img" \
        --so build/libfbfix.so --probe build/fbprobe --fb2txt build/fb2txt
echo "== 4. verify"
python3 tools/verify_image.py "$OUT/recovery.img"
echo "== 5. wrap for Odin (AP)"
bash tools/make_tar.sh "$OUT/recovery.img"
rm -rf "$WORK"
