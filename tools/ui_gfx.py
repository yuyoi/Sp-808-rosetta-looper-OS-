"""JSW UI graphics: fonts, icons and screen mockups for our own 128x32 LCD interface.

The same tables become firmware data later (gfx engine: RAM framebuffer, 4 strips of 32x32 px, blit API 0x400478,
drawn at LCD x = 2..129 like the boot animation).

usage: python -I ui_gfx.py mock out.png      # render the screen mockups (4x, LCD colours) for review
"""
import sys
from PIL import Image, ImageDraw

W, H = 128, 32

# ---------------- fonts ----------------
# tiny 3x5 (advance 4): labels, help lines. Rows top -> bottom, 3 bits each, MSB = left.
TINY_SRC = {
    'A': '010 101 111 101 101', 'B': '110 101 110 101 110', 'C': '011 100 100 100 011', 'D': '110 101 101 101 110',
    'E': '111 100 110 100 111', 'F': '111 100 110 100 100', 'G': '011 100 101 101 011', 'H': '101 101 111 101 101',
    'I': '111 010 010 010 111', 'J': '001 001 001 101 010', 'K': '101 101 110 101 101', 'L': '100 100 100 100 111',
    'M': '101 111 111 101 101', 'N': '110 101 101 101 101', 'O': '010 101 101 101 010', 'P': '110 101 110 100 100',
    'Q': '010 101 101 110 011', 'R': '110 101 110 101 101', 'S': '011 100 010 001 110', 'T': '111 010 010 010 010',
    'U': '101 101 101 101 111', 'V': '101 101 101 101 010', 'W': '101 101 111 111 101', 'X': '101 101 010 101 101',
    'Y': '101 101 010 010 010', 'Z': '111 001 010 100 111',
    '0': '111 101 101 101 111', '1': '010 110 010 010 111', '2': '110 001 010 100 111', '3': '110 001 010 001 110',
    '4': '101 101 111 001 001', '5': '111 100 110 001 110', '6': '011 100 110 101 010', '7': '111 001 010 010 010',
    '8': '010 101 010 101 010', '9': '010 101 011 001 110',
    ' ': '000 000 000 000 000', ':': '000 010 000 010 000', '.': '000 000 000 000 010', '-': '000 000 111 000 000',
    '=': '000 111 000 111 000', '/': '001 001 010 100 100', '+': '000 010 111 010 000', '>': '100 010 001 010 100',
    '<': '001 010 100 010 001', '!': '010 010 010 000 010', '?': '110 001 010 000 010', '(': '001 010 010 010 001',
    ')': '100 010 010 010 100', '%': '101 001 010 100 101', '#': '101 111 101 111 101', ',': '000 000 000 010 100',
    "'": '010 010 000 000 000', '_': '000 000 000 000 111', '*': '000 101 010 101 000',
}
TINY = {c: [int(r, 2) for r in s.split()] for c, s in TINY_SRC.items()}

# main 5x7 (advance 6), classic LCD font, columns LSB = top row
F57_SRC = {
    ' ': '0000000000', '!': '00005f0000', '"': '0007000700', '#': '147f147f14', '%': '2313086462', "'": '0005030000',
    '(': '001c224100', ')': '0041221c00', '*': '14083e0814', '+': '08083e0808', ',': '0050300000', '-': '0808080808',
    '.': '0060600000', '/': '2010080402', ':': '0036360000', '<': '0814224100', '=': '1414141414', '>': '0041221408',
    '?': '0201510906', '_': '4040404040',
    '0': '3e5149453e', '1': '00427f4000', '2': '4261514946', '3': '2141454b31', '4': '1814127f10', '5': '2745454539',
    '6': '3c4a494930', '7': '0171090503', '8': '3649494936', '9': '064949291e',
    'A': '7e1111117e', 'B': '7f49494936', 'C': '3e41414122', 'D': '7f4141221c', 'E': '7f49494941', 'F': '7f09090901',
    'G': '3e4149497a', 'H': '7f0808087f', 'I': '00417f4100', 'J': '2040413f01', 'K': '7f08142241', 'L': '7f40404040',
    'M': '7f020c027f', 'N': '7f0408107f', 'O': '3e4141413e', 'P': '7f09090906', 'Q': '3e4151215e', 'R': '7f09192946',
    'S': '4649494931', 'T': '01017f0101', 'U': '3f4040403f', 'V': '1f2040201f', 'W': '3f4038403f', 'X': '6314081463',
    'Y': '0708700807', 'Z': '6151494543',
    'a': '2054545478', 'b': '7f48444438', 'c': '3844444420', 'd': '384444487f', 'e': '3854545418', 'f': '087e090102',
    'g': '0c5252523e', 'h': '7f08040478', 'i': '00447d4000', 'j': '2040443d00', 'k': '7f10284400', 'l': '00417f4000',
    'm': '7c04180478', 'n': '7c08040478', 'o': '3844444438', 'p': '7c14141408', 'q': '081414187c', 'r': '7c08040408',
    's': '4854545420', 't': '043f444020', 'u': '3c4040207c', 'v': '1c2040201c', 'w': '3c4030403c', 'x': '4428102844',
    'y': '0c5050503c', 'z': '4464544c44',
}
F57 = {c: [int(s[i:i + 2], 16) for i in range(0, 10, 2)] for c, s in F57_SRC.items()}

