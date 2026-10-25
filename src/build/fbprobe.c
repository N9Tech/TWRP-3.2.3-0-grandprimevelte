/*
 * fbprobe.c - sonde d'affichage pour mmp-fb (PXA1908 / SM-G531F)
 *
 * But : déterminer EMPIRIQUEMENT quel tampon du framebuffer le contrôleur
 * d'affichage scanne réellement, et si le pilote honore yoffset.
 *
 * Contexte mesuré : xres=540 yres=960 xres_virtual=544 yres_virtual=2880
 *                   line_length=2176 smem_len=6266880 bpp=32  -> TRIPLE buffer
 * TWRP 3.2 ne gère que le double buffer (voir XDA, Galaxy Tab A6, ashyx).
 *
 * Séquence (chaque étape est journalisée dans /tmp/probe.log) :
 *   1. lit et journalise var/fix AVANT (xres, yres, virtual, offsets, yoffset)
 *   2. remplit le tampon 0 en BLANC, pan sur 0, vérifie par GETV  -> pause 3 s
 *   3. remplit le tampon 1 en VERT,  pan sur 1, vérifie par GETV  -> pause 3 s
 *   4. remplit le tampon 2 en BLEU,  pan sur 2, vérifie par GETV  -> pause 3 s
 *   5. remet yoffset=0, vérifie, journalise l'état final
 *
 * Ce que l'utilisateur doit voir : BLANC, puis VERT, puis BLEU (3 s chacun).
 *   - les 3 couleurs  -> les écritures ET le panning fonctionnent
 *   - une seule        -> yoffset ignoré : seul ce tampon est scanné
 *   - aucune            -> le fb n'est pas la source affichée (overlay/logo)
 *
 * Compilation (pas de libc, syscalls directs) :
 *   arm-linux-gnueabihf-gcc -O2 -nostdlib -nostartfiles -ffreestanding \
 *     -fno-builtin -march=armv7-a -mfloat-abi=softfp -static -Wl,-e,_start \
 *     -o fbprobe fbprobe.c
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

#define NR_exit   1
#define NR_read   3
#define NR_write  4
#define NR_open   5
#define NR_close  6
#define NR_ioctl  54
#define NR_nanosleep 162
#define NR_lseek  19

static inline long s1(long n, long a) {
    register long r7 __asm__("r7") = n; register long r0 __asm__("r0") = a;
    __asm__ volatile("svc 0" : "+r"(r0) : "r"(r7) : "memory"); return r0;
}
static inline long s2(long n, long a, long b) {
    register long r7 __asm__("r7") = n; register long r0 __asm__("r0") = a;
    register long r1 __asm__("r1") = b;
    __asm__ volatile("svc 0" : "+r"(r0) : "r"(r1), "r"(r7) : "memory"); return r0;
}
static inline long s3(long n, long a, long b, long c) {
    register long r7 __asm__("r7") = n; register long r0 __asm__("r0") = a;
    register long r1 __asm__("r1") = b; register long r2 __asm__("r2") = c;
    __asm__ volatile("svc 0" : "+r"(r0) : "r"(r1), "r"(r2), "r"(r7) : "memory");
    return r0;
}

static void log_s(const char *s) {
    long n = 0, fd;
    while (s[n]) n++;
    fd = s3(NR_open, (long)"/tmp/probe.log", 02101 /*O_WRONLY|O_CREAT|O_APPEND*/, 0644);
    if (fd >= 0) { s3(NR_write, fd, (long)s, n); s1(NR_close, fd); }
}
static void log_kv(const char *key, long v) {
    char buf[64], tmp[16];
    int i = 0, j = 0;
    while (key[i] && i < 40) { buf[i] = key[i]; i++; }
    buf[i++] = '=';
    if (v < 0) { buf[i++] = '-'; v = -v; }
    if (!v) tmp[j++] = '0';
    while (v) { tmp[j++] = (char)('0' + (v % 10)); v /= 10; }
    while (j) buf[i++] = tmp[--j];
    buf[i++] = '\n';
    {
        long fd = s3(NR_open, (long)"/tmp/probe.log", 02101, 0644);
        if (fd >= 0) { s3(NR_write, fd, (long)buf, i); s1(NR_close, fd); }
    }
}
static long x_lseek(int fd, long off, int whence) {
    return s3(NR_lseek, (long)fd, off, (long)whence);
}

static void msleep(u32 ms) {
    struct { long s, ns; } ts;
    ts.s = (long)(ms >> 10) + ((ms & 1023) >= 1000 ? 1 : 0);   /* ~ ms/1000 */
    ts.ns = (long)(ms % 1000) * 1000000L;                      /* constantes */
    s2(NR_nanosleep, (long)&ts, 0);
}

