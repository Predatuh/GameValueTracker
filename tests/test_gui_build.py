"""Build a mod menu from one sentence; top-speed finder; code patches on RPCS3; dark mode; the ' key."""
import sys, os, time, threading, shutil, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import numpy as np, tkinter as tk
import ps2core as core
import theme
import ps2_tracker as app_mod
app_mod.SAVE_FILE = os.path.abspath("gui_build_library.json")
app_mod.SETTINGS_FILE = os.path.abspath("gui_build_settings.json")
for p in (app_mod.SAVE_FILE, app_mod.SETTINGS_FILE):
    if os.path.exists(p): os.remove(p)
FORM = []
app_mod.ask_form = lambda *a, **k: FORM.pop(0) if FORM else None
for name in ("showinfo", "showwarning", "showerror"):
    setattr(app_mod.messagebox, name, lambda t, m, **k: print("MSG:", m[:160].replace("\n", " ")))
rng = np.random.default_rng(21)
MEM = np.zeros(core.EE_SIZE, np.uint8)
MEM[rng.integers(0, core.EE_SIZE, 1_000_000)] = rng.integers(0, 256, 1_000_000, dtype=np.uint8)
FV = MEM.view("<f4")
LOCK = threading.RLock()


class Fake:
    attached, exe, pid, profile, be = True, "pcsx2-qt.exe", 1, "ps2", False
    regions = None
    def snapshot(self):
        with LOCK: return MEM.copy()
    def read(self, a, vt):
        with LOCK: return core.decode(vt, MEM[a:a + core.TYPES[vt][2]].tobytes())
    def write(self, a, vt, v):
        raw = core.encode(vt, v)
        with LOCK: MEM[a:a + len(raw)] = np.frombuffer(raw, np.uint8)
        return True
    def parse_addr(self, text, vt=None): return int(text, 16)
    def _xor(self, vt): return 0
    def _region(self, off): return None


root = tk.Tk(); app = app_mod.App(root); app.ps2 = P = Fake()
def pump(sec):
    end = time.time() + sec
    while time.time() < end:
        root.update(); time.sleep(0.01)


