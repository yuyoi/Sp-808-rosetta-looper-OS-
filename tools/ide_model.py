"""A CompactFlash card in True-IDE mode behind a passive CF-to-IDE adapter (e.g. StarTech 35BAYCF2IDE), on the SP-808's
IDE port, for the H8S emulator. The card looks like a plain ATA hard disk (signature 00/00 after reset, IDENTIFY with
the CFA word 0 = 848Ah), backed by a disk image. Card behaviour comes from a profile, so different cards can be tested.

SP-808 wiring (from the boot ROM driver): task-file registers at 0x600000 + 2 * reg on the HIGH byte of a 16-bit bus
(the ROM byte-swaps before word writes, reads them with mov.b at the even address); the data register 0x600000 is read
and written as 16-bit words; device control / alternate status at 0x60001C.

    card = CFCard(bytearray(open('disk.img', 'rb').read()), PROFILES['generic-2gb'])
    emu = IdeEmu(image, card)
"""
import struct
import h8emu

IDE_LO, IDE_HI = 0x600000, 0x600020

PROFILES = {                                    # name -> card behaviour (fill from the real card labels / IDENTIFY)
    'generic-2gb': dict(model='GENERIC CF 2GB', serial='ROSETTA0001', fw='1.0', heads=16, spt=63, pio=4, multi=1,
                        lba=True),
    'old-512mb': dict(model='OLD CF 512MB', serial='ROSETTA0002', fw='0.9', heads=16, spt=32, pio=2, multi=1,
                      lba=True),
}