/* remplit une image (yres lignes de line_length) avec la couleur BGRA donnée */
static void fill(int fd, u32 line_length, u32 yres, u32 px, u32 color) {
    static u32 row[1024];
    u32 w = (px == 2) ? (line_length >> 1) : (line_length >> 2), x, y;
    if (w > 1024) w = 1024;
    for (x = 0; x < w; x++) row[x] = color;
    for (y = 0; y < yres; y++) s3(NR_write, fd, (long)row, w * px);
}

static int pan(int fd, struct fb_var_screeninfo *vi, u32 yoff, u32 yv) {
    struct fb_var_screeninfo v;
    long r;
    s3(NR_ioctl, fd, FBIOGET_VSCREENINFO, (long)&v);
    v.yoffset = yoff;
    v.yres_virtual = yv;
    r = s3(NR_ioctl, fd, FBIOPUT_VSCREENINFO, (long)&v);
    log_kv("  put_rc", r);
    s3(NR_ioctl, fd, FBIOPAN_DISPLAY, (long)&v);
    /* verification par relecture */
    if (s3(NR_ioctl, fd, FBIOGET_VSCREENINFO, (long)&v) == 0) {
        log_kv("  yoffset_lu", (long)v.yoffset);
        log_kv("  yres_virtual_lu", (long)v.yres_virtual);
        log_kv("  yoffset_demande", (long)yoff);
    }
    (void)vi;
    return 0;
}

void _start(void) {
    struct fb_var_screeninfo vi;
    struct fb_fix_screeninfo fi;
    int fd;
    u32 yres, line, px;

    log_s("=== fbprobe ===\n");
    fd = s3(NR_open, (long)"/dev/graphics/fb0", 2 /*O_RDWR*/, 0);
    if (fd < 0) { log_s("ouverture fb0 impossible\n"); s1(NR_exit, 1); }

    if (s3(NR_ioctl, fd, FBIOGET_FSCREENINFO, (long)&fi) < 0 ||
        s3(NR_ioctl, fd, FBIOGET_VSCREENINFO, (long)&vi) < 0) {
        log_s("ioctl fb impossible\n"); s1(NR_exit, 1);
    }
    yres = vi.yres; line = fi.line_length; px = (vi.bits_per_pixel == 16) ? 2 : 4;
    log_s("--- AVANT ---\n");
    log_kv("xres", (long)vi.xres);
    log_kv("yres", (long)vi.yres);
    log_kv("xres_virtual", (long)vi.xres_virtual);
    log_kv("yres_virtual", (long)vi.yres_virtual);
    log_kv("xoffset", (long)vi.xoffset);
    log_kv("yoffset", (long)vi.yoffset);
    log_kv("bpp", (long)vi.bits_per_pixel);
    log_kv("line_length", (long)line);
    log_kv("smem_len", (long)fi.smem_len);
    log_kv("smem_div_line_x_yres", (long)(fi.smem_len >= 3 * line * yres ? 3 : (fi.smem_len >= 2 * line * yres ? 2 : 1)));

    /* 1. tampon 0 : BLANC */
    log_s("--- tampon 0 : BLANC (3 s) ---\n");
    pan(fd, &vi, 0, vi.yres_virtual);
    if (x_lseek(fd, (long)0, 0) >= 0) log_s("lseek 0 ok\n");
    fill(fd, line, yres, px, 0xFFFFFFFFu);
    msleep(3000);

    /* 2. tampon 1 : VERT */
    log_s("--- tampon 1 : VERT (3 s) ---\n");
    pan(fd, &vi, yres, vi.yres_virtual);
    if (x_lseek(fd, (long)(line * yres), 0) >= 0) log_s("lseek 1 ok\n");
    fill(fd, line, yres, px, 0xFF00FF00u);
    msleep(3000);

    /* 3. tampon 2 : BLEU */
    log_s("--- tampon 2 : BLEU (3 s) ---\n");
    pan(fd, &vi, 2 * yres, vi.yres_virtual);
    if (x_lseek(fd, (long)(line * yres * 2), 0) >= 0) log_s("lseek 2 ok\n");
    fill(fd, line, yres, px, 0xFF0000FFu);
    msleep(3000);

    /* 4. retour au tampon 0 */
    log_s("--- retour tampon 0 (noir) ---\n");
    pan(fd, &vi, 0, vi.yres_virtual);
    x_lseek(fd, (long)0, 0);
    fill(fd, line, yres, px, 0xFF000000u);
    msleep(500);

    log_s("=== fin fbprobe ===\n");
    s1(NR_close, fd);
    s1(NR_exit, 0);
}
