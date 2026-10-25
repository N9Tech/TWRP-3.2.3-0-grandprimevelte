# Notes techniques — TWRP 3.2.3-0 hybride pour SM-G531F

## Pourquoi « hybride »

Marvell n'a jamais publié les sources du PXA1908 (ni kernel, ni gralloc, ni
galcore). Aucune compilation complète de TWRP n'est donc possible depuis un PC :
la seule voie sans machine de build est de **conserver le kernel 3.14 + le
`dt.img` d'origine** (les seuls binaires qui pilotent ce matériel) et de greffer
l'**userspace TWRP 3.2.3** d'un donneur ARM 32 bits.

```
twrp-3.0.2 G531F (origine)            donneur TWRP 3.2.3 (ARM 32 bits)
├── kernel 6 294 393 o        ─────┐  ├── sbin/recovery  (3.2.3-0)
├── dt.img 129 024 o          ─────┤  ├── linker + 26 libs
├── init.rc / ueventd.rc      ─────┤  └── twres/ (thème 3.2)
└── fstab soc.2               ─────┤
                                   ▼
                        recovery.img hybride
              + /sbin/libfbfix.so  (correctif framebuffer)
              + /sbin/fbfix.conf   (réglages, modifiables en adb)
              + /sbin/fbfix_run.sh (wrapper avant TWRP)
```

## Correctif écran : interposeur ioctl (v3)

`build/fbfix.c` → `build/libfbfix.so` (ELF ARM, 67 Ko, **aucune dépendance** :
`-nostdlib -ffreestanding`, syscalls ARM directs, `ioctl` exporté, 0 relocation
`UND`). Chargé par `LD_PRELOAD` depuis le wrapper.

Principe : ne jamais toucher une valeur qui conditionne une taille d'accès
mémoire. Le seul levier est `smem_len`, qui n'influence que la décision de minui
de double-bufferiser.

| Interception | Effet |
|---|---|
| `FBIOGET_FSCREENINFO` | après l'appel réel, renvoie `smem_len = yres × line_length` (valeurs **réelles**) → `yres×line_length×2 > smem_len` → minui passe en **simple buffer** et copie son rendu vers fb0. Valeur toujours ≤ `smem_len` réelle. |
| `FBIOGET_VSCREENINFO` | appel réel, **rien de modifié**, journal seul |
| `FBIOPUT_VSCREENINFO` | appel réel + `FBIOPAN_DISPLAY` (0x4606) pour appliquer `yoffset` |

### Historique des tentatives (important)

| version | approche | résultat |
|---|---|---|
| FBFIX 1 | `fbset` (busybox Alpine) dans un wrapper avant TWRP | démarre, écran inchangé (le pilote ne suit pas `yoffset`) |
| FBFIX 2 | `LD_PRELOAD` + mire 8 s + `line_length = xres×4` **supposé** | **reboot ×3** : si le pilote est en 16 bpp, lignes de 2160 o dans un buffer de 1080 o/ ligne → écriture hors buffer → oops noyau |
| FBFIX 3 (livrée) | `smem_len = 1 image` avec les valeurs réelles, aucune géométrie inventée, aucune écriture fb, aucun sleep + **watchdog** (relance sans correctif si TWRP meurt en < 8 s) | à tester |

Compilation :

```bash
arm-linux-gnueabihf-gcc -O2 -fPIC -shared -nostdlib -nostartfiles \
    -ffreestanding -fno-builtin -march=armv7-a -mfloat-abi=softfp \
    -o libfbfix.so fbfix.c
readelf --dyn-syms libfbfix.so   # doit ne montrer AUCUN symbole UND
```

## Outils fournis (`tools/`)

| Outil | Rôle |
|---|---|
| `marvell_recovery.py` | unpack/pack d'une image Marvell (page 2048, header moderne **et** pré-2015). Validé : reproduit `twrp-3.0.2-0-grandprimevelte.img` **octet pour octet** (SHA-1 du header compris) |
| `ramdisk_tool.py` | extract/pack cpio newc + gzip (gère symlinks, permissions, root:root) |
| `make_hybrid.py` | construit les images hybrides depuis un donneur (`--donor`) et l'image de base (`--base`) |
| `inject_fbfix.py` | injecte `libfbfix.so` + conf + wrapper dans une image hybride |
| `verify_image.py` | contrôle : version TWRP, libs `DT_NEEDED` manquantes, fstab `soc.2`, taille vs partition, kernel/dtb d'origine |
| `make_tar.sh` | `.img` → `.img.tar` (membre unique `recovery.img`, propriétaire root) |
| `marvell-mkbootimg-x86_64` | `mkbootimg` Marvell recompilé en 64 bits (l'original livré par TeamWin est un ELF **i386**) |

Refaire une image complète :

```bash
python3 tools/make_hybrid.py --donor twrp-3.2.3-0-bacon.img \
        --base twrp-3.0.2-0-grandprimevelte.img --outdir out/
python3 tools/inject_fbfix.py --in out/recovery_variantA.img \
        --out out/final.img --so build/libfbfix.so
tools/make_tar.sh out/final.img
python3 tools/verify_image.py out/final.img
```

## Ce qui reste hors de portée sans compilation

- **Affichage définitif** : si la géométrie du pilote est exotique (par ex.
  `smem_len` non multiple de la ligne), seul un build avec le `graphics.c` du
  device réglera le problème à 100 %. L'arbre device TeamWin (`android-5.1`) et
  les correctifs pour le manifest `twrp-8.1` sont publiés en amont ; un fork
  personnel + GitHub Actions suffit à rejouer la compilation.
- **Version affichée « bacon »** : le nom du modèle est compilé dans le binaire.
  L'identité `ro.product.device=grandprimevelte` est en revanche injectée, donc
  les ZIP avec `assert` passent.
- **`TW_EXCLUDE_MTP`** : MTP est coupé dans ce build (pas de
  `/dev/usb_mtp_gadget` fonctionnel en recovery) ; adb fonctionne.
