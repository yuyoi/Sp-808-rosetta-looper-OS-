"""Small H8S emulator for testing our own code on the PC (the instructions h8asm emits, not the whole CPU).

Stock OS routines are not emulated: every jsr/jmp to an address in `stubs` runs a Python function instead
(stub(emu) -> None, then the emulator returns to the caller). Unknown targets outside our code raise.

    emu = Emu(image_bytes)                 # OS image at 0x100000 (our build's .bin)
    emu.stubs[0x14D8AA] = lambda e: e.set16(0, 1)
    emu.call(0x16B272)                     # runs until that routine returns
"""
import struct

FLASH, RAM_LO, RAM_HI = 0x100000, 0x400000, 0x800000      # RAM incl. sample RAM (size on the unit unknown)


class Emu:
    def __init__(self, image):
        self.flash = bytearray(image)
        self.ram = bytearray(RAM_HI - RAM_LO)
        self.er = [0] * 8
        self.N = self.Z = self.V = self.C = 0
        self.pc = 0
        self.stubs = {}
        self.steps = 0
        self.code_lo, self.code_hi = 0x16B000, 0x1C0000     # where we really execute (others need a stub)

    # ---------- memory ----------
    def rb(self, a):
        a &= 0xFFFFFF
        if FLASH <= a < FLASH + len(self.flash): return self.flash[a - FLASH]
        if RAM_LO <= a < RAM_HI: return self.ram[a - RAM_LO]
        raise RuntimeError('read %06X at pc %06X' % (a, self.pc))
    def wb(self, a, v):
        a &= 0xFFFFFF
        if RAM_LO <= a < RAM_HI: self.ram[a - RAM_LO] = v & 0xFF; return
        raise RuntimeError('write %06X at pc %06X' % (a, self.pc))
    def rw(self, a): return (self.rb(a) << 8) | self.rb(a + 1)
    def ww(self, a, v): self.wb(a, v >> 8); self.wb(a + 1, v)
    def rl(self, a): return (self.rw(a) << 16) | self.rw(a + 2)
    def wl(self, a, v): self.ww(a, v >> 16); self.ww(a + 2, v & 0xFFFF)

    # ---------- registers ----------
    def g8(self, i):
        return (self.er[i] >> 8) & 0xFF if i < 8 else self.er[i - 8] & 0xFF
    def s8(self, i, v):
        v &= 0xFF
        if i < 8: self.er[i] = (self.er[i] & 0xFFFF00FF) | (v << 8)
        else: self.er[i - 8] = (self.er[i - 8] & 0xFFFFFF00) | v
    def g16(self, i):
        return self.er[i] & 0xFFFF if i < 8 else (self.er[i - 8] >> 16) & 0xFFFF
    def s16(self, i, v):
        v &= 0xFFFF
        if i < 8: self.er[i] = (self.er[i] & 0xFFFF0000) | v
        else: self.er[i - 8] = (self.er[i - 8] & 0xFFFF) | (v << 16)
    def set16(self, i, v): self.s16(i, v)
    def g32(self, i): return self.er[i] & 0xFFFFFFFF
    def s32(self, i, v): self.er[i] = v & 0xFFFFFFFF

    # ---------- flags ----------
    def nz(self, v, bits):
        self.N = (v >> (bits - 1)) & 1; self.Z = int((v & ((1 << bits) - 1)) == 0)
    def logic(self, v, bits): self.nz(v, bits); self.V = 0
    def add(self, a, b, bits):
        m = (1 << bits) - 1; r = (a + b) & m
        self.C = int(a + b > m); self.nz(r, bits)
        self.V = int(((a ^ r) & (b ^ r)) >> (bits - 1) & 1); return r
    def sub(self, a, b, bits):                              # a - b
        m = (1 << bits) - 1; r = (a - b) & m
        self.C = int(b > a); self.nz(r, bits)
        self.V = int(((a ^ b) & (a ^ r)) >> (bits - 1) & 1); return r
    def cond(self, c):
        N, Z, V, C = self.N, self.Z, self.V, self.C
        return [True, False, not (C or Z), bool(C or Z), not C, bool(C), not Z, bool(Z), not V, bool(V),
                not N, bool(N), not (N ^ V), bool(N ^ V), not (Z or (N ^ V)), bool(Z or (N ^ V))][c]

    # ---------- stack ----------
    def push32(self, v): self.er[7] = (self.er[7] - 4) & 0xFFFFFFFF; self.wl(self.er[7], v)
    def pop32(self):
        v = self.rl(self.er[7]); self.er[7] = (self.er[7] + 4) & 0xFFFFFFFF; return v

    # ---------- run ----------
    def call(self, addr, sp=0x43F000, limit=2_000_000):
        self.er[7] = sp
        self.push32(0xDEAD00)
        self.pc = addr
        while self.pc != 0xDEAD00:
            self.step()
            self.steps += 1
            if self.steps > limit: raise RuntimeError('step limit at %06X' % self.pc)

    def goto_sub(self, target, ret):
        if target in self.stubs:
            self.stubs[target](self); self.pc = ret
        elif self.code_lo <= target < self.code_hi:
            self.push32(ret); self.pc = target
        else:
            raise RuntimeError('call to %06X (no stub) from %06X' % (target, self.pc))

    def step(self):
        pc = self.pc
        b0, b1 = self.rb(pc), self.rb(pc + 1)
        hi, lo = b1 >> 4, b1 & 15
        def imm32(o): return self.rl(pc + o)
        def abs32(o): return self.rl(pc + o) & 0xFFFFFF
        if pc in self.stubs:                                 # jmp into a stub: run it, return to the caller
            self.stubs[pc](self); self.pc = self.pop32(); return
        # ---- 01 xx: long forms ----
        if b0 == 0x01 and b1 == 0x00:
            b2, b3 = self.rb(pc + 2), self.rb(pc + 3)
            if b2 == 0x6D:
                if b3 & 0xF0 == 0xF0: self.push32(self.g32(b3 & 7))
                elif b3 & 0xF0 == 0x70: self.s32(b3 & 7, self.pop32())
                else: raise RuntimeError('6D %02X' % b3)
                self.pc = pc + 4; return
            if b2 == 0x69:
                s, d = (b3 >> 4) & 7, b3 & 7
                if b3 & 0x80: self.wl(self.g32(s), self.g32(d)); v = self.g32(d)
                else: v = self.rl(self.g32(s)); self.s32(d, v)
                self.logic(v, 32); self.pc = pc + 4; return
            if b2 == 0x6F:                                 # mov.l @(d16,ers) / store
                p = (b3 >> 4) & 7; a = (self.g32(p) + struct.unpack('>h', self.flash_bytes(pc + 4, 2))[0]) & 0xFFFFFF
                if b3 & 0x80: v = self.g32(b3 & 7); self.wl(a, v)
                else: v = self.rl(a); self.s32(b3 & 7, v)
                self.logic(v, 32); self.pc = pc + 6; return
            if b2 == 0x6B:
                a = abs32(4)
                if b3 & 0xF0 == 0x20: v = self.rl(a); self.s32(b3 & 7, v)
                elif b3 & 0xF0 == 0xA0: v = self.g32(b3 & 7); self.wl(a, v)
                else: raise RuntimeError('6B %02X' % b3)
                self.logic(v, 32); self.pc = pc + 8; return
            raise RuntimeError('01 00 %02X at %06X' % (b2, pc))
        if b0 == 0x01 and b1 in (0x10, 0x20, 0x30):          # stm/ldm
            n = (b1 >> 4) + 1
            b3 = self.rb(pc + 3)
            if b3 & 0xF0 == 0xF0:
                first = b3 & 7
                for r in range(first, first + n): self.push32(self.g32(r))
            else:
                last = b3 & 7
                for r in range(last, last - n, -1): self.s32(r, self.pop32())
            self.pc = pc + 4; return
        # ---- control flow ----
        if b0 == 0x54 and b1 == 0x70: self.pc = self.pop32(); return
        if b0 == 0x5E: self.goto_sub(((b1 << 16) | self.rw(pc + 2)), pc + 4); return
        if b0 == 0x5A:
            t = (b1 << 16) | self.rw(pc + 2)
            if t in self.stubs: self.stubs[t](self); self.pc = self.pop32()
            elif self.code_lo <= t < self.code_hi: self.pc = t
            else: raise RuntimeError('jmp %06X' % t)
            return
        if b0 == 0x5D: self.goto_sub(self.g32(hi & 7) & 0xFFFFFF, pc + 2); return
        if b0 == 0x55: self.push32(pc + 2); self.pc = (pc + 2 + struct.unpack('b', bytes([b1]))[0]) & 0xFFFFFF; return
        if b0 == 0x5C and b1 == 0x00:
            self.push32(pc + 4); self.pc = (pc + 4 + struct.unpack('>h', self.flash_bytes(pc + 2, 2))[0]) & 0xFFFFFF
            return
        if 0x40 <= b0 <= 0x4F:
            self.pc = pc + 2
            if self.cond(b0 & 15): self.pc = (pc + 2 + struct.unpack('b', bytes([b1]))[0]) & 0xFFFFFF
            return
        if b0 == 0x58 and lo == 0:
            self.pc = pc + 4
            if self.cond(hi): self.pc = (pc + 4 + struct.unpack('>h', self.flash_bytes(pc + 2, 2))[0]) & 0xFFFFFF
            return
        # ---- moves ----
        if b0 == 0x0C: v = self.g8(hi); self.s8(lo, v); self.logic(v, 8); self.pc = pc + 2; return
        if b0 == 0x0D: v = self.g16(hi); self.s16(lo, v); self.logic(v, 16); self.pc = pc + 2; return
        if b0 == 0x0F and b1 & 0x80:
            v = self.g32((b1 >> 4) & 7); self.s32(b1 & 7, v); self.logic(v, 32); self.pc = pc + 2; return
        if b0 & 0xF0 == 0xF0: self.s8(b0 & 15, b1); self.logic(b1, 8); self.pc = pc + 2; return
        if b0 == 0x79:
            v = self.rw(pc + 2); n = lo
            if hi == 0: self.s16(n, v); self.logic(v, 16)
            elif hi == 2: self.sub(self.g16(n), v, 16)
            elif hi == 6: r = self.g16(n) & v; self.s16(n, r); self.logic(r, 16)
            elif hi == 1: self.s16(n, self.add(self.g16(n), v, 16))
            else: raise RuntimeError('79 %X' % hi)
            self.pc = pc + 4; return
        if b0 == 0x7A:
            v = imm32(2); n = lo & 7
            if hi == 0: self.s32(n, v); self.logic(v, 32)
            elif hi == 1: self.s32(n, self.add(self.g32(n), v, 32))
            elif hi == 2: self.sub(self.g32(n), v, 32)
            elif hi == 3: self.s32(n, self.sub(self.g32(n), v, 32))
            else: raise RuntimeError('7A %X' % hi)
            self.pc = pc + 6; return
        if b0 == 0x6A:
            if b1 == 0x38 or b1 == 0x30:                   # bit ops @aa:32
                a = abs32(2); op, bb = self.rb(pc + 6), self.rb(pc + 7) >> 4
                v = self.rb(a)
                if op == 0x70: self.wb(a, v | (1 << bb))
                elif op == 0x72: self.wb(a, v & ~(1 << bb))
                elif op == 0x73: self.Z = int(not (v >> bb) & 1)
                else: raise RuntimeError('6A %02X op %02X' % (b1, op))
                self.pc = pc + 8; return
            a = abs32(2)
            if hi == 2: v = self.rb(a); self.s8(lo, v)
            elif hi == 0xA: v = self.g8(lo); self.wb(a, v)
            else: raise RuntimeError('6A %02X' % b1)
            self.logic(v, 8); self.pc = pc + 6; return
        if b0 == 0x6B:
            a = abs32(2)
            if hi == 2: v = self.rw(a); self.s16(lo, v)
            elif hi == 0xA: v = self.g16(lo); self.ww(a, v)
            else: raise RuntimeError('6B %02X' % b1)
            self.logic(v, 16); self.pc = pc + 6; return
        if b0 == 0x68:
            p = (b1 >> 4) & 7
            if b1 & 0x80: v = self.g8(lo); self.wb(self.g32(p), v)
            else: v = self.rb(self.g32(p)); self.s8(lo, v)
            self.logic(v, 8); self.pc = pc + 2; return
        if b0 == 0x69:
            p = (b1 >> 4) & 7
            if b1 & 0x80: v = self.g16(lo); self.ww(self.g32(p), v)
            else: v = self.rw(self.g32(p)); self.s16(lo, v)
            self.logic(v, 16); self.pc = pc + 2; return
        if b0 == 0x6C and not b1 & 0x80:
            p = (b1 >> 4) & 7; v = self.rb(self.g32(p)); self.s8(lo, v); self.s32(p, self.g32(p) + 1)
            self.logic(v, 8); self.pc = pc + 2; return
        if b0 == 0x6D:                                     # push.w / pop.w
            if b1 & 0xF0 == 0xF0: self.er[7] -= 2; self.ww(self.er[7], self.g16(lo))
            elif b1 & 0xF0 == 0x70: self.s16(lo, self.rw(self.er[7])); self.er[7] += 2
            else: raise RuntimeError('6D %02X' % b1)
            self.pc = pc + 2; return
        if b0 in (0x6E, 0x6F):
            p = (b1 >> 4) & 7; a = (self.g32(p) + struct.unpack('>h', self.flash_bytes(pc + 2, 2))[0]) & 0xFFFFFF
            if b0 == 0x6E:
                if b1 & 0x80: v = self.g8(lo); self.wb(a, v)
                else: v = self.rb(a); self.s8(lo, v)
                self.logic(v, 8)
            else:
                if b1 & 0x80: v = self.g16(lo); self.ww(a, v)
                else: v = self.rw(a); self.s16(lo, v)
                self.logic(v, 16)
            self.pc = pc + 4; return
        # ---- ALU ----
        if b0 & 0xF0 == 0xA0: self.sub(self.g8(b0 & 15), b1, 8); self.pc = pc + 2; return
        if b0 & 0xF0 == 0x80: self.s8(b0 & 15, self.add(self.g8(b0 & 15), b1, 8)); self.pc = pc + 2; return
        if b0 & 0xF0 in (0xC0, 0xD0, 0xE0):
            r = b0 & 15; v = self.g8(r)
            v = {0xC0: v | b1, 0xD0: v ^ b1, 0xE0: v & b1}[b0 & 0xF0]
            self.s8(r, v); self.logic(v, 8); self.pc = pc + 2; return
        if b0 == 0x1C: self.sub(self.g8(lo), self.g8(hi), 8); self.pc = pc + 2; return
        if b0 == 0x1D: self.sub(self.g16(lo), self.g16(hi), 16); self.pc = pc + 2; return
        if b0 == 0x08: self.s8(lo, self.add(self.g8(lo), self.g8(hi), 8)); self.pc = pc + 2; return
        if b0 == 0x18: self.s8(lo, self.sub(self.g8(lo), self.g8(hi), 8)); self.pc = pc + 2; return
        if b0 == 0x19: self.s16(lo, self.sub(self.g16(lo), self.g16(hi), 16)); self.pc = pc + 2; return
        if b0 in (0x14, 0x15, 0x16):
            a_, b_ = self.g8(lo), self.g8(hi)
            v = {0x14: a_ | b_, 0x15: a_ ^ b_, 0x16: a_ & b_}[b0]
            self.s8(lo, v); self.logic(v, 8); self.pc = pc + 2; return
        if b0 == 0x17:
            if hi == 0: v = ~self.g8(lo) & 0xFF; self.s8(lo, v); self.logic(v, 8)
            elif hi == 5: v = self.g16(lo) & 0xFF; self.s16(lo, v); self.logic(v, 16)
            elif hi == 7: v = self.g32(lo & 7) & 0xFFFF; self.s32(lo & 7, v); self.logic(v, 32)
            else: raise RuntimeError('17 %X' % hi)
            self.pc = pc + 2; return
        if b0 == 0x0A:
            if b1 & 0x80: self.s32(b1 & 7, self.add(self.g32(lo & 7), self.g32((b1 >> 4) & 7), 32))
            elif hi == 0:
                c = self.C; self.s8(lo, self.add(self.g8(lo), 1, 8)); self.C = c
            else: raise RuntimeError('0A %02X' % b1)
            self.pc = pc + 2; return
        if b0 == 0x1A:
            if b1 & 0x80: self.s32(b1 & 7, self.sub(self.g32(lo & 7), self.g32((b1 >> 4) & 7), 32))
            elif hi == 0:
                c = self.C; self.s8(lo, self.sub(self.g8(lo), 1, 8)); self.C = c
            else: raise RuntimeError('1A %02X' % b1)
            self.pc = pc + 2; return
        if b0 == 0x0B:
            n = {0: 1, 8: 2, 9: 4}.get(hi)
            if n is not None: self.s32(lo & 7, self.g32(lo & 7) + n)
            elif hi == 5: c = self.C; self.s16(lo, self.add(self.g16(lo), 1, 16)); self.C = c
            else: raise RuntimeError('0B %02X' % b1)
            self.pc = pc + 2; return
        if b0 == 0x1B:
            n = {0: 1, 8: 2, 9: 4}.get(hi)
            if n is not None: self.s32(lo & 7, self.g32(lo & 7) - n)
            elif hi == 5: c = self.C; self.s16(lo, self.sub(self.g16(lo), 1, 16)); self.C = c
            else: raise RuntimeError('1B %02X' % b1)
            self.pc = pc + 2; return
        if b0 in (0x10, 0x11):
            left = b0 == 0x10
            kind, cnt = {0: (8, 1), 1: (16, 1), 3: (32, 1), 4: (8, 2), 5: (16, 2), 7: (32, 2)}[hi]
            r = lo if kind != 32 else lo & 7
            v = {8: self.g8, 16: self.g16, 32: self.g32}[kind](r)
            for _ in range(cnt):
                if left: self.C = (v >> (kind - 1)) & 1; v = (v << 1) & ((1 << kind) - 1)
                else: self.C = v & 1; v >>= 1
            {8: self.s8, 16: self.s16, 32: self.s32}[kind](r, v); self.logic(v, kind)
            self.pc = pc + 2; return
        if b0 == 0x50: self.s16(lo, (self.g16(lo) & 0xFF) * self.g8(hi)); self.pc = pc + 2; return
        if b0 == 0x73: self.Z = int(not (self.g8(lo) >> hi) & 1); self.pc = pc + 2; return
        if b0 == 0x00 and b1 == 0x00: self.pc = pc + 2; return
        raise RuntimeError('unknown opcode %02X %02X at %06X' % (b0, b1, pc))

    def flash_bytes(self, a, n): return bytes(self.rb(a + i) for i in range(n))