# big 7-segment digits 7x11, stroke 2 (advance 9): time and counters
SEGS = {'0': 'abcdef', '1': 'bc', '2': 'abdeg', '3': 'abcdg', '4': 'bcfg', '5': 'acdfg', '6': 'acdefg', '7': 'abc',
        '8': 'abcdefg', '9': 'abcdfg', '-': 'g', ' ': ''}
BIG_W, BIG_H = 7, 11


def big_digit(ch):
    g = [[0] * BIG_W for _ in range(BIG_H)]
    def box(x0, y0, x1, y1):
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1): g[y][x] = 1
    s = SEGS[ch]
    if 'a' in s: box(1, 0, 5, 1)
    if 'g' in s: box(1, 5, 5, 5)
    if 'd' in s: box(1, 9, 5, 10)
    if 'f' in s: box(0, 1, 1, 5)
    if 'b' in s: box(5, 1, 6, 5)
    if 'e' in s: box(0, 5, 1, 9)
    if 'c' in s: box(5, 5, 6, 9)
    return g


# ---------------- icons (home tiles, 15x13) ----------------
ICONS = {
    'mpc': [
        '...............',
        '.XXX.XXX.XXX...',
        '.X.X.X.X.X.X...',
        '.XXX.XXX.XXX...',
        '...............',
        '.XXX.XXX.XXX...',
        '.X.X.XXX.X.X...',
        '.XXX.XXX.XXX...',
        '...............',
        '.XXX.XXX.XXX...',
        '.X.X.X.X.X.X...',
        '.XXX.XXX.XXX...',
        '...............'],
    'loop': [
        '..........X....',
        '..........XX...',
        '.XXXXXXXXXXXX..',
        'X.........XX..X',
        'X.........X...X',
        'X.............X',
        'X.............X',
        'X.............X',
        'X...X.........X',
        'X..XX.........X',
        '..XXXXXXXXXXXX.',
        '...XX..........',
        '....X..........'],
    'keys': [
        'XXXXXXXXXXXXXXX',
        'X.XX.XX.X.XX.XX',
        'X.XX.XX.X.XX.XX',
        'X.XX.XX.X.XX.XX',
        'X.XX.XX.X.XX.XX',
        'X.XX.XX.X.XX.XX',
        'X..X..X.X..X..X',
        'X..X..X.X..X..X',
        'X..X..X.X..X..X',
        'X..X..X.X..X..X',
        'X..X..X.X..X..X',
        'X..X..X.X..X..X',
        'XXXXXXXXXXXXXXX'],
    'edit': [                     # S-EDIT: a waveform with the edit line through it
        '.........XXX...',
        '....X.....X....',
        '....X...X.X....',
        '..X.X...X.X.X..',
        '..X.X.X.X.X.X..',
        'X.X.X.X.X.X.X.X',
        'X.X.X.X.X.X.X.X',
        'X.X.X.X.X.X.X.X',
        '..X.X.X.X.X.X..',
        '..X.X...X.X.X..',
        '....X...X.X....',
        '....X.....X....',
        '.........XXX...'],
    'dds': [                      # DDS-DSP: a saw over a pulse
        '...............',
        '....XX...XX...X',
        '...X.X..X.X..X.',
        '..X..X.X..X.X..',
        '.X...XX...XX...',
        'X....X....X....',
        '...............',
        'XXXXX...XXXXX..',
        '....X...X...X..',
        '....X...X...X..',
        '....X...X...X..',
        '....X...X...X..',
        '....XXXXX...XXX'],
    'route': [                    # ROUTING: two sources into a mix node, one out
        'XXXXX.....XXXXX',
        'X...X.....X...X',
        'X...XXXXXXX...X',
        'X...X.....X...X',
        'XXXXX.....XXXXX',
        '..X.........X..',
        '..X.........X..',
        '..X...XXX...X..',
        '..XXXXX.XXXXX..',
        '......XXX......',
        '.......X.......',
        '.......X.......',
        '.....XXXXX.....'],
    'lab': [                      # LAB: a flask
        '....XXXXXXX....',
        '.....X...X.....',
        '.....X...X.....',
        '.....X...X.....',
        '.....X...X.....',
        '....X.....X....',
        '...X.......X...',
        '..X..X.X....X..',
        '.X..XXXXXX...X.',
        'X..XXXXXXXXX..X',
        'X.XXXXXXXXXXX.X',
        'X.............X',
        '.XXXXXXXXXXXXX.'],
    'sys': [
        '......XXX......',
        '..XX..X.X..XX..',
        '..X.XXX.XXX.X..',
        '...X.......X...',
        '.XX...XXX...XX.',
        '.X...X...X...X.',
        '.X...X...X...X.',
        '.X...X...X...X.',
        '.XX...XXX...XX.',
        '...X.......X...',
        '..X.XXX.XXX.X..',
        '..XX..X.X..XX..',
        '......XXX......'],
}
REC_DOT = ['..XXX..', '.XXXXX.', 'XXXXXXX', 'XXXXXXX', 'XXXXXXX', '.XXXXX.', '..XXX..']
REC_RING = ['..XXX..', '.X...X.', 'X.....X', 'X.....X', 'X.....X', '.X...X.', '..XXX..']


