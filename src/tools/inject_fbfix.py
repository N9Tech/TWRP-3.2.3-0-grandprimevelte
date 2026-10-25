#!/usr/bin/env python3
"""
inject_fbfix.py - injecte le correctif framebuffer + les sondes dans une image
                  recovery hybride TWRP 3.2.3 pour SM-G531F.

Géométrie réelle du mmp-fb (mesurée sur l'appareil) :
    xres 540  yres 960  xres_virtual 544  yres_virtual 2880 (triple buffer)
    line_length 2176 (544x4)  smem_len 6266880  bpp 32

Ajoute au ramdisk :
  sbin/libfbfix.so          interposeur ioctl (simple buffer, line_length réel)
  sbin/fbfix.conf           réglages : mode, pan, probe
  sbin/fbfix_run.sh         wrapper : sonde -> TWRP -> captures -> code de sortie
  sbin/fbfix_ctl.sh         outils à chaud (info/dump/shot/probe/plain/hook/set)
  sbin/fbprobe              sonde couleurs (blanc/vert/bleu)
  sbin/fb2txt               capture d'écran en texte (/tmp/shot.txt)
  init.recovery.pxa1908.rc  vide (supprime un message d'erreur d'init)

Usage :
  python3 inject_fbfix.py --in <src.img> --out <dst.img> --so <libfbfix.so>
                          [--probe <fbprobe>] [--fb2txt <fb2txt>] [--diag]
"""
import argparse
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import marvell_recovery  # noqa: E402
import ramdisk_tool     # noqa: E402

CONF = """\
# /sbin/fbfix.conf - correctif framebuffer PXA1908 / mmp-fb
# Relu à chaque démarrage. Modifiable depuis adb puis : adb shell reboot
#
# mode=1 : smem_len ramené à UNE image (line_length réel 2176 conservé)
#          -> minui (TWRP 3.2) abandonne son double buffer et copie vers fb0.
# mode=0 : aucune modification.
# pan=1  : après FBIOPUT_VSCREENINFO, force la fenêtre via FBIOPAN_DISPLAY.
# probe=0 : demarrage direct dans TWRP (aucune mire).
# probe=1 : sonde couleurs (blanc/vert/bleu) au demarrage, pour diagnostiquer.
mode=__MODE__
pan=1
probe=0
"""

