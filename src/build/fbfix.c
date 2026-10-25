/*
 * fbfix.c - interposeur ioctl pour le framebuffer Marvell mmp-fb du PXA1908
 *           (Samsung Galaxy Grand Prime VE SM-G531F)
 *
 * GÉOMÉTRIE RÉELLE MESURÉE SUR L'APPAREIL (log /tmp/fbfix.log) :
 *
 *   name            = mmp-fb
 *   xres            = 540      yres            = 960
 *   xres_virtual    = 544      yres_virtual    = 2880     (= 3 x 960 !)
 *   bits_per_pixel  = 32
 *   line_length     = 2176     (= 544 x 4, avec 4 px de padding par ligne)
 *   smem_len        = 6266880  (= 544 x 2880 x 4)
 *   offsets         = red 0, green 8, blue 16
 *
 * Conséquence : minui (TWRP 3.2) voyait  yres*line_length*2 = 4 177 920 <=
 * smem_len -> il activait son double buffer et "flippait" en jouant sur
 * yoffset = n*960 dans un buffer TRIPLE. La zone réellement scannée restait
 * la première image -> écran figé sur le logo / bande grise.
 *
 * STRATÉGIE (v4) : mentir le moins possible, mais de façon cohérente.
 *   GET_FSCREENINFO : line_length INCHANGÉ (2176, la vraie valeur !) et
 *                     smem_len = line_length * yres (= une seule image)
 *                     -> minui ne voit pas de place pour 2 images
 *                     -> chemin SIMPLE BUFFER : il alloue son propre tampon
 *                        et copie vers fb0 avec le bon pas de ligne.
 *   GET_VSCREENINFO : xres/yres/bpp INCHANGÉS ; xres_virtual=yres_virtual
 *                     ramenés à la taille réelle, xoffset/yoffset = 0.
 *   PUT_VSCREENINFO : transmis, puis FBIOPAN_DISPLAY pour que le pilote
 *                     applique (0x4606).
 *
 * Aucune valeur inventée, aucune écriture hors du buffer (smem_len renvoyé
 * est toujours <= la vraie smem_len), aucune mire, aucun sleep.
 *
 * Compilation sans libc (bionic ne charge pas une .so glibc) :
 *   arm-linux-gnueabihf-gcc -O2 -fPIC -shared -nostdlib -nostartfiles \
 *     -ffreestanding -fno-builtin -march=armv7-a -mfloat-abi=softfp \
 *     -o libfbfix.so fbfix.c
 */
typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned long ulong;

struct fb_bitfield { u32 offset, length, msb_right; };

struct fb_var_screeninfo {
    u32 xres, yres, xres_virtual, yres_virtual, xoffset, yoffset;
    u32 bits_per_pixel, grayscale;
    struct fb_bitfield red, green, blue, transp;
    u32 nonstd, activate, height, width, accel_flags;
    u32 pixclock, left_margin, right_margin, upper_margin, lower_margin;
    u32 hsync_len, vsync_len, sync, vmode, rotate, colorspace;
    u32 reserved[4];
};

struct fb_fix_screeninfo {
    char id[16];
    ulong smem_start;
    u32 smem_len;
    u32 type, type_aux, visual;
    u16 xpanstep, ypanstep, ywrapstep;
    u32 line_length;
    ulong mmio_start;
    u32 mmio_len, accel;
    u16 capabilities, reserved[2];
};

#define FBIOGET_VSCREENINFO 0x4600
#define FBIOPUT_VSCREENINFO 0x4601
#define FBIOGET_FSCREENINFO 0x4602
#define FBIOPAN_DISPLAY     0x4606

#define NR_write 4
#define NR_open  5
#define NR_close 6
#define NR_read  3
#define NR_ioctl 54

static inline long sys1(long n, long a) {
    register long r7 __asm__("r7") = n;
    register long r0 __asm__("r0") = a;
    __asm__ volatile("svc 0" : "+r"(r0) : "r"(r7) : "memory");
    return r0;
}
static inline long sys3(long n, long a, long b, long c) {
    register long r7 __asm__("r7") = n;
    register long r0 __asm__("r0") = a;
    register long r1 __asm__("r1") = b;
    register long r2 __asm__("r2") = c;
    __asm__ volatile("svc 0" : "+r"(r0) : "r"(r1), "r"(r2), "r"(r7) : "memory");
    return r0;
}