# ---------------- canvas ----------------
class Canvas:
    def __init__(self): self.px = [[0] * W for _ in range(H)]
    def set(self, x, y, v=1):
        if 0 <= x < W and 0 <= y < H: self.px[y][x] = v
    def inv(self, x0, y0, w, h):
        for y in range(y0, y0 + h):
            for x in range(x0, x0 + w):
                if 0 <= x < W and 0 <= y < H: self.px[y][x] ^= 1
    def fill(self, x0, y0, w, h, v=1):
        for y in range(y0, y0 + h):
            for x in range(x0, x0 + w): self.set(x, y, v)
    def rect(self, x0, y0, w, h):
        for x in range(x0, x0 + w): self.set(x, y0); self.set(x, y0 + h - 1)
        for y in range(y0, y0 + h): self.set(x0, y); self.set(x0 + w - 1, y)
    def bitmap(self, x0, y0, rows):
        for y, r in enumerate(rows):
            for x, c in enumerate(r):
                if c == 'X': self.set(x0 + x, y0 + y)
    def tiny(self, x0, y0, s, v=1):
        x = x0
        for ch in s.upper():
            for r, bits in enumerate(TINY.get(ch, TINY['?'])):
                for i in range(3):
                    if bits & (4 >> i): self.set(x + i, y0 + r, v)
            x += 4
        return x
    def text(self, x0, y0, s, v=1):
        x = x0
        for ch in s:
            for i, col in enumerate(F57.get(ch, F57['?'])):
                for r in range(7):
                    if col & (1 << r): self.set(x + i, y0 + r, v)
            x += 6
        return x
    def big(self, x0, y0, s):
        x = x0
        for ch in s:
            if ch == ':':
                self.fill(x, y0 + 2, 2, 2); self.fill(x, y0 + 7, 2, 2); x += 4
            elif ch == '.':
                self.fill(x, y0 + 9, 2, 2); x += 4
            else:
                g = big_digit(ch)
                for yy in range(BIG_H):
                    for xx in range(BIG_W):
                        if g[yy][xx]: self.set(x + xx, y0 + yy)
                x += BIG_W + 2
        return x
    def tiny_w(self, s): return 4 * len(s) - 1
    def meter(self, x0, y0, w, h, level, peak):
        """segmented bar: 2px segments, 1px gaps; level/peak 0..1"""
        n = (w + 1) // 3
        for i in range(n):
            x = x0 + 3 * i
            if i < int(level * n): self.fill(x, y0, 2, h)
            else: self.set(x, y0 + h - 1); self.set(x + 1, y0 + h - 1)
        p = x0 + 3 * min(n - 1, int(peak * n))
        self.fill(p, y0 - 1, 2, h + 1)


# ---------------- screens ----------------
def pad_grid(c, x0, y0, used, sel, cell=6, gap=1):
    """4x4 pads, pad 1 bottom-left (MPC style). used = set of pads 1-16, sel = selected pad"""
    for p in range(1, 17):
        col, row = (p - 1) % 4, 3 - (p - 1) // 4
        x, y = x0 + col * (cell + gap), y0 + row * (cell + gap)
        if p in used: c.fill(x, y, cell, cell)
        else: c.rect(x, y, cell, cell)
        if p == sel:
            c.inv(x + 1, y + 1, cell - 2, cell - 2)
            c.rect(x - 1, y - 1, cell + 2, cell + 2)


