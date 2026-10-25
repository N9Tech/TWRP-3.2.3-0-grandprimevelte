#!/sbin/busybox sh
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

# point de montage FUSE utilise par adb sideload (libminadbd monte /dev/fuse ici)
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
