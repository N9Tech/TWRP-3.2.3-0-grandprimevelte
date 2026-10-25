#!/bin/bash
# Reproduce TWRP-3.2.3-0-G531F.img (rev. 10) from the published inputs.
set -e
STOCK=${1:?usage: ./build.sh <stock G531F recovery.img> <TWRP 3.2.3 arm32 donor .img>}
DONOR=${2:?same}
WORK=$(mktemp -d)

echo "== 1. build the injected binaries (needs gcc-arm-linux-gnueabihf)"
make -C build

echo "== 2. graft the TWRP 3.2.3 userspace onto the stock G531F kernel + dtb"
python3 tools/make_hybrid.py --base "$STOCK" --donor "$DONOR" --outdir "$WORK"
# -> "$WORK/recovery_variantA.img"

echo "== 3. inject the payload (shim, probes, theme.tar, init.rc fixes)"
python3 tools/inject_fbfix.py --in "$WORK/recovery_variantA.img" --out recovery.img \
        --so build/libfbfix.so --probe build/fbprobe --fb2txt build/fb2txt \
        --theme-tar payload/theme.tar

echo "== 4. verify"
python3 tools/verify_image.py recovery.img

echo "== 5. wrap for Odin (AP)"
bash tools/make_tar.sh recovery.img
rm -rf "$WORK"