RUNNER = """#!/sbin/busybox sh
# fbfix_run.sh - v8 : sonde -> theme -> TWRP -> capture de crash / blocage
LOG=/tmp/fb.txt
FB=/sys/class/graphics/fb0
: > $LOG
exec >>$LOG 2>&1

echo "==== fbfix_run $(date) ===="
echo "--- /proc/fb ---"; cat /proc/fb 2>&1
for f in name virtual_size stride bits_per_pixel blank; do
    echo "$f = $(cat $FB/$f 2>/dev/null)"
done
echo "--- conf ---"; grep -v '^#' /sbin/fbfix.conf

echo "--- theme : creation de /twres depuis /sbin/theme.tar ---"
echo "avant : $(ls /twres 2>/dev/null | wc -l) entrees dans /twres"
mkdir -p /twres
tar xf /sbin/theme.tar -C / ; echo "tar rc=$?"
echo "apres : $(ls /twres | wc -l) entrees dans /twres, $(ls /twres/images 2>/dev/null | wc -l) images, $(ls /twres/fonts 2>/dev/null | wc -l) polices"
for f in ui.xml splash.xml portrait.xml languages/en.xml fonts/RobotoCondensed-Regular.ttf images/splashlogo.png; do
    echo "  $f : $(wc -c < /twres/$f 2>&1) octets"
done

if [ "$(grep -c '^probe=0' /sbin/fbfix.conf)" != "1" ]; then
    [ -x /sbin/fbprobe ] && /sbin/fbprobe
fi
echo "--- probe.log ---"; cat /tmp/probe.log 2>/dev/null

# --- etat d'un processus, sans se laisser tromper par les zombies ---
etat() {
    S=$(sed 's/.*) //' /proc/$1/stat 2>/dev/null | cut -c1-2)
    [ -z "$S" ] && S="absent"
    echo "$S"
}

# point de montage FUSE d'adb sideload (ceinture et bretelles)
mkdir -p /sideload 2>/dev/null
chmod 0777 /sideload 2>/dev/null
echo "sideload : $(ls -ld /sideload 2>&1)"

export LD_PRELOAD=/sbin/libfbfix.so
/sbin/recovery &
RPID=$!
sleep 12

echo "--- capture a 12 s ---"
[ -x /sbin/fb2txt ] && /sbin/fb2txt; cat /tmp/shot.txt 2>/dev/null; rm -f /tmp/shot.txt
dd if=/dev/graphics/fb0 of=/tmp/screen12.raw bs=2176 count=960 2>/dev/null

ST=$(etat $RPID)
echo "recovery a 12 s : etat=$ST (S/R=fonctionne, Z=tue, absent=mort, T=arrete)"

if [ "$ST" = "S" ] || [ "$ST" = "R" ]; then
    echo "--- fils d'execution de TWRP ---"
    for t in /proc/$RPID/task/*; do
        echo "tid ${t##*/} : $(sed 's/.*) //' $t/stat 2>/dev/null | cut -d' ' -f1-3) wchan=$(cat $t/wchan 2>/dev/null)"
    done
    echo "--- memoire ---"; grep -E "^(MemTotal|MemFree|MemAvailable):" /proc/meminfo
    echo "--- maps de TWRP (extrait) ---"; grep -E "r-xp" /proc/$RPID/maps | head -20
    echo "--- sommeil 13 s de plus ---"
    sleep 13
    echo "--- capture a 25 s ---"
    [ -x /sbin/fb2txt ] && /sbin/fb2txt; cat /tmp/shot.txt 2>/dev/null; rm -f /tmp/shot.txt
    ST2=$(etat $RPID)
    echo "recovery a 25 s : etat=$ST2"
    if [ "$ST2" = "S" ] || [ "$ST2" = "R" ]; then
        echo "=> TWRP TOURNE TOUJOURS (pas de crash) : probleme de rendu, pas de binaire"
    fi
    wait $RPID; RC=$?
    echo "TWRP termine, code=$RC (139=SEGV 134=ABRT 137=KILL)"
    [ -x /sbin/fb2txt ] && /sbin/fb2txt; cat /tmp/shot.txt 2>/dev/null
else
    wait $RPID; RC=$?
    echo "TWRP MORT, code=$RC (139=SEGV 134=ABRT 137=KILL)"
    [ -x /sbin/fb2txt ] && /sbin/fb2txt; cat /tmp/shot.txt 2>/dev/null
    echo "=== /tmp/crash.txt ==="; cat /tmp/crash.txt 2>&1
    echo "=== dmesg (fin) ==="; dmesg 2>/dev/null | tail -20
    echo "relance SANS le correctif"
    unset LD_PRELOAD
    /sbin/recovery &
    RPID=$!; sleep 10
    echo "relance : etat=$(etat $RPID)"
fi
echo "==== fin fbfix_run ===="
"""

RUNNER_DIAG = """#!/sbin/busybox sh
# diag_run.sh - aucune modification d'affichage : journal puis TWRP.
LOG=/tmp/fb.txt
FB=/sys/class/graphics/fb0
: > $LOG
{
  echo "==== diag_run $(date) ===="
  echo "--- /proc/fb ---"; cat /proc/fb 2>&1
  for f in name virtual_size stride bits_per_pixel blank modes; do
      echo "$f = $(cat $FB/$f 2>/dev/null)"
  done
  echo "--- /proc/cmdline ---"; cat /proc/cmdline 2>&1
} >> $LOG 2>&1
exec /sbin/recovery
"""