#define O_RDONLY 0
#define O_WRONLY 1
#define O_CREAT  0100
#define O_APPEND 02000
#define O_TRUNC  01000

static void log_s(const char *s) {
    long n = 0, fd;
    while (s[n]) n++;
    fd = sys3(NR_open, (long)"/tmp/fbfix.log", O_WRONLY | O_CREAT | O_APPEND, 0644);
    if (fd >= 0) { sys3(NR_write, fd, (long)s, n); sys1(NR_close, fd); }
}

static void log_kv(const char *key, long v) {
    char buf[64], tmp[16];
    int i = 0, j = 0, num = 0;
    while (key[i] && i < 40) { buf[i] = key[i]; i++; }
    buf[i++] = '=';
    if (v < 0) { buf[i++] = '-'; v = -v; }
    if (!v) tmp[j++] = '0';
    while (v) { tmp[j++] = (char)('0' + (v % 10)); v /= 10; }
    while (j) buf[i++] = tmp[--j];
    buf[i++] = '\n';
    {
        long fd = sys3(NR_open, (long)"/tmp/fbfix.log", O_WRONLY | O_CREAT | O_APPEND, 0644);
        if (fd >= 0) { sys3(NR_write, fd, (long)buf, i); sys1(NR_close, fd); }
    }
}

static int atoi_simple(const char *s) {
    int v = 0;
    while (*s >= '0' && *s <= '9') { v = v * 10 + (*s - '0'); s++; }
    return v;
}

/* conf : mode 1 = simple buffer (défaut), 0 = ne rien changer ; pan 1 = FBIOPAN */
static u32 cfg_mode = 1, cfg_pan = 1, cfg_loaded = 0;
static u32 real_yres = 0, real_line = 0, real_smem = 0;
static u32 seen_fi = 0, seen_vi = 0, n_put = 0;

static void read_conf(void) {
    char buf[256];
    long fd = sys3(NR_open, (long)"/sbin/fbfix.conf", O_RDONLY, 0), n;
    if (fd < 0) return;
    n = sys3(NR_read, fd, (long)buf, sizeof(buf) - 1);
    sys1(NR_close, fd);
    if (n <= 0) return;
    buf[n] = 0;
    {
        char *p = buf;
        while (*p) {
            char *k = p;
            while (*p && *p != '=' && *p != '\n') p++;
            if (*p == '=') {
                char *v = ++p;
                int val;
                while (*p && *p != '\n') p++;
                val = atoi_simple(v);
                if (k[0] == 'm' && k[1] == 'o' && k[2] == 'd' && k[3] == 'e' && *p != 0)
                    cfg_mode = (u32)val;
                else if (k[0] == 'p' && k[1] == 'a' && k[2] == 'n') cfg_pan = (u32)val;
            }
            while (*p == '\n') p++;
        }
    }
    cfg_loaded = 1;
}

