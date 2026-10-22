"""Rosetta Patcher: turn Roland's own SP-808 OS 1.05 update into SP-808 Rosetta OS (SP808.PRG), optionally straight
into a Zip / ZuluIDE disk image. Roland's code is never shipped: you bring SP808v1050.zip (or its SP808#1-8.MID
files, or an already decoded sp808_v1050_raw.bin).

window:        python tools/rosetta_patcher.py
command line:  python -I tools/rosetta_patcher.py --upd SP808v1050.zip --out outdir [--img disk.img]
The disk image gets a .bak first, and the PRG is read back and compared after writing.
"""
import argparse, hashlib, io, os, queue, shutil, sys, tempfile, threading, zipfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def load_update(path, log=print):
    """zip / folder of SP808#n.MID / raw .bin -> decoded OS image bytes"""
    import decode_upd
    if os.path.isfile(path) and path.lower().endswith('.bin'):
        img = open(path, 'rb').read(); log('raw image: %s (%d bytes)' % (os.path.basename(path), len(img)))
        return img
    with tempfile.TemporaryDirectory() as td:
        if os.path.isfile(path) and zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as z:
                mids = [n for n in z.namelist() if n.upper().endswith('.MID')]
                if not mids: raise ValueError('no .MID files in %s' % path)
                for n in mids:
                    open(os.path.join(td, os.path.basename(n)), 'wb').write(z.read(n))
            folder = td; log('zip: %d update files' % len(mids))
        elif os.path.isdir(path):
            folder = path
        else:
            raise ValueError('not a zip, a folder or a .bin: %s' % path)
        img, chunks = decode_upd.decode(folder)
    log('decoded the update: %d chunks, %d bytes' % (chunks, len(img)))
    return img


def check_image(img, log=print):
    import struct
    ver = struct.unpack('>H', img[0x0E:0x10])[0]
    if ver != 1050:
        raise ValueError('this is OS version %d; Rosetta OS needs the SP-808 (non-EX) OS 1.05 (1050)' % ver)
    log('Roland OS 1.05 found, sha256 %s' % hashlib.sha256(img[:0xC0000]).hexdigest()[:16])


def build(img, outdir, log=print):
    import build_v10 as bm
    os.makedirs(outdir, exist_ok=True)
    raw = os.path.join(outdir, '_roland_raw.bin')
    open(raw, 'wb').write(img)
    old = sys.stdout; sys.stdout = io.StringIO()
    try:
        bm.main(raw, outdir)
        out = sys.stdout.getvalue()
    finally:
        sys.stdout = old
        os.remove(raw)
    for line in out.splitlines()[:2]: log(line)
    prg = os.path.join(outdir, 'SP808.PRG')
    log('Rosetta OS v%s -> %s (sha256 %s)' % (bm.VER_TXT, prg, hashlib.sha256(open(prg, 'rb').read()).hexdigest()[:16]))
    try: os.remove(os.path.join(outdir, 'sp808_v10.bin'))       # keep only the PRG (Roland-derived either way)
    except OSError: pass
    return prg


def install(prg, disk, log=print):
    import subprocess
    r = subprocess.run([sys.executable, '-I', os.path.join(HERE, 'fat_add.py'), disk, prg, '--replace'],
                       capture_output=True, text=True)
    if r.returncode: raise RuntimeError('fat_add failed:\n' + r.stdout + r.stderr)
    data, prgb = open(disk, 'rb').read(), open(prg, 'rb').read()
    i = data.find(prgb[:64])
    if i < 0 or data[i:i + len(prgb)] != prgb: raise RuntimeError('read-back check failed: the PRG is not in the image')
    log('installed into %s (backup: %s.bak), read back OK' % (disk, disk))


def run(upd, outdir, disk=None, log=print):
    img = load_update(upd, log); check_image(img, log)
    prg = build(img, outdir, log)
    if disk: install(prg, disk, log)
    log('done. On the SP-808: power on with the disk in, answer YES to "Update System?", power-cycle when it asks '
        'for the Zip (hold HOLD at power-on to force the prompt). Back up your disk first. Do not share the PRG: '
        'it contains Roland code; share the patcher instead.')
    return prg


def gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext
    root = tk.Tk(); root.title('Rosetta Patcher - SP-808'); root.geometry('640x420')
    v_upd, v_out, v_img = tk.StringVar(), tk.StringVar(value=os.path.join(os.path.expanduser('~'), 'Rosetta_SP808')), tk.StringVar()
    def row(r, label, var, pick):
        tk.Label(root, text=label, anchor='w').grid(row=r, column=0, sticky='w', padx=8, pady=4)
        tk.Entry(root, textvariable=var, width=60).grid(row=r, column=1, sticky='we', padx=4)
        tk.Button(root, text='...', command=pick, width=3).grid(row=r, column=2, padx=8)
    row(0, 'Roland update', v_upd, lambda: v_upd.set(filedialog.askopenfilename(
        title='SP808v1050.zip, an SP808#1.MID or sp808_v1050_raw.bin',
        filetypes=[('Roland update', '*.zip *.MID *.mid *.bin'), ('all', '*.*')]) or v_upd.get()))
    row(1, 'Output folder', v_out, lambda: v_out.set(filedialog.askdirectory() or v_out.get()))
    row(2, 'Disk image (optional)', v_img, lambda: v_img.set(filedialog.askopenfilename(
        title='Zip / ZuluIDE disk image', filetypes=[('disk image', '*.img *.ima *.hda'), ('all', '*.*')]) or v_img.get()))
    root.columnconfigure(1, weight=1)
    tk.Label(root, text="You need Roland's own SP808v1050.zip (SP-808 OS 1.05). It is not included.", fg='#555').grid(
        row=3, column=0, columnspan=3, sticky='w', padx=8)
    logw = scrolledtext.ScrolledText(root, height=14); logw.grid(row=5, column=0, columnspan=3, sticky='nsew', padx=8, pady=8)
    root.rowconfigure(5, weight=1)
    q = queue.Queue()
    def log(s): q.put(s)
    def pump():
        while not q.empty():
            s = q.get()
            if s == '__done__': btn.config(state='normal'); continue
            logw.insert('end', s + '\n'); logw.see('end')
        root.after(100, pump)
    def go():
        upd = v_upd.get()
        if upd.upper().endswith('.MID'): upd = os.path.dirname(upd)           # one .MID picked: use its folder
        if not upd: messagebox.showerror('Rosetta Patcher', 'Pick the Roland update first.'); return
        disk = v_img.get() or None
        if disk and not messagebox.askyesno('Rosetta Patcher', 'Write SP808.PRG into\n%s ?\n(a .bak copy is made first)' % disk):
            return
        btn.config(state='disabled')
        def work():
            try: run(upd, v_out.get(), disk, log)
            except Exception as ex: log('ERROR: %s' % ex)
            log('__done__')
        threading.Thread(target=work, daemon=True).start()
    btn = tk.Button(root, text='Build Rosetta OS', command=go, height=2); btn.grid(row=4, column=0, columnspan=3, pady=4)
    pump(); root.mainloop()


def main():
    if len(sys.argv) == 1: return gui()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--upd', required=True, help='SP808v1050.zip, the folder with SP808#1-8.MID, or a decoded .bin')
    ap.add_argument('--out', required=True, help='output folder for SP808.PRG')
    ap.add_argument('--img', help='optional Zip / ZuluIDE disk image to install into (a .bak is made)')
    a = ap.parse_args()
    run(a.upd, a.out, a.img)


if __name__ == '__main__':
    main()