CTL = """#!/sbin/busybox sh
# fbfix_ctl.sh - diagnostic à chaud depuis adb (root) :
#   adb shell sh /sbin/fbfix_ctl.sh info    état, géométrie, processus
#   adb shell sh /sbin/fbfix_ctl.sh shot    capture d'écran en TEXTE (/tmp/shot.txt)
#   adb shell sh /sbin/fbfix_ctl.sh probe   relance la sonde couleurs
#   adb shell sh /sbin/fbfix_ctl.sh dump    enregistre /tmp/screen.raw
#   adb shell sh /sbin/fbfix_ctl.sh plain   relance TWRP SANS correctif
#   adb shell sh /sbin/fbfix_ctl.sh hook    relance TWRP AVEC correctif
#   adb shell sh /sbin/fbfix_ctl.sh set mode=0    ajoute un réglage
CMD="$1"; shift
FB=/sys/class/graphics/fb0
case "$CMD" in
  info)
    echo "--- /proc/fb"; cat /proc/fb 2>/dev/null
    for f in name virtual_size stride bits_per_pixel blank; do
        echo "$f = $(cat $FB/$f 2>/dev/null)"
    done
    echo "--- conf"; grep -v '^#' /sbin/fbfix.conf
    echo "--- processus"; ps | grep -E 'recovery|adbd' | grep -v grep
    ;;
  shot)  [ -x /sbin/fb2txt ] && /sbin/fb2txt || echo "fb2txt absent" ;;
  probe) [ -x /sbin/fbprobe ] && /sbin/fbprobe && cat /tmp/probe.log || echo "fbprobe absent" ;;
  dump)
    dd if=/dev/graphics/fb0 of=/tmp/screen.raw bs=2176 count=960 2>/dev/null
    echo "/tmp/screen.raw = $(ls -l /tmp/screen.raw | awk '{print $5}') octets"
    ;;
  set)   echo "$*" >> /sbin/fbfix.conf; echo "conf : $* (au prochain demarrage)" ;;
  plain) pkill -f sbin/recovery 2>/dev/null; sleep 1
         echo "TWRP SANS correctif"; exec /sbin/recovery ;;
  hook)  pkill -f sbin/recovery 2>/dev/null; sleep 1
         echo "TWRP AVEC correctif (/tmp/fbfix.log)"
         LD_PRELOAD=/sbin/libfbfix.so exec /sbin/recovery ;;
  *)     sed -n '2,10p' /sbin/fbfix_ctl.sh ;;
esac
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", dest="out", required=True)
    ap.add_argument("--so", required=True)
    ap.add_argument("--probe", help="binaire fbprobe (sonde couleurs)")
    ap.add_argument("--fb2txt", help="binaire fb2txt (capture d'écran en texte)")
    ap.add_argument("--theme-tar", help="archive tar des ressources du thème (réparation)")
    ap.add_argument("--diag", action="store_true",
                    help="aucune modification d'affichage, journal seul")
    a = ap.parse_args()

    tmp = tempfile.mkdtemp()
    img = os.path.join(tmp, "img")
    marvell_recovery.unpack(a.inp, img)
    root = os.path.join(tmp, "root")
    ramdisk_tool.extract(os.path.join(img, "ramdisk.gz"), root)
    sb = os.path.join(root, "sbin")

    shutil.copy2(a.so, os.path.join(sb, "libfbfix.so"))
    os.chmod(os.path.join(sb, "libfbfix.so"), 0o644)

    if a.theme_tar:
        shutil.copy2(a.theme_tar, os.path.join(sb, "theme.tar"))
        os.chmod(os.path.join(sb, "theme.tar"), 0o644)
    for src, name in ((a.probe, "fbprobe"), (a.fb2txt, "fb2txt")):
        if src:
            shutil.copy2(src, os.path.join(sb, name))
            os.chmod(os.path.join(sb, name), 0o755)

    open(os.path.join(sb, "fbfix.conf"), "w").write(
        CONF.replace("__MODE__", "0" if a.diag else "1"))

    runner, rname = ((RUNNER_DIAG, "diag_run.sh") if a.diag
                     else (RUNNER, "fbfix_run.sh"))
    for name, body in ((rname, runner), ("fbfix_ctl.sh", CTL)):
        p = os.path.join(sb, name)
        open(p, "w").write(body)
        os.chmod(p, 0o750)

    open(os.path.join(root, "init.recovery.pxa1908.rc"), "w").write("# vide\n")

    irc = os.path.join(root, "init.rc")
    s = open(irc).read()
    replaced = False
    for line in s.splitlines():
        if line.startswith("service recovery "):
            s = s.replace(line, "service recovery /sbin/busybox sh /sbin/%s" % rname)
            replaced = True
            break
    if not replaced:
        raise SystemExit("init.rc : 'service recovery' introuvable")
    # adb sideload : libminadbd fait mount("/dev/fuse", "/sideload", "fuse", ...)
    # -> sans ce dossier le montage echoue en ENOENT et le sideload plante.
    # Le etc/init.rc officiel de TWRP contient bien "mkdir /sideload" ; celui du
    # ramdisk G531F 3.0.2 non, d'ou l'ajout.
    if "mkdir /sideload" not in s:
        s = s.replace("    mkdir /tmp\n", "    mkdir /tmp\n    mkdir /sideload\n", 1)
        print("init.rc : 'mkdir /sideload' ajoute")
    open(irc, "w").write(s)
    print("init.rc : service recovery -> /sbin/%s" % rname)

    ramdisk_tool.pack(root, os.path.join(img, "ramdisk.gz"))
    marvell_recovery.pack(img, a.out)
    print("image : %s (%d octets)" % (a.out, os.path.getsize(a.out)))


if __name__ == "__main__":
    main()