int ioctl(int fd, unsigned long req, ...) {
    void *arg;
    __builtin_va_list ap;
    __builtin_va_start(ap, req);
    arg = __builtin_va_arg(ap, void *);
    __builtin_va_end(ap);

    if (!cfg_loaded) {
        read_conf();
        log_s("=== fbfix v4 ===\n");
        log_kv("cfg_mode", (long)cfg_mode);
        log_kv("cfg_pan", (long)cfg_pan);
    }

    if (req == FBIOGET_FSCREENINFO) {
        struct fb_fix_screeninfo *fi = (struct fb_fix_screeninfo *)arg;
        struct fb_var_screeninfo v;
        long r = sys3(NR_ioctl, fd, (long)req, (long)arg);
        if (r == 0) {
            real_line = fi->line_length;
            real_smem = fi->smem_len;
            if (sys3(NR_ioctl, fd, FBIOGET_VSCREENINFO, (long)&v) == 0)
                real_yres = v.yres;
            if (!seen_fi) {
                seen_fi = 1;
                log_kv("reel_line_length", (long)real_line);
                log_kv("reel_smem_len", (long)real_smem);
                log_kv("reel_yres", (long)real_yres);
            }
            /* UNE seule image, avec le VRAI pas de ligne -> simple buffer */
            if (cfg_mode && real_yres && real_line &&
                (u32)(real_yres * real_line) <= real_smem) {
                fi->smem_len = real_yres * real_line;   /* 2 088 960 */
                log_kv("force_smem_len", (long)fi->smem_len);
                log_kv("line_length_conserve", (long)fi->line_length);
            }
        }
        return r;
    }

    if (req == FBIOGET_VSCREENINFO) {
        struct fb_var_screeninfo *vi = (struct fb_var_screeninfo *)arg;
        long r = sys3(NR_ioctl, fd, (long)req, (long)arg);
        if (r == 0 && !seen_vi) {
            seen_vi = 1;
            log_kv("reel_xres", (long)vi->xres);
            log_kv("reel_yres", (long)vi->yres);
            log_kv("reel_xres_virtual", (long)vi->xres_virtual);
            log_kv("reel_yres_virtual", (long)vi->yres_virtual);
            log_kv("reel_bits_per_pixel", (long)vi->bits_per_pixel);
            log_kv("reel_red_offset", (long)vi->red.offset);
            log_kv("reel_green_offset", (long)vi->green.offset);
            log_kv("reel_blue_offset", (long)vi->blue.offset);
        }
        if (r == 0 && cfg_mode) {
            /* xres / yres / bpp : INCHANGÉS. On remet juste la virtualisation
               et le cadrage sur la première image. */
            vi->xres_virtual = vi->xres;
            vi->yres_virtual = vi->yres;
            vi->xoffset = 0;
            vi->yoffset = 0;
        }
        return r;
    }

    if (req == FBIOPUT_VSCREENINFO) {
        struct fb_var_screeninfo *vi = (struct fb_var_screeninfo *)arg;
        long r = sys3(NR_ioctl, fd, (long)req, (long)arg);
        n_put++;
        if (n_put == 1 || n_put == 100)
            log_kv("put_yoffset_demande", (long)vi->yoffset);
        if (cfg_pan) {
            /* certains pilotes n'appliquent la fenêtre que sur FBIOPAN_DISPLAY */
            vi->yoffset = 0;
            vi->yres_virtual = vi->yres;
            vi->xoffset = 0;
            vi->xres_virtual = vi->xres;
            sys3(NR_ioctl, fd, FBIOPAN_DISPLAY, (long)vi);
        }
        return r;
    }

    return sys3(NR_ioctl, fd, (long)req, (long)arg);
}

/* =====================================================================
 * v8 - CAPTURE DE CRASH
 * TWRP meurt silencieusement apres le chargement du theme : son journal
 * est bufferise (stdio), donc la fin du log est perdue et on ne sait pas
 * ce qui s'est passe. On installe ici des gestionnaires de signaux qui
 * ecrivent, avec de simples appels systeme (aucune libc -> sur d'etre
 * appelable dans un contexte de crash), le signal, l'adresse fautive,
 * les 16 registres ARM, la carte memoire complete du processus et une
 * tranche de pile. Resultat : /tmp/crash.txt
 * ===================================================================== */
#define NR_exit_group  248
#define NR_rt_sigaction 67
#define NR_gettid       224
#define O_RDONLY_ 0

static inline long sys4(long n, long a, long b, long c, long d) {
    register long r7 __asm__("r7") = n;
    register long r0 __asm__("r0") = a;
    register long r1 __asm__("r1") = b;
    register long r2 __asm__("r2") = c;
    register long r3 __asm__("r3") = d;
    __asm__ volatile("svc 0" : "+r"(r0) : "r"(r1), "r"(r2), "r"(r3), "r"(r7) : "memory");
    return r0;
}

static char cbuf[4096];
static int  clen;

