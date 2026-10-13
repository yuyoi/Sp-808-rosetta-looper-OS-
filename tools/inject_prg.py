"""Swap a stock SP808.PRG inside an SP-808 disk image (e.g. the SD card's .img) for a patched one.

Flow: on the SP-808, power on holding CLEAR + LOC 2 -> "SAVE SYSPROG FILE"
writes SP808.PRG (stock OS) to the disk. Then run this on the disk image:
it finds that file's data by its header, checks it is the stock image laid
out contiguously, makes a .bak of the disk image, and overwrites it in place.
No filesystem edits needed: same name, same size.

usage: python -I inject_prg.py disk.img stock_raw.bin new_SP808.PRG
"""
import shutil, sys

SIZE = 0xC0008


def main(disk, stock_raw, new_prg):
    new = open(new_prg, 'rb').read()
    stock = b'\x00\x10\x00\x00\x00\x1c\x00\x00' + open(stock_raw, 'rb').read()[:SIZE - 8]
    assert len(new) == SIZE and new[:9] == stock[:9]
    d = open(disk, 'rb').read()
    hits = [o for o in range(0, len(d) - SIZE + 1, 512) if d[o:o + 9] == stock[:9]]
    print('candidates at', [hex(h) for h in hits])
    good = [o for o in hits if d[o:o + SIZE] == stock]
    if len(good) != 1:
        sys.exit('need exactly 1 contiguous stock SP808.PRG, found %d (fragmented or already patched?)' % len(good))
    o = good[0]
    shutil.copyfile(disk, disk + '.bak')
    with open(disk, 'r+b') as f:
        f.seek(o); f.write(new)
    print('patched at 0x%x, backup at %s.bak' % (o, disk))


if __name__ == '__main__':
    main(*sys.argv[1:4])
