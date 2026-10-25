#!/sbin/busybox sh
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
