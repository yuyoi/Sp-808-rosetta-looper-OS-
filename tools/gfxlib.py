"""JSW graphics engine for the SP-808 LCD: H8S routines (via h8asm) + font/icon data (from ui_gfx).

Framebuffer FB (RAM, 512 bytes) = 4 strips x 32 rows x 4 bytes. Pixel (x, y), x 0-127, y 0-31, 1 = dark:
    byte FB + (x >> 5) * 128 + y * 4 + ((x >> 3) & 3), bit 7 - (x & 7)
gfx_flush packs FB straight into the boot ROM's LCD framebuffer (canvas at LCD x 4-131), which an interrupt
streams to the LCD all the time. From the boot ROM dump (dump/BOOTROM.BIN, 2026-10-13):
- LCD RAM image at 0x40187A: 34 rows x 24 bytes, 6 pixels per byte in bits 5-0 (bit 5 = left), bits 7-6 = 0.
  Rows 0-1 are the 7-segment / icon line, rows 2-33 the 32 dot rows: pointer @0x401EC4 (= 0x4018AA),
  stride @0x401EBC (= 24). Init 0x9DA8 / 0xA084, full copy 0xA046, interrupt streamer 0x9C58 (port 0xA00000
  command/status, 0xA00001 data).
- The blit API 0x400478 (0xB074) reads its source as 7 pixels per byte (bits 7-1, "and.w #0x1FE"), rows of
  ceil(w/7) bytes; rows-byte bit 7 = compressed source (unpacked to 0x401BAA), y bit 6 = invert,
  y bit 7 = second draw op. That is why 8-px-per-byte bitmaps lost every 8th pixel.

Routines (preserve er3-er6; er0-er2 are scratch unless noted):
  gfx_clear()                            FB = 0
  gfx_flush()                            FB -> LCD
  gfx_put8(r0l bits, r1l x, r1h y)       8 pixels, MSB at x, mode @GMODE (0 set, 1 clear, 2 invert). Keeps r1, er2.
  gfx_fill(r1l x, r1h y, r2l w, r2h h)   rectangle, mode @GMODE
  gfx_text(er0 str, r1l x, r1h y, er2 font) -> r1l = x after the text
  gfx_bitmap(er0 bmp, r1l x, r1h y)      bmp = w, h, then rows of (w + 7) / 8 bytes (MSB = left)
  gfx_patrow(er0 pat, r1h y, r2l w)      OR pixels x 0..w-1 of a 16-byte row pattern into row y (meters)
  gfx_vline(r1l x, r1h y, r2h h)         set pixels (x, y .. y + h - 1), y + h <= 32
Font = height, first char, last char, 0, then per glyph: advance, height row bytes (MSB = left).
Characters outside first..last draw as glyph 0 (space).
"""
import ui_gfx

BLIT = 0x400478
M_SET, M_CLR, M_INV = 0, 1, 2


def font_tiny():
    out = bytearray([5, 0x20, 0x5A, 0])
    for c in range(0x20, 0x5B):
        rows = ui_gfx.TINY.get(chr(c), [0] * 5)
        out += bytes([4] + [(r << 5) & 0xFF for r in rows])
    return bytes(out)


def font_57():
    out = bytearray([7, 0x20, 0x7A, 0])
    for c in range(0x20, 0x7B):
        cols = ui_gfx.F57.get(chr(c), [0] * 5)
        rows = [sum(((col >> r) & 1) << (7 - i) for i, col in enumerate(cols)) for r in range(7)]
        out += bytes([6] + rows)
    return bytes(out)