static void cflush(int fd) {
    if (clen > 0) { sys3(NR_write, fd, (long)cbuf, clen); clen = 0; }
}
static void cputc(int fd, char c) {
    if (clen >= (int)sizeof(cbuf) - 1) cflush(fd);
    cbuf[clen++] = c;
}
static void cputs(int fd, const char *s) { while (*s) cputc(fd, *s++); }
static void chex(int fd, unsigned long v) {
    char t[10]; int i = 8;
    cputs(fd, "0x");
    while (i--) { int d = v & 0xf; t[i] = d < 10 ? '0' + d : 'a' + d - 10; v >>= 4; }
    for (i = 0; i < 8; i++) cputc(fd, t[i]);
}
static void cdec(int fd, long v) {
    char t[12]; int i = 0;
    if (v < 0) { cputc(fd, '-'); v = -v; }
    if (v == 0) { cputc(fd, '0'); return; }
    while (v > 0) { t[i++] = '0' + (v % 10); v /= 10; }
    while (i--) cputc(fd, t[i]);
}

/* copie integrale d'un fichier texte (ici /proc/self/maps) */
static void ccopy(int out, const char *path) {
    char b[1024];
    long fd = sys3(NR_open, (long)path, O_RDONLY_, 0), n, i;
    if (fd < 0) { cputs(out, "(impossible d'ouvrir "); cputs(out, path); cputs(out, ")\n"); return; }
    while ((n = sys3(NR_read, fd, (long)b, sizeof(b))) > 0)
        for (i = 0; i < n; i++) cputc(out, b[i]);
    sys1(NR_close, fd);
}

static void crash_handler(int sig, void *info, void *uc) {
    unsigned long *regs = (unsigned long *)0;
    unsigned long fault = 0;
    long fd;
    int i;

    if (uc) {
        /* ucontext ARM : uc_mcontext a l'offset 20 ; regs a l'offset 12 */
        unsigned char *p = (unsigned char *)uc + 20;
        regs = (unsigned long *)(p + 12);          /* arm_r0 */
        fault = (unsigned long)(((unsigned long *)info)[3]);  /* si_addr */
    }

    fd = sys3(NR_open, (long)"/tmp/crash.txt", O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd < 0) fd = 1;
    clen = 0;
    cputs(fd, "================ CRASH TWRP ================\n");
    cputs(fd, "signal="); cdec(fd, sig);
    cputs(fd, "  (11=SEGV 7=BUS 4=ILL 8=FPE 6=ABRT)\n");
    cputs(fd, "adresse_fautive="); chex(fd, fault); cputc(fd, '\n');
    if (regs) {
        static const char *nm[16] = { "r0","r1","r2","r3","r4","r5","r6","r7",
                                      "r8","r9","r10","r11","r12","sp","lr","pc" };
        for (i = 0; i < 16; i++) {
            cputs(fd, "  "); cputs(fd, nm[i]); cputs(fd, " = "); chex(fd, regs[i]); cputc(fd, '\n');
        }
        /* tranche de pile : contient les adresses de retour des appelants */
        cputs(fd, "--- pile (96 mots depuis sp) ---\n");
        {
            unsigned long sp = regs[13] & ~3UL;
            unsigned long *s = (unsigned long *)sp;
            int k;
            for (k = 0; k < 96; k++) {
                if (k % 4 == 0) { cputc(fd, '\n'); cputs(fd, "  sp+"); }
                chex(fd, s[k]); cputc(fd, ' ');
            }
            cputc(fd, '\n');
        }
    }
    cputs(fd, "--- /proc/self/maps (pour retrouver le module et l'offset) ---\n");
    ccopy(fd, "/proc/self/maps");
    cputs(fd, "================ FIN ================\n");
    cflush(fd);
    if (fd > 2) sys1(NR_close, fd);
    sys1(NR_exit_group, 128 + sig < 255 ? 128 + sig : 139);
}

struct ksigaction { unsigned long handler, flags, restorer, mask[2]; };

__attribute__((constructor)) static void install_crash_handlers(void) {
    static struct ksigaction sa;
    int sigs[5] = { 11, 7, 4, 8, 6 };
    int i;
    sa.handler = (unsigned long)&crash_handler;
    sa.flags = 4 /*SA_SIGINFO*/ | 0x80000000 /*SA_RESETHAND*/;
    sa.restorer = 0;
    sa.mask[0] = sa.mask[1] = 0;
    for (i = 0; i < 5; i++)
        sys4(NR_rt_sigaction, sigs[i], (long)&sa, 0, 8);
}
