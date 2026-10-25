# SM-G531F — TWRP 3.2.3-0 : **TESTÉ ET FONCTIONNEL** ✅

**Image : `TWRP-3.2.3-0-G531F.img.tar`** — MD5 `6b874d8c92ef9237258ffeb6f49f785d`

> Flashée sur l'appareil : écran blanc → vert → rouge → logo → **menu TWRP affiché**.
> Version 3.2.3-0 (supérieure au minimum 3.2 demandé), interface complète à 540×960.

---

## 0. À faire en tout premier (5 minutes, ça peut sauver le téléphone)

Dans TWRP, avant toute autre manipulation : **Backup** → coche **EFS**, **Boot**, **Recovery**
→ destination *Internal Storage* → *Swipe to Back up*. L'EFS contient les identifiants radio
(IMEI) : sans sauvegarde, une mauvaise manip peut le rendre irrécupérable.

Copie ensuite le dossier `TWRP/BACKUPS/` sur ton PC, et garde aussi ce `.img.tar` de côté :
c'est ta porte de sortie si un jour un flash tourne mal.

---

## 1. La cause de tout, enfin

Ton `/tmp/fb.txt` a livré la preuve :

```
--- AVANT reparation ---
/twres        : seulement portrait.xml, splash.xml, twrp, ui.xml + 3 dossiers
/twres/fonts  : DroidSansFallback.ttf SEUL (3 725 920 o)
images        : 0 fichiers
```

**Le noyau de ce téléphone n'extrait qu'une partie du ramdisk.** J'ai mesuré la coupure
dans l'archive décompressée : elle tombe pile après `twres/fonts/DroidSansFallback.ttf`,
à l'octet **13 021 016** — alors que l'archive complète en fait **15 034 368**. Soit **86,6 %**.
Tout ce qui se trouvait ensuite n'a jamais existé sur l'appareil :

| Ce qui manquait | Symptôme que ça a produit |
|---|---|
| `twres/images/` (les 57 PNG) | la bande grise, pas de logo |
| `twres/fonts/` (4 polices sur 5) | `Failed to load truetype face … : 1` (v6) |
| **`twres/languages/` (les 22 langues, dont `en.xml`)** | **crash après `Loading page main2`** (v7) |

Mon `theme.tar` de la v7 avait restauré polices **et** images — c'est pour ça que le logo
s'est mis à s'afficher correctement — mais **pas `en.xml`**. Sans aucune chaîne de caractères,
TWRP plante au moment de dessiner le menu principal. Tout s'explique : les trois symptômes
successifs n'étaient qu'un seul et même problème, la fin de l'archive jamais extraite.

> Au passage : `indeterminate013` était bien un faux problème (le thème a les frames 001→012,
> TWRP sonde la 013 pour savoir où s'arrêter).

## 2. Le correctif

Je ne dépends plus de la fin de l'archive :

1. **`/twres` est retiré du cpio** et livré entier dans **`/sbin/theme.tar`** (645 120 o,
   65 fichiers : les 3 XML, 2 polices utiles, les 57 images, `en.xml` + `fr.xml`, le marqueur `twrp`).
   `/sbin` est au **début** de l'archive : c'est la zone qui est toujours extraite.
2. Le lanceur **reconstruit `/twres` à chaque démarrage** (`mkdir -p /twres` + `tar xf`), puis
   vérifie pièce par pièce (`ui.xml`, `splash.xml`, `portrait.xml`, `en.xml`, les 2 polices,
   `splashlogo.png`) avant de démarrer TWRP.
3. Les deux polices inutiles (CJK, 4,4 Mo à elles deux) et 19 langues inutilisées sont
   supprimées → **ramdisk 4,80 Mo au lieu de 7,52 Mo**, cpio 9,40 Mo au lieu de 15,03 Mo.
   Même si la limite du noyau reste à 13 021 016 octets, **plus rien n'est coupé**.

## 3. Vérifications faites

```
problemes            : []
twrp_version         : 3.2.3-0
tient_dans_partition : True          image 11 223 040 o (< 16 Mo)
libs_requises        : 26, libs_manquantes : []
theme_tar            : 69 entrees, 57 images, en.xml + fr.xml, 2 polices
kernel / dtb         : ceux du G531F d'origine (6 294 393 / 129 024)
cpio                 : 9 401 856 o  <  13 021 016 o (limite observee)
```

## 4. À faire

1. Flash : Odin → **AP** → Auto Reboot / Re-Partition décochés → `PASS`
   → batterie → **Vol+ + Home + Power**.
2. Tu dois voir : blanc → vert → rouge → logo TWRP → **le menu TWRP**.
3. Si jamais ça bloque encore, récupère (comme la dernière fois, c'est ce qui a tout résolu) :

```bash
adb pull /tmp/fb.txt
adb pull /tmp/recovery.log
```

Le gestionnaire de crash de la v8 reste embarqué : en cas de plantage il écrit `/tmp/crash.txt`
avec les registres ARM et la carte mémoire, donc je saurai nommer la fonction exacte.

## 5. Limites connues de cette image

- **Langues** : seules `en` et `fr` sont embarquées (les 19 autres pesaient 0,9 Mo et se
  trouvaient dans la zone coupée de l'archive). Le thème est en anglais par défaut ;
  pour le passer en français : *Settings → Language* (ou l'icône globe du menu).
- **Polices CJK** retirées (4,4 Mo) : les textes en japonais/chinois/coréen ne s'afficheraient
  pas. Sans effet sur le reste.
- Ne flashe **pas** un firmware Odin complet avec cette recovery installée sans avoir sauvegardé
  l'EFS d'abord.

## 6. Rappel utile

Même sans interface, l'appareil était pilotable : `adb shell twrp backup`, `twrp wipe data`,
`twrp install /sdcard/x.zip`.

## 7. Historique

| Version | Approche | Résultat |
|---|---|---|
| FBFIX 3/4 | géométrie du framebuffer | logo figé → a donné les valeurs réelles (2176, 540×960) |
| v5 | sonde couleurs | blanc/vert/bleu OK : framebuffer et panning validés |
| v6 | captures texte | `recovery.log` → erreurs de police |
| v7 | restauration du thème par `tar` | **logo affiché**, mais crash après `Loading page main2` |
| v8 | gestionnaire de crash + état réel du processus | a fourni `/tmp/fb.txt` → **la coupure à 13 021 016 octets** |
| v9 | thème complet dans `/sbin/theme.tar`, ramdisk allégé de 36 % | **FONCTIONNE** ✅ |