def font_big():
    """7-segment digits 7x11, advance 9; '.' and ':' advance 4. Range '-' .. ':'"""
    h = ui_gfx.BIG_H
    out = bytearray([h, 0x2D, 0x3A, 0])
    for c in range(0x2D, 0x3B):
        ch = chr(c)
        if ch in ui_gfx.SEGS:
            g = ui_gfx.big_digit(ch)
            rows = [sum(g[y][x] << (7 - x) for x in range(ui_gfx.BIG_W)) for y in range(h)]
            out += bytes([ui_gfx.BIG_W + 2] + rows)
        elif ch == '.':
            out += bytes([4] + [0] * 9 + [0xC0, 0xC0])
        elif ch == ':':
            out += bytes([4, 0, 0, 0xC0, 0xC0, 0, 0, 0, 0xC0, 0xC0, 0, 0])
        else:
            out += bytes([4] + [0] * h)
    return bytes(out)


def bitmap(rows):
    """rows of 'X'/'.' -> w, h, packed rows"""
    w, h = len(rows[0]), len(rows)
    bpr = (w + 7) // 8
    out = bytearray([w, h])
    for r in rows:
        v = 0
        for i, ch in enumerate(r.ljust(bpr * 8, '.')):
            if ch == 'X': v |= 1 << (bpr * 8 - 1 - i)
        out += v.to_bytes(bpr, 'big')
    return bytes(out)


LCD_X0 = 4                                       # canvas x 0 is LCD x 4 (gfx_flush)
LCD_FBPTR, LCD_STRIDE, LCD_BYTES = 0x401EC4, 24, 22   # dot-row pointer, bytes per row, bytes we write (132 px)


