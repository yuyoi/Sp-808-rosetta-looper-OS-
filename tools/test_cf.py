"""CF support research in the emulator: Roland's own boot ROM IDE driver against a virtual CF card (ide_model) holding an
SP-808 disk image. Shows what the boot ROM detects (type 0 = ATA / CF, 1 = ATAPI / Zip), the geometry it reads, and
whether its read routine returns the image's sectors.
usage: python -I tools/test_cf.py sp808_v1050_raw.bin disk.img [profile]"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ide_model

HERE = os.path.dirname(os.path.abspath(__file__))
DUMP = os.path.join(HERE, '..', 'dump')


IDLE = 0x4E0000                                                  # wait until the driver is idle (0x401000 = 0), as the OS
IDLE_CODE = bytes.fromhex('6a2800401000' '46f8' '5470')            # does in 0x106142 before the next command


def make(image, disk, profile, swap=False):
    card = ide_model.CFCard(bytearray(disk), ide_model.PROFILES[profile])
    e = ide_model.IdeEmu(image[:0xC0000], card, swap)
    e.boot = open(os.path.join(DUMP, 'BOOTROM.BIN'), 'rb').read()
    e.ram[:0x3000] = open(os.path.join(DUMP, 'BOOTRAM.BIN'), 'rb').read()[8:0x3008]      # the dump has an 8-byte header
    e.code_lo, e.code_hi = 0x000000, 0x800000                    # boot ROM, OS, and the RAM vector JMPs
    e.stubs[0x946C] = lambda e: None                             # boot ROM delay (timer poll): skip
    for v in (0x400210, 0x400214): e.stubs[v] = lambda e: None    # OS-installed mask save / restore (EXR ops)
    e.wb(0x401001, 0)                                            # no drive known yet (the dump had the Zip)
    e.ram[IDLE - 0x400000:IDLE - 0x400000 + len(IDLE_CODE)] = IDLE_CODE
    return e, card


def main(image_path, disk_path, profile='generic-2gb'):
    image, disk = open(image_path, 'rb').read(), open(disk_path, 'rb').read()
    for swap in (False, True):
        e, card = make(image, disk, profile, swap)
        try:
            e.call(0xF30, limit=5_000_000)                           # IDE init (vector 0x400388)
            r = 'ok'
        except RuntimeError as x:
            r = 'stopped: %s' % x
        print('swap %-5s init %s' % (swap, r))
        print('           type @401014 = %d (0 = ATA / CF, 1 = ATAPI / Zip), present %d, heads %d, spt %d, capacity %d, '
              'error %04X' % (e.rb(0x401014), e.rb(0x401001), e.rw(0x401006), e.rw(0x401008), e.rl(0x40100A), e.rw(0x40101E)))
        print('           commands sent:', ['%02X lba %d n %d' % c for c in card.log][:12])
        if not swap: continue                                        # (the SP-808 wiring is the swapped one)
        for lba, n in ((0, 1), (1000, 8), (204000, 64)):             # Roland's read (vector 0x4003A8 -> ROM 0x16E8)
            buf = 0x4C0000
            del card.log[:]
            e.er[7] = 0x43F000; e.push32(buf)
            e.er[0] = lba; e.s8(9, n)
            try:
                e.call(0x16E8, sp=e.er[7], limit=5_000_000); e.call(IDLE, limit=5_000_000); r = 'ok'
            except RuntimeError as x:
                r = 'stopped: %s' % x
            got = bytes(e.ram[buf - 0x400000:buf - 0x400000 + 512 * n])
            print('read       lba %6d n %2d: %s, error %04X, data == image: %s, card commands %s' % (
                lba, n, r, e.rw(0x40101E), got == disk[lba * 512:(lba + n) * 512], ['%02X' % c[0] for c in card.log]))
        for lba, n in ((5000, 1), (204100, 64)):                      # Roland's write (vector 0x4003AC -> ROM 0x1940)
            buf = 0x4C0000
            data = bytes((lba + i * 7 + (i >> 9)) & 0xFF for i in range(512 * n))
            e.ram[buf - 0x400000:buf - 0x400000 + len(data)] = data
            del card.log[:]
            e.er[7] = 0x43F000; e.push32(buf)
            e.er[0] = lba; e.s8(9, n)
            try:
                e.call(0x1940, sp=e.er[7], limit=5_000_000)              # returns once the first burst is going;
                e.call(IDLE, limit=5_000_000); r = 'ok'                  # the rest runs in the IDE / DTC interrupts
            except RuntimeError as x:
                r = 'stopped: %s' % x
            print('write      lba %6d n %2d: %s, error %04X, card == data: %s, card commands %s' % (
                lba, n, r, e.rw(0x40101E), bytes(card.img[lba * 512:(lba + n) * 512]) == data,
                ['%02X' % c[0] for c in card.log]))


if __name__ == '__main__':
    main(*sys.argv[1:])
