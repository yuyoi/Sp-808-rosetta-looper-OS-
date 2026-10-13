"""Add (or replace) a file in the root dir of a FAT12/FAT16 disk image, e.g. a ZuluIDE .img
that the SP-808 formatted. Handles both a bare FAT volume and an MBR-partitioned disk.

Data is put in one contiguous run of clusters (safest for an old embedded FAT reader).
A .bak of the image is written first, and the file is read back through the FAT afterwards.

usage: python -I fat_add.py disk.img SP808.PRG [--name "SP808   PRG"] [--replace] [--info]
"""
import argparse, shutil, struct, sys, time


class Fat:
    def __init__(self, img):
        self.img = img
        self.base = self._find_volume()
        b = self.base
        (self.bps, self.spc, self.res, self.nfats, self.rootents, ts16, _media, self.spf,
         ) = struct.unpack_from('<HBHBHHBH', img, b + 11)
        ts32 = struct.unpack_from('<I', img, b + 32)[0]
        self.total = ts16 or ts32
        self.fat0 = b + self.res * self.bps
        self.root = self.fat0 + self.nfats * self.spf * self.bps
        self.rootsz = self.rootents * 32
        self.data = self.root + ((self.rootsz + self.bps - 1) // self.bps) * self.bps
        self.csize = self.spc * self.bps
        data_secs = self.total - (self.data - b) // self.bps
        self.nclus = data_secs // self.spc
        self.fat12 = self.nclus < 4085
        assert self.nclus < 65525, 'FAT32 not supported'

    def _find_volume(self):
        def bpb_ok(o):
            if o + 512 > len(self.img): return False
            bps, spc = struct.unpack_from('<HB', self.img, o + 11)
            return (self.img[o] in (0xEB, 0xE9) and bps in (512, 1024, 2048, 4096)
                    and spc in (1, 2, 4, 8, 16, 32, 64, 128) and self.img[o + 16] in (1, 2))
        if bpb_ok(0):
            return 0
        if self.img[510:512] == b'\x55\xaa':
            for i in range(4):
                e = 0x1BE + 16 * i
                ptype, lba = self.img[e + 4], struct.unpack_from('<I', self.img, e + 8)[0]
                if ptype in (0x01, 0x04, 0x06, 0x0E) and bpb_ok(lba * 512):
                    return lba * 512
        sys.exit('no FAT12/16 volume found (not superfloppy, no FAT partition in MBR)')

    def get(self, n):
        if self.fat12:
            v = struct.unpack_from('<H', self.img, self.fat0 + n * 3 // 2)[0]
            return v >> 4 if n & 1 else v & 0xFFF
        return struct.unpack_from('<H', self.img, self.fat0 + n * 2)[0]

    def set(self, n, val):
        for k in range(self.nfats):
            f = self.fat0 + k * self.spf * self.bps
            if self.fat12:
                o = f + n * 3 // 2
                v = struct.unpack_from('<H', self.img, o)[0]
                v = (v & 0x000F) | (val << 4) if n & 1 else (v & 0xF000) | val
                struct.pack_into('<H', self.img, o, v)
            else:
                struct.pack_into('<H', self.img, f + n * 2, val)

    @property
    def eoc(self): return 0xFFF if self.fat12 else 0xFFFF

    def chain(self, start):
        out, c = [], start
        while 2 <= c < self.nclus + 2:
            out.append(c); c = self.get(c)
            if len(out) > self.nclus: sys.exit('FAT loop')
        return out

    def entries(self):
        for i in range(self.rootents):
            o = self.root + i * 32
            yield i, o, self.img[o:o + 32]

    def info(self):
        free = sum(1 for c in range(2, self.nclus + 2) if self.get(c) == 0)
        print('volume @0x%x  FAT%d  %d B/sec  %d sec/clus  %d clusters (%d free)  root %d entries'
              % (self.base, 12 if self.fat12 else 16, self.bps, self.spc, self.nclus, free, self.rootents))
        print('OEM %r  label %r' % (bytes(self.img[self.base + 3:self.base + 11]),
                                   bytes(self.img[self.base + 43:self.base + 54])))
        for i, o, e in self.entries():
            if e[0] in (0, 0xE5) or e[11] == 0x0F: continue
            print('  %-11s attr %02x  clus %5d  size %d' % (e[:11].decode('latin1'), e[11],
                  struct.unpack_from('<H', e, 26)[0], struct.unpack_from('<I', e, 28)[0]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('disk'); ap.add_argument('file', nargs='?')
    ap.add_argument('--name', default='SP808   PRG')
    ap.add_argument('--replace', action='store_true')
    ap.add_argument('--info', action='store_true')
    a = ap.parse_args()
    img = bytearray(open(a.disk, 'rb').read())
    fs = Fat(img)
    fs.info()
    if a.info or not a.file:
        return
    name = a.name.encode('ascii'); assert len(name) == 11
    data = open(a.file, 'rb').read()
    need = (len(data) + fs.csize - 1) // fs.csize

    slot = None
    for i, o, e in fs.entries():
        if e[:11] == name and e[11] != 0x0F:
            if not a.replace: sys.exit('%s already on disk; use --replace' % a.name)
            for c in fs.chain(struct.unpack_from('<H', e, 26)[0]): fs.set(c, 0)
            img[o] = 0xE5
        if slot is None and e[0] in (0, 0xE5):
            slot = o
    if slot is None: sys.exit('root directory full')

    run, start = 0, None
    for c in range(2, fs.nclus + 2):
        run = run + 1 if fs.get(c) == 0 else 0
        if run == need: start = c - need + 1; break
    if start is None: sys.exit('no contiguous free run of %d clusters' % need)

    for k in range(need):
        c = start + k
        fs.set(c, c + 1 if k < need - 1 else fs.eoc)
        o = fs.data + (c - 2) * fs.csize
        chunk = data[k * fs.csize:(k + 1) * fs.csize]
        img[o:o + fs.csize] = chunk + b'\x00' * (fs.csize - len(chunk))

    t = time.localtime()
    ftime = (t.tm_hour << 11) | (t.tm_min << 5) | (t.tm_sec // 2)
    fdate = ((t.tm_year - 1980) << 9) | (t.tm_mon << 5) | t.tm_mday
    ent = bytearray(32); ent[:11] = name; ent[11] = 0x20
    struct.pack_into('<HHHHHHHI', ent, 14, ftime, fdate, fdate, 0, ftime, fdate, start, len(data))
    img[slot:slot + 32] = ent

    # read back through the FAT before touching the real file
    ch = fs.chain(start)
    back = b''.join(img[fs.data + (c - 2) * fs.csize:fs.data + (c - 1) * fs.csize] for c in ch)[:len(data)]
    assert len(ch) == need and back == data, 'read-back mismatch'

    shutil.copyfile(a.disk, a.disk + '.bak')
    open(a.disk, 'wb').write(img)
    print('added %s: %d bytes, clusters %d-%d, backup %s.bak' % (a.name, len(data), start, start + need - 1, a.disk))
    Fat(img).info()


if __name__ == '__main__':
    main()