AMMO = 0x01DC3DA0
COPIES = [0x00D7C000 + 0x40 * i for i in range(10)]
SPEED, CAP = 0x00800010, 0x00810040
decoys = rng.choice(np.arange(0x00300000, 0x00600000, 4), 150, replace=False)
with LOCK:
    FV[CAP // 4] = 6.0
    FV[decoys // 4] = 6.0
    FV[SPEED // 4] = 0.0
P.write(AMMO, "u16", 30)
G = {"alive": True, "run": False}


def game():
    while G["alive"]:
        with LOCK:
            a = core.decode("u16", MEM[AMMO:AMMO + 2].tobytes())
            for c in COPIES:
                MEM[c:c + 4] = np.frombuffer(core.encode("u32", a), np.uint8)
            target = float(FV[CAP // 4]) if G["run"] else 0.0
            sp = float(FV[SPEED // 4])
            FV[SPEED // 4] = sp + (target - sp) * 0.2
        time.sleep(1 / 60)


threading.Thread(target=game, daemon=True).start()
pump(0.3)
app.library.append(core.new_value_entry("Run speed", "Running", SPEED, "float"))   # found earlier
app.library_changed()

# ---- one sentence -> plan -> build ----
app.build_var.set("infinite ammo on L1+R1, top speed x3")
app.build_plan()
assert [i["kind"] for i in app.build_items] == ["value", "topspeed"], app.build_items
assert "YOUR MENU (2 cheats" in app.build_lbl.cget("text")
app.build_start(); pump(0.5)
ammo, typed_first, t_end = 30, False, time.time() + 180
while time.time() < t_end and app.builder is not None:
    pump(0.1)
    if app.coach_wait == "number" and app.coach and not app.coach.done:
        if typed_first:
            ammo -= 1
            P.write(AMMO, "u16", ammo); pump(0.1)
        typed_first = True
        app.overlay.num.delete(0, "end"); app.overlay.num.insert(0, str(ammo)); app.overlay._send_number()
    elif app.pending_answer and getattr(app, "ts", None) and app.pending_answer[0] == app._ts_go:
        app._hotkey("rec_mark")                  # ] = go, then keep running
        G["run"] = True
print("builder:", app.build_lbl.cget("text"))
G["run"] = False
assert app.builder is None and "Mod menu built: 2 cheat(s)" in app.build_lbl.cget("text"), app.build_lbl.cget("text")
names = {c["name"]: c for c in app.cheats}
inf, top = names["Infinite ammo"], names["Top speed x3"]
lib = {e["name"]: e for e in app.library}
assert lib[inf["entry"]]["addr"] == AMMO and inf["mode"] == "freeze" and inf["hotkey"] == ["L1", "R1"]
assert lib[top["entry"]]["addr"] == CAP and top["value"] == 18.0 and top["mode"] == "freeze"
pump(0.5)
assert P.read(CAP, "float") == 6.0 and all(abs(FV[d // 4] - 6.0) < 1e-6 for d in decoys), "everything restored"
assert "Start mod menu" in [b.cget("text") for b in app.overlay._choice_btns]

# the top-speed cheat really makes you faster, and switching it off puts the setting back
top["on"] = True; G["run"] = True; pump(1.5)
fast = P.read(SPEED, "float")
top["on"] = False; app._restore_normal(top); pump(1.5)
slow = P.read(SPEED, "float")
G["run"] = False
print(f"top speed with cheat {fast:.1f}, without {slow:.1f}")
assert fast > 15 and abs(slow - 6.0) < 0.5 and P.read(CAP, "float") == 6.0

# ---- ' = NO works for questions (not only in the pitch predictor) ----
got = []
app.pending_answer = (lambda: got.append("yes"), lambda: got.append("no"))
app._hotkey("zone_ball")
assert got == ["no"] and app.pending_answer is None

# ---- code patch on RPCS3: add, try live, undo, install into RPCS3's patch file ----
P.profile = "ps3"
CODE = 0x00012340
P.write(CODE, "u32", 0x7C0802A6)
FORM.append({"name": "No ammo used", "addr": "00012340", "value": "60000000"})
app.add_code_patch()
i = next(k for k, c in enumerate(app.cheats) if c.get("code"))
assert app.cheats[i]["system"] == "ps3" and app.cheats[i]["value"] == 0x60000000
app.ch_tree.selection_set(str(i))
app.code_patch_live()
assert P.read(CODE, "u32") == 0x60000000 and "LIVE NOW" in app.ch_tree.set(str(i), "does")
app.ch_tree.selection_set(str(i))
app.code_patch_live()
assert P.read(CODE, "u32") == 0x7C0802A6
app.preview_pnach()
assert "be32, 0x00012340, 0x60000000" in app.pnach_text.get("1.0", "end")
d = tempfile.mkdtemp()
try:
    with open(os.path.join(d, "RPCS3.log"), "w", encoding="utf-8") as f:
        f.write("SYS: Title: Mercenaries 2\nSYS: Serial: BLUS30056\nAPP_VER=01.00\nPPU executable hash: PPU-abc123\n")
    app.settings["rpcs3_dir"] = d
    path = app.export_rpcs3_patch()
    txt = open(path, encoding="utf-8").read()
    print(txt)
    assert "PPU-abc123:" in txt and "BLUS30056: [ 01.00 ]" in txt and "be32, 0x00012340, 0x60000000" in txt
finally:
    shutil.rmtree(d)
P.profile = "pc"
FORM.append({"name": "x", "addr": "1000", "value": "90"})
app.add_code_patch()                      # PC: explains Cheat Engine instead
assert FORM, "no form for PC games"
FORM.clear()

# ---- dark mode: everything recolours, the in-game overlay keeps its own look ----
app.dark_var.set(True); app.toggle_theme(); pump(0.2)
dark = theme.PALETTES["dark"]
assert theme.mode() == "dark" and app.settings["theme"] == "dark"
assert app.plan_text.cget("background") == dark["surface"] and app.root.cget("background") == dark["bg"]
assert str(app.build_lbl.cget("foreground")) == dark["muted"]
assert app.overlay.cget("background") == app_mod.Overlay.BG
assert str(app.conn_label.cget("foreground")) == dark["ok"]
app.dark_var.set(False); app.toggle_theme(); pump(0.2)
assert app.plan_text.cget("background") == theme.PALETTES["light"]["surface"]
assert str(app.build_lbl.cget("foreground")) == theme.PALETTES["light"]["muted"]
# ---- jump hunts: pressing jump (Cross / A) on the controller counts as ], once per press ----
class FakePad:
    available, held = True, set()
    def pressed(self): return set(self.held)
marks = []
app.pulse_mark = lambda: marks.append(time.time())
app.pulsing, app.pulse_busy = True, False
pad, tok = FakePad(), app.coach_token
threading.Thread(target=app._pulse_pad_watch, args=(pad, tok), daemon=True).start()
pump(0.2)
pad.held = {"Cross"}; pump(0.3)              # held down: still one try
pad.held = set(); pump(0.2)
pad.held = {"Square"}; pump(0.2)             # other buttons do nothing
pad.held = {"Cross"}; pump(0.2)
assert len(marks) == 2, marks
app.coach_token += 1; app.pulsing = False; pump(0.1)
del app.pulse_mark

# ---- updates: a late check can't cover "Downloading...", and "nothing new" doesn't restart (no loop) ----
app._update_available("2026.10.24.1", "2026.10.23.3"); pump(0.1)
assert app.update_bar.winfo_manager() and "Update ready" in app.update_lbl.cget("text")
app._updating = True
app.update_lbl.configure(text="Downloading the update...")
app._update_available("2026.10.24.1", "2026.10.23.3")
assert app.update_lbl.cget("text") == "Downloading the update..."
app._update_done([], "2026.10.24.1"); pump(0.1)
assert not app._updating and not app.update_bar.winfo_manager() and "up to date" in app.status.get()
app._updating = True
app._update_failed("GitHub error 500")
assert not app._updating and "try again" in app.update_lbl.cget("text")
G["alive"] = False
root.destroy()
for p in (app_mod.SAVE_FILE, app_mod.SETTINGS_FILE):
    if os.path.exists(p): os.remove(p)
print("BUILD / TOP SPEED / CODE PATCH / THEME GUI TEST PASSED")
