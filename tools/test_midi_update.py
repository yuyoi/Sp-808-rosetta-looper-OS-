"""Feed MIDI update files to Roland's own boot ROM receiver (0x2D66, the "Waiting MIDI..." mode) in the emulator and
check what lands in its flash buffer (RAM 0x440000), the 8-file bits (0x401862 == 0x401863, else "Data Not Enough!")
and its image check 0x94C4, before anything is sent to the unit.
usage: python -I tools/test_midi_update.py <folder with Roland's SP808#1-8.MID> <folder to test> new_raw.bin"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_cf
import encode_upd as E

BUF, SIZE = 0x440000, 0xC0000


def stream(folder):
    for n in range(1, 9):
        _, evs = E.read_track(os.path.join(folder, 'SP808#%d.MID' % n))
        for _, raw in evs:
            if raw[0] == 0xF0:
                yield 0xF0
                yield from E.sysex_of(raw)


def receive(image, folder):
    e, _ = test_cf.make(image, bytes(512 * 64), 'generic-2gb', swap=True)
    src = stream(folder)
    def getb(e):
        try: e.s8(8, next(src))
        except StopIteration: raise RuntimeError('MIDI stream ended before the receiver finished')
    e.stubs[0x8D90] = getb                                       # next MIDI byte (SCI ring buffer on the unit)
    for a in (0x99D0, 0x9A94, 0xA680, 0xA756): e.stubs[a] = lambda e: None    # LCD text
    e.wb(0x401862, 0); e.wb(0x401863, 0)
    e.ram[BUF - 0x400000:BUF - 0x400000 + SIZE] = b'\xFF' * SIZE  # as 0x9750 does
    e.call(0x2D66, limit=200_000_000); ok = e.g16(0)
    left = sum(1 for _ in src)
    files = (e.rb(0x401862), e.rb(0x401863))
    e.er[0] = BUF
    e.call(0x94C4, limit=50_000_000); valid = e.g16(0)
    return ok, files, left, bytes(e.ram[BUF - 0x400000:BUF - 0x400000 + SIZE]), valid


def main(roland_folder, folder, raw):
    new = open(raw, 'rb').read()[:SIZE]
    ok, files, left, buf, valid = receive(new, folder)
    want = E.expected(roland_folder, new)
    bad = [hex(0x100000 + i) for i in range(SIZE) if buf[i] != want[i]]
    print('%s: receiver %s, file bits %02X/%02X (%s), %d bytes left unread, image check %s, buffer == expected: %s %s' % (
        folder, 'OK' if ok == 1 else 'MIDI Data Error', files[0], files[1], 'all files' if files[0] == files[1] else
        'Data Not Enough', left, 'OK' if valid else 'FAILED', not bad, bad[:6]))
    return ok == 1 and files[0] == files[1] and valid and not bad


if __name__ == '__main__':
    sys.exit(0 if main(*sys.argv[1:4]) else 1)
