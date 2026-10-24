"""CF support research in the emulator: Roland's own boot ROM IDE driver against a virtual CF card (ide_model) holding an
SP-808 disk image. Shows what the boot ROM detects (type 0 = ATA / CF, 1 = ATAPI / Zip), the geometry it reads, and
whether its read routine returns the image's sectors.
usage: python -I tools/test_cf.py sp808_v1050_raw.bin disk.img [profile]"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ide_model

HERE = os.path.dirname(os.path.abspath(__file__))
DUMP = os.path.join(HERE, '..', 'dump')


def make(image, disk, profile, swap=False):
    card = ide_model.CFCard(bytearray(disk), ide_model.PROFILES[profile])
    e = ide_model.IdeEmu(image[:0xC0000], card, swap)
    e.boot = open(os.path.join(DUMP, 'BOOTROM.BIN'), 'rb').read()
    e.ram[:0x3000] = open(os.path.join(DUMP, 'BOOTRAM.BIN'), 'rb').read()[:0x3000]
    e.code_lo, e.code_hi = 0x000000, 0x1C0000
    e.stubs[0x946C] = lambda e: None                             # boot ROM delay (timer poll): skip
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


if __name__ == '__main__':
    main(*sys.argv[1:])