class CFCard:
    def __init__(self, image, profile):
        self.img, self.p = image, dict(profile)
        self.sectors = len(image) // 512
        self.heads, self.spt = self.p['heads'], self.p['spt']        # logical geometry (INITIALIZE DEVICE PARAMS)
        self.cyls = min(65535, self.sectors // (self.heads * self.spt))
        self.multi = 0                                               # SET MULTIPLE count (0 = off)
        self.log = []                                                # (command, lba, count) for the tests
        self.reset()

    # ---- registers ----
    def reset(self):
        self.err, self.feat = 1, 0
        self.count, self.sector, self.cyl_lo, self.cyl_hi, self.dev = 1, 1, 0, 0, 0xA0
        self.status = 0x50                                           # DRDY | DSC, ATA signature 00/00
        self.buf, self.pos, self.dir, self.pend = b'', 0, None, None
        self.irq = False                                             # INTRQ (IRQ2 on the SP-808)
    def read_reg(self, r):
        return [None, self.err, self.count, self.sector, self.cyl_lo, self.cyl_hi, self.dev, self.status][r]
    def write_reg(self, r, v):
        v &= 0xFF
        if r == 1: self.feat = v
        elif r == 2: self.count = v
        elif r == 3: self.sector = v
        elif r == 4: self.cyl_lo = v
        elif r == 5: self.cyl_hi = v
        elif r == 6: self.dev = v
        elif r == 7: self.command(v)
    def devctl(self, v):
        if v & 0x04: self.reset()                                    # SRST

    # ---- addressing ----
    def lba(self):
        if self.dev & 0x40:                                          # LBA mode
            return ((self.dev & 0x0F) << 24) | (self.cyl_hi << 16) | (self.cyl_lo << 8) | self.sector
        c, h, s = (self.cyl_hi << 8) | self.cyl_lo, self.dev & 0x0F, self.sector
        return (c * self.heads + h) * self.spt + (s - 1)
    def nsec(self): return self.count or 256

    # ---- commands ----
    def ok(self): self.status, self.err, self.irq = 0x50, 0, True
    def abort(self): self.status, self.err, self.irq = 0x51, 0x04, True
    def command(self, c):
        self.log.append((c, self.lba(), self.nsec()))
        if c == 0xEC: self.buf, self.pos, self.dir = self.identify(), 0, 'in'; self.status, self.irq = 0x58, True; return
        if c == 0x91:                                                # INITIALIZE DEVICE PARAMETERS
            self.heads, self.spt = (self.dev & 0x0F) + 1, self.count or 256
            self.cyls = min(65535, self.sectors // (self.heads * self.spt)); self.ok(); return
        if c in (0x20, 0x21, 0xC4):                                  # READ SECTORS / MULTIPLE
            a, n = self.lba(), self.nsec()
            if a + n > self.sectors: self.status, self.err = 0x51, 0x10; return
            self.buf, self.pos, self.dir = bytes(self.img[a * 512:(a + n) * 512]), 0, 'in'; self.status, self.irq = 0x58, True; return
        if c in (0x30, 0x31, 0xC5):                                  # WRITE SECTORS / MULTIPLE
            a, n = self.lba(), self.nsec()
            if a + n > self.sectors: self.status, self.err = 0x51, 0x10; return
            self.buf, self.pos, self.dir, self.pend = bytearray(n * 512), 0, 'out', a; self.status = 0x58; return
        if c == 0xC6:                                                # SET MULTIPLE MODE
            if self.count and self.count <= self.p['multi']: self.multi = self.count; self.ok()
            else: self.abort()
            return
        if c in (0xE5, 0x98): self.count = 0xFF; self.ok(); return       # CHECK POWER MODE: FFh = active / idle
        if c in (0xEF, 0x10, 0x70, 0x40, 0x41, 0xE0, 0xE1, 0xE2, 0xE3, 0xE6, 0xE7): self.ok(); return
        self.abort()                                                 # unknown (e.g. ATAPI PACKET 0xA0 / 0xA1)
    def identify(self):
        w = [0] * 256
        w[0] = 0x848A                                                # CFA signature (removable, CF)
        w[1], w[3], w[6] = self.cyls, self.heads, self.spt
        def text(s, n): s = s.ljust(2 * n)[:2 * n]; return [(ord(s[2 * i]) << 8) | ord(s[2 * i + 1]) for i in range(n)]
        w[10:20], w[23:27], w[27:47] = text(self.p['serial'], 10), text(self.p['fw'], 4), text(self.p['model'], 20)
        w[47] = 0x8000 | self.p['multi']
        w[49] = 0x0200 if self.p['lba'] else 0                       # LBA supported
        w[51] = min(self.p['pio'], 2) << 8
        w[53] = 0x0003
        w[54], w[55], w[56] = self.cyls, self.heads, self.spt
        cap = self.cyls * self.heads * self.spt
        w[57], w[58] = cap & 0xFFFF, cap >> 16
        w[60], w[61] = self.sectors & 0xFFFF, self.sectors >> 16
        w[64] = {3: 1, 4: 3}.get(self.p['pio'], 0)                   # advanced PIO modes (3, 4)
        return b''.join(struct.pack('<H', x) for x in w)             # ATA words are little-endian on the bus
    # ---- data port (16 bit) ----
    def read_data(self):
        if self.dir != 'in' or self.pos >= len(self.buf): return 0xFFFF
        v = self.buf[self.pos] | (self.buf[self.pos + 1] << 8); self.pos += 2
        if self.pos >= len(self.buf): self.dir = None; self.status, self.err = 0x50, 0      # last sector: no INTRQ
        elif self.pos % 512 == 0: self.irq = True                                          # next sector ready
        return v
    def write_data(self, v):
        if self.dir != 'out' or self.pos >= len(self.buf): return
        self.buf[self.pos], self.buf[self.pos + 1] = v & 0xFF, (v >> 8) & 0xFF; self.pos += 2
        if self.pos >= len(self.buf):
            a = self.pend; self.img[a * 512:a * 512 + len(self.buf)] = self.buf; self.dir = None; self.ok()
        elif self.pos % 512 == 0: self.irq = True                                          # ready for the next sector


class IdeEmu(h8emu.Emu):
    """h8emu with the CF card on the IDE port. `swap` = byte order of data words as the H8 sees them."""
    def __init__(self, image, card, swap=False):
        super().__init__(image)
        self.card, self.swap = card, swap
        self.isr, self.in_isr, self.irqs = 0xB44, False, 0             # boot ROM IDE interrupt handler (IRQ2)
        self.latch = bytearray(0x100)                                # 0x200000-0x2000FF control latches (0x200010 bit 3:
        self.latch_log = []                                          # set on the ATAPI path, cleared on ATA)
    def rb(self, a):
        a &= 0xFFFFFF
        if 0x200000 <= a < 0x200100: return self.latch[a - 0x200000]
        if IDE_LO <= a < IDE_HI:
            if a == 0x60001C: return self.card.status                # alternate status
            return (self.card.read_reg((a - IDE_LO) >> 1) or 0) if not a & 1 else 0
        return super().rb(a)
    def wb(self, a, v):
        a &= 0xFFFFFF
        if 0x200000 <= a < 0x200100:
            self.latch[a - 0x200000] = v & 0xFF; self.latch_log.append((a, v & 0xFF)); return
        if IDE_LO <= a < IDE_HI:
            if a & 1: return
            if a == 0x60001C: self.card.devctl(v); return
            self.card.write_reg((a - IDE_LO) >> 1, v); return
        return super().wb(a, v)
    def rw(self, a):
        if (a & 0xFFFFFE) == IDE_LO:
            v = self.card.read_data()
            return ((v & 0xFF) << 8) | (v >> 8) if self.swap else v
        if (a & 0xFFFFFE) == 0x60001C: return self.card.status << 8
        if IDE_LO <= (a & 0xFFFFFF) < IDE_HI: return self.rb(a & ~1) << 8
        return super().rw(a)
    def ww(self, a, v):
        if (a & 0xFFFFFE) == IDE_LO:
            self.card.write_data(((v & 0xFF) << 8) | ((v >> 8) & 0xFF) if self.swap else v); return
        if (a & 0xFFFFFE) == 0x60001C: self.card.devctl(v >> 8); return
        if IDE_LO <= (a & 0xFFFFFF) < IDE_HI: self.wb(a & ~1, v >> 8); return
        return super().ww(a, v)
    def step(self):                                                  # IRQ2 entry (advanced mode: CCR:PC on the stack)
        if self.card.irq and not self.in_isr:
            self.card.irq, self.in_isr = False, True; self.irqs += 1
            self.push32((self.ccr() << 24) | self.pc); self.I = 1; self.pc = self.isr; return
        if self.in_isr and self.rw(self.pc) == 0x5670:                # rte
            v = self.pop32(); self.set_ccr(v >> 24); self.pc = v & 0xFFFFFF; self.in_isr = False; return
        super().step()
