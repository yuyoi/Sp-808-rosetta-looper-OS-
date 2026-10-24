"""Rosetta Patcher: turn Roland's own SP-808 OS 1.05 update into SP-808 Rosetta OS (SP808.PRG), optionally straight
into a Zip / ZuluIDE disk image. Roland's code is never shipped: you bring SP808v1050.zip (or its SP808#1-8.MID
files, or an already decoded sp808_v1050_raw.bin). CF beta (cf_patch.py): plain CF cards on an IDE adapter, on Rosetta
or on Roland's stock OS (1.05, or SP808EXv1001.zip for the EX).

window:        python tools/rosetta_patcher.py
command line:  python -I tools/rosetta_patcher.py --upd SP808v1050.zip --out outdir [--img disk.img] [--cf] [--stock]
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


def check_image(img, log=print, stock=False):
    import struct
    ver = struct.unpack('>H', img[0x0E:0x10])[0]
    if ver != 1050 and not (stock and ver == 1001):
        raise ValueError('this is OS version %d; Rosetta OS needs the SP-808 (non-EX) OS 1.05 (1050)%s' % (
            ver, '' if stock else ' (stock + CF beta also takes EX 1.001)'))
    log('Roland OS %s found, sha256 %s' % ({1050: '1.05', 1001: 'EX 1.001'}[ver], hashlib.sha256(img[:0xC0000]).hexdigest()[:16]))


def build_stock_cf(img, outdir, log=print):
    import cf_patch
    out, name, old, new = cf_patch.stock(img)
    os.makedirs(outdir, exist_ok=True)
    prg = os.path.join(outdir, 'SP808.PRG')
    data = cf_patch.prg(out)
    open(prg + '.tmp', 'wb').write(data); os.replace(prg + '.tmp', prg)
    log('stock %s + CF beta, version %d -> %d -> %s (sha256 %s)' % (name, old, new, prg, hashlib.sha256(data).hexdigest()[:16]))
    return prg


def build(img, outdir, log=print, cf=False):
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
    if cf:
        import cf_patch
        cf_patch.patch_prg(prg)
    log('Rosetta OS v%s%s -> %s (sha256 %s)' % (bm.VER_TXT, ' + CF beta' if cf else '', prg,
                                                hashlib.sha256(open(prg, 'rb').read()).hexdigest()[:16]))
    try: os.remove(os.path.join(outdir, 'sp808_v10.bin'))       # keep only the PRG (Roland-derived either way)
    except OSError: pass
    return prg


def install(prg, disk, log=print):
    import fat_add                                    # in-process (works inside the .exe too)
    old_argv, old_out = sys.argv, sys.stdout; sys.argv, sys.stdout = ['fat_add', disk, prg, '--replace'], io.StringIO()
    try:
        fat_add.main()
    except SystemExit as ex:
        if ex.code: raise RuntimeError('fat_add failed: %s\n%s' % (ex.code, sys.stdout.getvalue()))
    finally:
        sys.argv, sys.stdout = old_argv, old_out
    data, prgb = open(disk, 'rb').read(), open(prg, 'rb').read()
    i = data.find(prgb[:64])
    if i < 0 or data[i:i + len(prgb)] != prgb: raise RuntimeError('read-back check failed: the PRG is not in the image')
    log('installed into %s (backup: %s.bak), read back OK' % (disk, disk))


def run(upd, outdir, disk=None, log=print, stock=False, cf=False):
    if stock and not cf: raise ValueError('stock OS without CF beta: nothing to patch')
    img = load_update(upd, log); check_image(img, log, stock)
    prg = build_stock_cf(img, outdir, log) if stock else build(img, outdir, log, cf)
    if disk: install(prg, disk, log)
    log('done. On the SP-808: power on with the disk in, answer YES to "Update System?", power-cycle when it asks '
        'for the Zip (hold HOLD at power-on to force the prompt). Back up your disk first. Do not share the PRG: '
        'it contains Roland code; share the patcher instead.')
    if cf:
        log('CF beta: install from the Zip / ZuluIDE as usual, then swap in the CF adapter (card as master) with an '
            'SP-808 disk image written to the card. Untested on hardware: please report back. An EX OS build is for '
            'SP-808EX units only.')
    return prg


def gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext
    try: __import__('ctypes').windll.shell32.SetCurrentProcessExplicitAppUserModelID('Rosetta.Patcher.SP808')
    except Exception: pass                            # own taskbar entry (not "Python"), so it shows our icon
    try: __import__('ctypes').windll.shcore.SetProcessDpiAwareness(1)
    except Exception: pass                            # crisp text and icons on scaled displays
    BG, PANEL, BLUE, GREEN, TXT = '#05080c', '#0d141c', '#2ec4ff', '#39ff88', '#cfeee0'
    root = tk.Tk(); root.title('Rosetta Patcher - SP-808'); root.geometry('680x500'); root.configure(bg=BG)
    base = getattr(sys, '_MEIPASS', os.path.join(HERE, '..'))
    for ico in (os.path.join(base, 'tools', 'rosetta_patcher.ico'), os.path.join(HERE, 'rosetta_patcher.ico')):
        if os.path.exists(ico):
            try: root.iconbitmap(default=ico)
            except tk.TclError: pass
            try:                                      # Windows: hand the exact big / small sizes it wants (DPI aware)
                import ctypes
                u = ctypes.windll.user32; root.update_idletasks()
                u.LoadImageW.restype = ctypes.c_void_p
                u.LoadImageW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
                u.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_void_p]
                hwnd = int(root.wm_frame(), 16)
                dpi = u.GetDpiForWindow(hwnd) if hasattr(u, 'GetDpiForWindow') else 96
                for which, metric in ((1, 11), (0, 49)):       # ICON_BIG = SM_CXICON, ICON_SMALL = SM_CXSMICON
                    sz = u.GetSystemMetricsForDpi(metric, dpi) if hasattr(u, 'GetSystemMetricsForDpi') else u.GetSystemMetrics(metric)
                    h = u.LoadImageW(None, ico, 1, sz, sz, 0x10)   # IMAGE_ICON, LR_LOADFROMFILE: picks that size
                    if h: u.SendMessageW(hwnd, 0x80, which, h)     # WM_SETICON
            except Exception: pass
            break
    tk.Label(root, text='ROSETTA OS  //  SP-808 PATCHER', bg=BG, fg=GREEN, font=('Consolas', 15, 'bold')).grid(
        row=0, column=0, columnspan=3, sticky='w', padx=10, pady=(10, 2))
    lab = dict(bg=BG, fg=BLUE, font=('Consolas', 10))
    ent = dict(bg=PANEL, fg=TXT, insertbackground=GREEN, relief='flat', font=('Consolas', 10), highlightthickness=1,
               highlightbackground='#1b2a36', highlightcolor=BLUE)
    btn_s = dict(bg=PANEL, fg=GREEN, activebackground=BLUE, activeforeground=BG, relief='flat', font=('Consolas', 10, 'bold'))
    v_upd, v_out, v_img = tk.StringVar(), tk.StringVar(value=os.path.join(os.path.expanduser('~'), 'Rosetta_SP808')), tk.StringVar()
    def row(r, label, var, pick):
        tk.Label(root, text=label, anchor='w', **lab).grid(row=r, column=0, sticky='w', padx=10, pady=5)
        tk.Entry(root, textvariable=var, width=60, **ent).grid(row=r, column=1, sticky='we', padx=4, ipady=3)
        tk.Button(root, text='...', command=pick, width=3, **btn_s).grid(row=r, column=2, padx=10)
    row(1, 'Roland update', v_upd, lambda: v_upd.set(filedialog.askopenfilename(
        title='SP808v1050.zip / SP808EXv1001.zip, an SP808#1.MID or a decoded .bin',
        filetypes=[('Roland update', '*.zip *.MID *.mid *.bin'), ('all', '*.*')]) or v_upd.get()))
    row(2, 'Output folder', v_out, lambda: v_out.set(filedialog.askdirectory() or v_out.get()))
    row(3, 'Disk image (optional)', v_img, lambda: v_img.set(filedialog.askopenfilename(
        title='Zip / ZuluIDE disk image', filetypes=[('disk image', '*.img *.ima *.hda'), ('all', '*.*')]) or v_img.get()))
    root.columnconfigure(1, weight=1)
    tk.Label(root, text="You need Roland's own SP808v1050.zip (OS 1.05; stock EX + CF: SP808EXv1001.zip). Not included.", bg=BG,
             fg='#4f6b7a', font=('Consolas', 9)).grid(row=4, column=0, columnspan=3, sticky='w', padx=10)
    v_stock, v_cf = tk.BooleanVar(value=False), tk.BooleanVar(value=False)
    opt = tk.Frame(root, bg=BG); opt.grid(row=5, column=0, columnspan=3, sticky='w', padx=6)
    chk = dict(bg=BG, fg=BLUE, selectcolor=PANEL, activebackground=BG, activeforeground=GREEN, font=('Consolas', 10))
    tk.Radiobutton(opt, text='Rosetta OS', variable=v_stock, value=False, **chk).pack(side='left')
    tk.Radiobutton(opt, text='Roland stock OS (1.05 / EX 1.001)', variable=v_stock, value=True, **chk).pack(side='left')
    tk.Checkbutton(opt, text='CF card support (beta)', variable=v_cf, **chk).pack(side='left', padx=(16, 0))
    logw = scrolledtext.ScrolledText(root, height=14, bg=PANEL, fg=GREEN, insertbackground=GREEN, relief='flat',
                                     font=('Consolas', 9), highlightthickness=1, highlightbackground='#1b2a36')
    logw.grid(row=7, column=0, columnspan=3, sticky='nsew', padx=10, pady=10)
    root.rowconfigure(7, weight=1)
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
        stock, cf = v_stock.get(), v_cf.get()
        def work():
            try: run(upd, v_out.get(), disk, log, stock, cf)
            except Exception as ex: log('ERROR: %s' % ex)
            log('__done__')
        threading.Thread(target=work, daemon=True).start()
    btn = tk.Button(root, text='BUILD', command=go, height=2, width=24, **btn_s)
    btn.config(fg=BG, bg=GREEN, activebackground=BLUE); btn.grid(row=6, column=0, columnspan=3, pady=6)
    pump(); root.mainloop()


def main():
    if len(sys.argv) == 1: return gui()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--upd', required=True, help='SP808v1050.zip, the folder with SP808#1-8.MID, or a decoded .bin')
    ap.add_argument('--out', required=True, help='output folder for SP808.PRG')
    ap.add_argument('--img', help='optional Zip / ZuluIDE disk image to install into (a .bak is made)')
    ap.add_argument('--cf', action='store_true', help='CF card support (beta): plain CF card on an IDE adapter')
    ap.add_argument('--stock', action='store_true', help="Roland's stock OS (1.05 or EX 1.001) + --cf, no Rosetta")
    a = ap.parse_args()
    run(a.upd, a.out, a.img, stock=a.stock, cf=a.cf)


if __name__ == '__main__':
    main()
