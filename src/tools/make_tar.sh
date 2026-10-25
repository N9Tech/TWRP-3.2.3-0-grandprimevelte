#!/bin/sh
# Convertit une image .img en .img.tar flashable par Odin (membre: recovery.img)
[ $# -ge 1 ] || { echo "usage: $0 <fichier.img> [sortie.tar]"; exit 2; }
IN="$1"; OUT="${2:-${IN%.img}.img.tar}"
TMP=$(mktemp -d) || exit 1
cp "$IN" "$TMP/recovery.img"
tar -H ustar --owner=0 --group=0 -C "$TMP" -cf "$OUT" recovery.img
rm -rf "$TMP"
echo "$OUT"; md5sum "$OUT"
