/*
 * fb2txt.c - "capture d'écran en texte" pour mmp-fb (PXA1908 / SM-G531F)
 *
 * Lit un framebuffer BGRA (540x960, line_length 2176) et écrit une carte
 * grossière en ASCII dans /tmp/shot.txt, lisible par un humain et par moi.
 * Permet de VOIR ce que TWRP a réellement dessiné, sans outil graphique.
 *
 * Légende :  .  noir      :  gris très sombre   o  gris moyen   O  gris clair
 *            W  blanc      r/g/b  rouge/vert/bleu dominants atténués
 *            R/G/B  rouge/vert/bleu francs
 *
 * Échantillonnage : 1 pixel sur 12 en x (45 colonnes), 1 sur 15 en y (64 lignes).
 * Aucune division, aucune libc (syscalls ARM directs).
 *
 * arm-linux-gnueabihf-gcc -O2 -nostdlib -nostartfiles -ffreestanding \
 *   -fno-builtin -march=armv7-a -mfloat-abi=softfp -static -Wl,-e,_start \
 *   -o fb2txt fb2txt.c
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
#define FBIOGET_FSCREENINFO 0x4602

#define NR_exit  1
#define NR_read  3
#define NR_write 4
#define NR_open  5
#define NR_close 6
#define NR_lseek 19
#define NR_ioctl 54

static inline long s1(long n, long a) {
    register long r7 __asm__("r7") = n; register long r0 __asm__("r0") = a;
    __asm__ volatile("svc 0" : "+r"(r0) : "r"(r7) : "memory"); return r0;
}
static inline long s3(long n, long a, long b, long c) {
    register long r7 __asm__("r7") = n; register long r0 __asm__("r0") = a;
    register long r1 __asm__("r1") = b; register long r2 __asm__("r2") = c;
    __asm__ volatile("svc 0" : "+r"(r0) : "r"(r1), "r"(r2), "r"(r7) : "memory");
    return r0;
}

#define O_RDONLY 0
#define O_WRONLY 1
#define O_CREAT  0100
#define O_APPEND 02000

/* tampon statique du framebuffer (2 Mo en BSS, pas dans le fichier) */
static unsigned char fbraw[2176 * 960];

static char out[60000];
static int olen = 0;

static void put(const char *s) { while (*s) out[olen++] = *s++; }
static void putc_(char c) { out[olen++] = c; }
static void putn(long v) {
    char t[16]; int i = 0;
    if (v < 0) { putc_('-'); v = -v; }
    if (!v) t[i++] = '0';
    while (v) { t[i++] = (char)('0' + (v % 10)); v /= 10; }
    while (i) putc_(t[--i]);
}

static char classify(unsigned char b, unsigned char g, unsigned char r) {
    int mx = r > g ? (r > b ? r : b) : (g > b ? g : b);
    int mn = r < g ? (r < b ? r : b) : (g < b ? g : b);
    int chroma = mx - mn;
    if (mx < 24) return '.';
    if (chroma < 24) {                       /* gris */
        if (mx > 232) return 'W';
        if (mx > 160) return 'O';
        if (mx > 80)  return 'o';
        return ':';
    }
    if (mx > 200) {                          /* couleur franche */
        if (r == mx) return 'R';
        if (g == mx) return 'G';
        return 'B';
    }
    if (r == mx) return 'r';
    if (g == mx) return 'g';
    return 'b';
}

void _start(void) {
    struct fb_var_screeninfo vi;
    struct fb_fix_screeninfo fi;
    int fd, outfd;
    long got;
    u32 line = 2176, yres = 960, xres = 540, off = 0;
    u32 x, y, cx, cy;
    u32 nonblack = 0, first_row = 0xFFFFFFFFu, last_row = 0, colors[8];
    u32 i;
    char cc;

    for (i = 0; i < 8; i++) colors[i] = 0;

    fd = s3(NR_open, (long)"/dev/graphics/fb0", O_RDONLY, 0);
    if (fd >= 0) {
        if (s3(NR_ioctl, fd, FBIOGET_FSCREENINFO, (long)&fi) == 0)
            line = fi.line_length ? fi.line_length : 2176;
        if (s3(NR_ioctl, fd, FBIOGET_VSCREENINFO, (long)&vi) == 0) {
            if (vi.yres) yres = vi.yres;
            if (vi.xres) xres = vi.xres;
        }
        s3(NR_lseek, fd, 0, 0);
        got = s3(NR_read, fd, (long)fbraw, (long)sizeof(fbraw));
        s1(NR_close, fd);
    } else {
        got = -1;
    }

    put("=== fb2txt (capture texte du framebuffer) ===\n");
    put("line_length="); putn((long)line);
    put("  xres="); putn((long)xres);
    put("  yres="); putn((long)yres);
    put("  octets_lus="); putn(got); put("\n\n");

    /* grille 45 x 64 */
    for (cy = 0; cy < 64; cy++) {
        y = cy * 15;
        if (y >= yres) break;
        for (cx = 0; cx < 45; cx++) {
            x = cx * 12;
            if (x >= xres) break;
            off = y * line + (x << 2);
            if (got > (long)(off + 4)) {
                cc = classify(fbraw[off + 0], fbraw[off + 1], fbraw[off + 2]);
                putc_(cc);
                if (cc != '.') {
                    nonblack++;
                    if (y < first_row) first_row = y;
                    if (y > last_row) last_row = y;
                }
                switch (cc) {
                    case '.': colors[0]++; break;
                    case ':': colors[1]++; break;
                    case 'o': colors[2]++; break;
                    case 'O': colors[3]++; break;
                    case 'W': colors[4]++; break;
                    case 'R': case 'r': colors[5]++; break;
                    case 'G': case 'g': colors[6]++; break;
                    default:  colors[7]++; break;
                }
            } else {
                putc_('?');
            }
        }
        putc_('\n');
    }

    put("\n--- stats ---\n");
    put("cellules_non_noires="); putn((long)nonblack); put(" / 2880\n");
    put("premiere_ligne_non_noire="); putn(first_row == 0xFFFFFFFFu ? -1 : (long)first_row); put("\n");
    put("derniere_ligne_non_noire="); putn((long)last_row); put("\n");
    put("noir="); putn((long)colors[0]);
    put(" gris_sombre="); putn((long)colors[1]);
    put(" gris_moyen="); putn((long)colors[2]);
    put(" gris_clair="); putn((long)colors[3]);
    put(" blanc="); putn((long)colors[4]);
    put(" rouge="); putn((long)colors[5]);
    put(" vert="); putn((long)colors[6]);
    put(" bleu="); putn((long)colors[7]);
    put("\n");

    outfd = s3(NR_open, (long)"/tmp/shot.txt", O_WRONLY | O_CREAT | O_APPEND, 0644);
    if (outfd >= 0) { s3(NR_write, outfd, (long)out, olen); s1(NR_close, outfd); }
    s3(NR_write, 1, (long)out, olen);      /* aussi sur stdout (adb) */
    s1(NR_exit, 0);
}