def pack6(px, x0):
    """one row of pixels (truthy = dark) starting at LCD x0 -> 24 LCD bytes (6 px per byte, bit 5 = left)"""
    out = bytearray(LCD_STRIDE)
    for i, on in enumerate(px):
        x = x0 + i
        if on and 0 <= x < 6 * LCD_STRIDE: out[x // 6] |= 1 << (5 - x % 6)
    return bytes(out)


def unpack6(row):
    """24 LCD bytes -> 144 pixels (for tests)"""
    return [(row[x // 6] >> (5 - x % 6)) & 1 for x in range(6 * LCD_STRIDE)]


def strips24(px):
    """canvas rows (32 x 128, truthy = dark) -> the 6 x 24 px strips gfx_flush builds (for data blitted as is)"""
    out = bytearray()
    for s in range(6):
        for y in range(32):
            v = 0
            for i in range(24):
                x = 24 * s + i - LCD_X0
                if 0 <= x < 128 and px[y][x]: v |= 1 << (31 - i)
            out += v.to_bytes(4, 'big')
    return bytes(out)


def emit(a, FB, GMODE, STG=None):
    """STG = 768-byte RAM staging buffer for gfx_flush (default right after FB).
    Note: build_v07 / v07b used a 32 px strip flush (broken on hw); rebuilding them now gives this flush."""
    if STG is None: STG = FB + 0x200
    """emit the engine routines and data into Asm a (labels gfx_*, font_tiny, font_57, font_big, icon_*)"""
    # ---- gfx_clear ----
    a.label('gfx_clear')
    a.push_l(2)
    a.mov_l_imm(FB, 1); a.sub_l(0, 0); a.mov_w_imm(128, 2)
    a.label('gc_loop')
    a.mov_l_st(0, 1); a.adds4(1); a.dec_w1(2); a.bne('gc_loop')
    a.pop_l(2); a.rts()

    # ---- gfx_flush: FB -> the boot ROM's LCD RAM image (6 px per byte), canvas at LCD x 4 ----
    # Per row the bit stream is 4 zero bits + 128 canvas bits = 132 bits = 22 LCD bytes. Stream byte j is the
    # canvas row shifted right by a nibble: S[j] = c[j-1] << 4 | c[j] >> 4 (c[-1] = c[16] = 0). Every 3 stream
    # bytes (24 bits) make 4 LCD bytes; the last 12 bits make 2. LCD bytes 22-23 (x 132-143) are cleared.
    def cdisp(j): return (j >> 2) * 128 + (j & 3)               # canvas byte j of the row at er4
    def load_c(j, reg):
        if 0 <= j < 16: a.mov_b_ld_disp(cdisp(j), 4, reg)
        else: a.mov_b_imm(0, reg)
    def stream(j, dst):                                         # dst = S[j] (uses r3l)
        load_c(j - 1, dst)
        for _ in range(4): a.shll_b(dst)
        load_c(j, 'r3l')
        for _ in range(4): a.shlr_b('r3l')
        a.or_b_rr('r3l', dst)
    def put(k):                                                 # LCD byte k of the row <- r3h
        a.mov_b_st_disp('r3h', k, 5)
    a.label('gfx_flush')
    a.push_l(3); a.push_l(4); a.push_l(5); a.push_l(6)
    a.mov_l_imm(FB, 4); a.mov_l_from_abs(LCD_FBPTR, 5); a.mov_w_imm(32, 14)     # e6 = rows
    a.label('gf_row')
    for g in range(6):
        stream(3 * g, 'r0l'); stream(3 * g + 1, 'r1l')
        if g < 5: stream(3 * g + 2, 'r2l')
        a.mov_b_rr('r0l', 'r3h'); a.shlr_b('r3h'); a.shlr_b('r3h'); put(4 * g)                     # s0 >> 2
        a.mov_b_rr('r0l', 'r3h'); a.and_b_imm(3, 'r3h')
        for _ in range(4): a.shll_b('r3h')
        a.mov_b_rr('r1l', 'r6h')
        for _ in range(4): a.shlr_b('r6h')
        a.or_b_rr('r6h', 'r3h'); put(4 * g + 1)                                                     # s0 & 3 << 4 | s1 >> 4
        if g == 5: break
        a.mov_b_rr('r1l', 'r3h'); a.and_b_imm(0x0F, 'r3h'); a.shll_b('r3h'); a.shll_b('r3h')
        a.mov_b_rr('r2l', 'r6h')
        for _ in range(6): a.shlr_b('r6h')
        a.or_b_rr('r6h', 'r3h'); put(4 * g + 2)                                                     # s1 & 15 << 2 | s2 >> 6
        a.mov_b_rr('r2l', 'r3h'); a.and_b_imm(0x3F, 'r3h'); put(4 * g + 3)                         # s2 & 63
    a.mov_b_imm(0, 'r3h'); put(22); put(23)
    a.adds4(4); a.add_l_imm(LCD_STRIDE, 5); a.dec_w1(14); a.bne16('gf_row')
    a.pop_l(6); a.pop_l(5); a.pop_l(4); a.pop_l(3); a.rts()

    # ---- gfx_put8 ----
    a.label('gfx_put8')
    a.push_l(2); a.push_l(3)
    a.cmp_b_imm(32, 'r1h'); a.bcc16('p8_out')
    a.mov_b_rr('r0l', 'r3h'); a.sub_b_rr('r3l', 'r3l')       # r3 = bits << 8
    a.mov_b_rr('r1l', 'r2l'); a.and_b_imm(7, 'r2l')
    a.label('p8_sh')
    a.beq('p8_shd'); a.shlr_w(3); a.dec_b('r2l'); a.bra('p8_sh')
    a.label('p8_shd')
    a.cmp_b_imm(128, 'r1l'); a.bcc16('p8_out')
    a.bsr16('p8_addr'); a.mov_b_rr('r3h', 'r0l'); a.bsr16('p8_op')
    a.mov_b_rr('r3l', 'r0l'); a.beq('p8_out')
    a.add_b_imm(8, 'r1l')
    a.cmp_b_imm(128, 'r1l'); a.bcc('p8_back')
    a.bsr16('p8_addr'); a.mov_b_rr('r3l', 'r0l'); a.bsr16('p8_op')
    a.label('p8_back'); a.add_b_imm(0x100 - 8, 'r1l')
    a.label('p8_out')
    a.pop_l(3); a.pop_l(2); a.rts()
    # er2 = byte address of (r1l, r1h)
    a.label('p8_addr')
    a.push_l(0)
    a.sub_l(2, 2); a.mov_b_rr('r1l', 'r2l')
    a.shlr_b('r2l'); a.shlr_b('r2l'); a.shlr_b('r2l')          # t = x >> 3
    a.sub_l(0, 0); a.mov_b_rr('r2l', 'r0l'); a.and_b_imm(3, 'r0l')
    a.and_b_imm(0x0C, 'r2l'); a.shll_l2(2); a.shll_l2(2); a.shll_l(2)   # (t & 12) * 32 = strip * 128
    a.add_l_rr(0, 2)
    a.sub_l(0, 0); a.mov_b_rr('r1h', 'r0l'); a.shll_l2(0)       # y * 4
    a.add_l_rr(0, 2)
    a.add_l_imm(FB, 2)
    a.pop_l(0); a.rts()
    # @er2 op= r0l by mode
    a.label('p8_op')
    a.mov_b_ld(2, 'r0h')
    a.btst_abs(1, GMODE); a.bne('po_inv')
    a.btst_abs(0, GMODE); a.bne('po_clr')
    a.or_b_rr('r0l', 'r0h'); a.bra('po_st')
    a.label('po_clr'); a.not_b('r0l'); a.and_b_rr('r0l', 'r0h'); a.bra('po_st')
    a.label('po_inv'); a.xor_b_rr('r0l', 'r0h')
    a.label('po_st'); a.mov_b_st('r0h', 2)
    a.rts()

    # ---- gfx_fill ----
    a.label('gfx_fill')
    a.push_l(3); a.push_l(4); a.push_l(5)
    a.mov_b_rr('r1l', 'r3l'); a.mov_b_rr('r1h', 'r3h'); a.mov_b_rr('r2l', 'r4l'); a.mov_b_rr('r2h', 'r4h')
    a.label('gfl_row')
    a.mov_b_rr('r4h', 'r4h'); a.beq16('gfl_done')
    a.mov_b_rr('r3l', 'r1l'); a.mov_b_rr('r3h', 'r1h'); a.mov_b_rr('r4l', 'r5l')
    a.label('gfl_chunk')
    a.mov_b_rr('r5l', 'r5l'); a.beq('gfl_next')
    a.mov_b_rr('r5l', 'r0l'); a.cmp_b_imm(8, 'r0l'); a.bcs('gfl_lt'); a.mov_b_imm(8, 'r0l')
    a.label('gfl_lt')
    a.mov_l_imm('gfx_masks', 2); a.extu_w(0); a.extu_l(0); a.add_l_rr(0, 2); a.mov_b_ld(2, 'r0l')
    a.bsr16('gfx_put8')
    a.cmp_b_imm(9, 'r5l'); a.bcs('gfl_next')
    a.add_b_imm(8, 'r1l'); a.add_b_imm(0x100 - 8, 'r5l'); a.bra('gfl_chunk')
    a.label('gfl_next')
    a.inc_b('r3h'); a.dec_b('r4h'); a.bra('gfl_row')
    a.label('gfl_done')
    a.pop_l(5); a.pop_l(4); a.pop_l(3); a.rts()

    # ---- gfx_text ----
    a.label('gfx_text')
    a.push_l(3); a.push_l(4); a.push_l(5); a.push_l(6)
    a.mov_l_rr(0, 5); a.mov_l_rr(2, 4)
    a.mov_b_rr('r1l', 'r6l'); a.mov_b_rr('r1h', 'r6h')
    a.label('gt_next')
    a.mov_b_ldinc(5, 'r0l'); a.beq16('gt_done')
    a.mov_b_ld_disp(2, 4, 'r1l'); a.cmp_b_rr('r1l', 'r0l'); a.bhi('gt_unk')     # ch > last
    a.mov_b_ld_disp(1, 4, 'r1l'); a.sub_b_rr('r1l', 'r0l'); a.bcc('gt_have')    # idx = ch - first
    a.label('gt_unk'); a.mov_b_imm(0, 'r0l')
    a.label('gt_have')
    a.mov_b_ld(4, 'r1l'); a.inc_b('r1l'); a.mulxu_b('r1l', 0)                    # idx * (height + 1)
    a.extu_l(0); a.add_l_rr(4, 0); a.adds4(0)
    a.mov_l_rr(0, 2); a.mov_l_rr(0, 3); a.adds1(3)                             # er2 = glyph, er3 = rows
    a.mov_b_ld(4, 'r0l'); a.extu_w(0); a.mov_w_rr(0, 14)                        # e6 = rows to draw
    a.mov_b_rr('r6h', 'r1h')
    a.label('gt_row')
    a.mov_b_ldinc(3, 'r0l'); a.mov_b_rr('r6l', 'r1l'); a.bsr16('gfx_put8')
    a.inc_b('r1h'); a.dec_w1(14); a.bne('gt_row')
    a.mov_b_ld(2, 'r0l'); a.add_b_rr('r0l', 'r6l')                              # x += advance
    a.bra16('gt_next')
    a.label('gt_done')
    a.mov_b_rr('r6l', 'r1l')
    a.pop_l(6); a.pop_l(5); a.pop_l(4); a.pop_l(3); a.rts()

    # ---- gfx_bitmap ----
    a.label('gfx_bitmap')
    a.push_l(3); a.push_l(4); a.push_l(5)
    a.mov_l_rr(0, 3)
    a.mov_b_ldinc(3, 'r4l'); a.mov_b_ldinc(3, 'r4h')                            # w, h
    a.mov_b_rr('r4l', 'r5h'); a.add_b_imm(7, 'r5h')
    a.shlr_b('r5h'); a.shlr_b('r5h'); a.shlr_b('r5h')                           # bytes per row
    a.mov_b_rr('r1l', 'r5l')
    a.label('gb_row')
    a.mov_b_rr('r4h', 'r4h'); a.beq('gb_done')
    a.mov_b_rr('r5l', 'r1l'); a.mov_b_rr('r5h', 'r2l')
    a.label('gb_byte')
    a.mov_b_ldinc(3, 'r0l'); a.bsr16('gfx_put8'); a.add_b_imm(8, 'r1l')
    a.dec_b('r2l'); a.bne('gb_byte')
    a.inc_b('r1h'); a.dec_b('r4h'); a.bra('gb_row')
    a.label('gb_done')
    a.pop_l(5); a.pop_l(4); a.pop_l(3); a.rts()

    # ---- gfx_patrow: OR the first r2l px (from x 0) of a 16-byte row pattern @er0 into row r1h ----
    a.label('gfx_patrow')
    a.push_l(3); a.push_l(4); a.push_l(5)
    a.mov_l_rr(0, 3)
    a.sub_l(4, 4); a.mov_b_rr('r1h', 'r4l'); a.shll_l2(4); a.add_l_imm(FB, 4)      # er4 = FB + y * 4
    a.mov_b_imm(16, 'r5h'); a.mov_b_rr('r2l', 'r5l')
    a.label('pr_byte')
    a.mov_b_rr('r5l', 'r5l'); a.beq('pr_done')
    a.mov_b_ldinc(3, 'r0l')
    a.cmp_b_imm(8, 'r5l'); a.bcc('pr_full')
    a.sub_l(1, 1); a.mov_b_rr('r5l', 'r1l'); a.mov_l_imm('gfx_masks', 2); a.add_l_rr(1, 2)
    a.mov_b_ld(2, 'r1l'); a.and_b_rr('r1l', 'r0l'); a.mov_b_imm(0, 'r5l'); a.bra('pr_st')
    a.label('pr_full'); a.add_b_imm(0x100 - 8, 'r5l')
    a.label('pr_st')
    a.mov_b_ld(4, 'r1l'); a.or_b_rr('r0l', 'r1l'); a.mov_b_st('r1l', 4)
    a.adds1(4); a.dec_b('r5h'); a.beq('pr_done')
    a.mov_b_rr('r5h', 'r1l'); a.and_b_imm(3, 'r1l'); a.bne('pr_byte')
    a.add_l_imm(124, 4); a.bra('pr_byte')                                          # next 32 px strip
    a.label('pr_done')
    a.pop_l(5); a.pop_l(4); a.pop_l(3); a.rts()

    # ---- gfx_vline: set pixels (r1l, r1h .. r1h + r2h - 1) ----
    a.label('gfx_vline')
    a.push_l(3)
    a.mov_b_rr('r2h', 'r3h'); a.beq('vl_done')
    a.bsr16('p8_addr')                                                             # er2 = byte of (x, y)
    a.mov_b_rr('r1l', 'r0h'); a.and_b_imm(7, 'r0h'); a.mov_b_imm(0x80, 'r3l')
    a.label('vl_sh')
    a.mov_b_rr('r0h', 'r0h'); a.beq('vl_row'); a.shlr_b('r3l'); a.dec_b('r0h'); a.bra('vl_sh')
    a.label('vl_row')
    a.mov_b_ld(2, 'r0l'); a.or_b_rr('r3l', 'r0l'); a.mov_b_st('r0l', 2)
    a.adds4(2); a.dec_b('r3h'); a.bne('vl_row')
    a.label('vl_done')
    a.pop_l(3); a.rts()

    # ---- data ----
    a.label('gfx_masks'); a.raw(bytes([0x00, 0x80, 0xC0, 0xE0, 0xF0, 0xF8, 0xFC, 0xFE, 0xFF]))
    for name, data in (('font_tiny', font_tiny()), ('font_57', font_57()), ('font_big', font_big())):
        a.label(name); a.raw(data)
    for name, rows in ui_gfx.ICONS.items():
        a.label('icon_' + name); a.raw(bitmap(rows))
    a.label('icon_recdot'); a.raw(bitmap(ui_gfx.REC_DOT))
    a.label('icon_recring'); a.raw(bitmap(ui_gfx.REC_RING))
    a.align2()


class Draw:
    """macros that emit calls into the engine (screen code is written with these)"""
    def __init__(self, a, GMODE):
        self.a, self.GMODE = a, GMODE
    def mode(self, m):
        self.a.mov_b_imm(m, 'r0l'); self.a.mov_b_to_abs('r0l', self.GMODE)
    def text(self, x, y, s, font='font_57'):
        """s = label of a string (or RAM address)"""
        a = self.a
        a.mov_l_imm(s, 0); a.mov_b_imm(x, 'r1l'); a.mov_b_imm(y, 'r1h'); a.mov_l_imm(font, 2)
        a.bsr16('gfx_text')
    def text_at_r1(self, s, font='font_57'):
        """text at the x/y already in r1"""
        a = self.a
        a.mov_l_imm(s, 0); a.mov_l_imm(font, 2); a.bsr16('gfx_text')
    def fill(self, x, y, w, h, m=M_SET):
        a = self.a
        if m != M_SET: self.mode(m)
        a.mov_b_imm(x, 'r1l'); a.mov_b_imm(y, 'r1h'); a.mov_b_imm(w, 'r2l'); a.mov_b_imm(h, 'r2h')
        a.bsr16('gfx_fill')
        if m != M_SET: self.mode(M_SET)
    def frame(self, x, y, w, h):
        self.fill(x, y, w, 1); self.fill(x, y + h - 1, w, 1); self.fill(x, y, 1, h); self.fill(x + w - 1, y, 1, h)
    def bitmap(self, x, y, lbl):
        a = self.a
        a.mov_l_imm(lbl, 0); a.mov_b_imm(x, 'r1l'); a.mov_b_imm(y, 'r1h'); a.bsr16('gfx_bitmap')
    def popup(self, msg_lbl, nchars):
        """centred message box over the page (5x7 text)"""
        w = 6 * nchars + 7
        x0 = 64 - w // 2
        self.fill(x0, 8, w, 15, M_CLR)
        self.frame(x0, 8, w, 15); self.frame(x0 + 1, 9, w - 2, 13)
        self.text(x0 + 4, 12, msg_lbl)