def scr_home(sel=0):
    c = Canvas()
    tiles = [('mpc', 'MPC'), ('loop', 'LOOP'), ('keys', 'KEYS'), ('sys', 'SYS')]
    for i, (ic, label) in enumerate(tiles):
        x = i * 32
        c.bitmap(x + 8, 2, ICONS[ic])
        c.tiny(x + 16 - c.tiny_w(label) // 2, 22, label)
        if i == sel:                                      # frame the tile, invert its label
            c.rect(x + 1, 0, 30, 32)
            c.inv(x + 2, 20, 28, 9)
    return c


def scr_mpc(row=0, pad=5, used=(1, 2, 3, 4, 5, 6, 7, 9, 10, 13), mode='CLASSIC', start='INSTANT'):
    c = Canvas()
    rows = [('PAD', '%02d %s' % (pad, 'USED' if pad in used else 'EMPTY')), ('REC', mode), ('START', start)]
    for i, (k, v) in enumerate(rows):
        y = i * 8
        c.text(1, y + 1, k); c.text(37, y + 1, v)
        if i == row: c.inv(0, y, 93, 9)
    c.fill(0, 26, 13, 6); c.tiny(1, 27, 'MPC', 0)
    c.tiny(16, 27, 'ENTER/SAMPLE=REC')
    pad_grid(c, 99, 1, set(used), pad)
    return c


def scr_rec(t='00:03.2', level=0.62, peak=0.81, pad=5, waiting=False, blink=True):
    c = Canvas()
    if waiting:
        c.bitmap(1, 1, REC_RING); c.text(11, 1, 'WAIT')
        c.tiny(1, 10, 'PLAY TO START')
    else:
        if blink: c.bitmap(1, 1, REC_DOT)
        c.text(11, 1, 'REC')
        c.tiny(1, 10, 'PAD %02d' % pad)
    c.big(127 - 55, 1, t)
    c.meter(1, 18, 126, 5, level, peak)
    c.tiny(1, 26, 'PAD=STOP  EXIT=CANCEL')
    return c


def scr_done(secs='3.2', pad=5):
    c = Canvas()
    c.text(1, 1, 'TAKE'); c.big(30, 0, secs); c.tiny(30 + 22, 6, 'S')
    c.text(72, 1, '>'); c.fill(80, 0, 47, 9); c.text(82, 1, 'PAD %02d' % pad, 0)
    import math
    for x in range(128):                                     # waveform overview (envelope)
        a = abs(math.sin(x * 0.37) * math.exp(-x / 70.0)) * 0.8 + 0.1 * abs(math.sin(x * 1.7))
        h = max(1, int(a * 6))
        for y in range(17 - h, 17 + h): c.set(x, y)
    c.tiny(1, 26, 'ENTER=KEEP PAD=MOVE EXIT=CANCEL')
    return c


def scr_toast(msg='TAKE CANCELED'):
    c = scr_mpc(row=1)
    w = 6 * len(msg) + 6
    x0 = 64 - w // 2
    c.fill(x0, 9, w, 13, 0); c.rect(x0, 9, w, 13); c.rect(x0 + 1, 10, w - 2, 11)
    c.text(x0 + 3, 12, msg)
    return c


def render(screens, path, scale=4, cols=2):
    bg, on, frame = (178, 196, 150), (28, 40, 26), (60, 66, 56)
    pad = 12
    tw, th = W * scale, H * scale
    rows = (len(screens) + cols - 1) // cols
    img = Image.new('RGB', (cols * (tw + pad) + pad, rows * (th + pad + 14) + pad), (34, 34, 38))
    d = ImageDraw.Draw(img)
    for i, (name, c) in enumerate(screens):
        ox, oy = pad + (i % cols) * (tw + pad), pad + (i // cols) * (th + pad + 14)
        d.text((ox, oy), name, fill=(220, 220, 220))
        oy += 14
        d.rectangle((ox - 3, oy - 3, ox + tw + 2, oy + th + 2), outline=frame, width=3)
        d.rectangle((ox, oy, ox + tw - 1, oy + th - 1), fill=bg)
        for y in range(H):
            for x in range(W):
                if c.px[y][x]:
                    d.rectangle((ox + x * scale, oy + y * scale, ox + x * scale + scale - 2, oy + y * scale + scale - 2),
                                fill=on)
    img.save(path)
    return path


def mock(path):
    screens = [('1 HOME (dial/arrows move, ENTER opens)', scr_home(1)),
               ('2 MPC page (pad 1 = bottom left, selected pad blinks)', scr_mpc()),
               ('3 RECORDING', scr_rec()),
               ('4 WAITING FOR SIGNAL', scr_rec(waiting=True, level=0.08, peak=0.12, t='00:00.0')),
               ('5 TAKE DONE (waveform)', scr_done()),
               ('6 CANCELED (pop-up over MPC)', scr_toast())]
    print(render(screens, path))


if __name__ == '__main__':
    if sys.argv[1] == 'mock': mock(sys.argv[2])
