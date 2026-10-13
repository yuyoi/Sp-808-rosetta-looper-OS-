"""JSW graphics engine for the SP-808 LCD: H8S routines (via h8asm) + font/icon data (from ui_gfx).

Framebuffer FB (RAM, 512 bytes) = 4 strips x 32 rows x 4 bytes. Pixel (x, y), x 0-127, y 0-31, 1 = dark:
    byte FB + (x >> 5) * 128 + y * 4 + ((x >> 3) & 3), bit 7 - (x & 7)
gfx_flush converts FB into 6 strips of 24 px (STG, 768 bytes) and blits them with boot API 0x400478 at
LCD x = 0, 24 .. 120, so the canvas sits at LCD x 4-131 (see the comment at gfx_flush for why 24).

Routines (preserve er3-er6; er0-er2 are scratch unless noted):
  gfx_clear()                            FB = 0
  gfx_flush()                            FB -> LCD
  gfx_put8(r0l bits, r1l x, r1h y)       8 pixels, MSB at x, mode @GMODE (0 set, 1 clear, 2 invert). Keeps r1, er2.
  gfx_fill(r1l x, r1h y, r2l w, r2h h)   rectangle, mode @GMODE
  gfx_text(er0 str, r1l x, r1h y, er2 font) -> r1l = x after the text
  gfx_bitmap(er0 bmp, r1l x, r1h y)      bmp = w, h, then rows of (w + 7) / 8 bytes (MSB = left)
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

    # ---- gfx_flush: FB (4 x 32 px strips) -> STG (6 x 24 px strips at LCD x 0, 24 .. 120, canvas at LCD x 4) ----
    # On hardware (v0.7/v0.7b photos): a 32 px wide blit shears (the boot ROM uses a longer row for that width),
    # and strips at x not on a byte boundary lose 1-2 columns at the seams. 24 px strips at x = 24*s: 4-byte rows,
    # every seam on a multiple of 6 and of 8.
    a.label('gfx_flush')
    a.push_l(3); a.push_l(4); a.push_l(5); a.push_l(6)
    a.mov_l_imm(FB, 4); a.mov_l_imm(STG, 5); a.mov_w_imm(32, 6)
    a.label('gf_row')                                         # L0..L3 = canvas x 0-31, 32-63, 64-95, 96-127
    a.mov_l_ld_disp(0, 4, 0); a.mov_l_rr(0, 1); a.shr32(1, 4); a.mov_l_st_disp(1, 0, 5)                  # W0 = L0 >> 4
    a.shl32(0, 20); a.mov_l_ld_disp(128, 4, 2); a.mov_l_rr(2, 3); a.shr32(3, 12)
    a.add_l_rr(3, 0); a.mov_l_st_disp(0, 128, 5)                                                        # W1 = L0<<20 | L1>>12
    a.mov_l_rr(2, 0); a.shl32(0, 12); a.mov_l_ld_disp(256, 4, 2); a.mov_l_rr(2, 3); a.shr32(3, 20)
    a.add_l_rr(3, 0); a.mov_l_st_disp(0, 256, 5)                                                        # W2 = L1<<12 | L2>>20
    a.mov_l_rr(2, 0); a.shl32(0, 4); a.mov_l_st_disp(0, 384, 5)                                          # W3 = L2<<4
    a.mov_l_rr(2, 0); a.shl32(0, 28); a.mov_l_ld_disp(384, 4, 1); a.mov_l_rr(1, 3); a.shr32(3, 4)
    a.add_l_rr(3, 0); a.mov_l_st_disp(0, 512, 5)                                                        # W4 = L2<<28 | L3>>4
    a.mov_l_rr(1, 0); a.shl32(0, 20); a.mov_l_st_disp(0, 640, 5)                                         # W5 = L3<<20
    a.adds4(4); a.adds4(5); a.dec_w1(6); a.bne16('gf_row')
    a.mov_l_imm(STG, 4); a.mov_l_imm(BLIT, 5); a.mov_b_imm(0, 'r6l')
    a.label('gf_blit')
    a.sub_l(0, 0); a.push_l(0)                    # stack arg 0, as stock
    a.mov_l_rr(4, 1)
    a.mov_w_imm((24 << 8) | 32, 8)                # e0 = width 24, rows 32
    a.mov_b_imm(0, 'r0h'); a.mov_b_rr('r6l', 'r0l')
    a.jsr_ind(5)
    a.adds4(7)
    a.add_l_imm(128, 4); a.add_b_imm(24, 'r6l')
    a.cmp_b_imm(6 * 24, 'r6l'); a.bne('gf_blit')
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
