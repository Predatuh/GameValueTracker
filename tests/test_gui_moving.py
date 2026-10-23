import sys, os, struct, time, threading
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), ".."))
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import numpy as np, tkinter as tk
import ps2core as core
import ps2_tracker as app_mod

app_mod.SAVE_FILE = os.path.abspath("gui_mov_library.json")
app_mod.SETTINGS_FILE = os.path.abspath("gui_mov_settings.json")
for p in (app_mod.SAVE_FILE, app_mod.SETTINGS_FILE):
    if os.path.exists(p): os.remove(p)
FORM = []
app_mod.ask_form = lambda *a, **k: FORM.pop(0) if FORM else None
for name in ("showinfo", "showwarning", "showerror"):
    setattr(app_mod.messagebox, name, lambda t, m, **k: print("MSG:", m[:120].replace("\n", " ")))
rng = np.random.default_rng(3)
MEM = np.zeros(core.EE_SIZE, np.uint8)
MEM[rng.integers(0, core.EE_SIZE, 1_000_000)] = rng.integers(0, 256, 1_000_000, dtype=np.uint8)
LOCK = threading.RLock()

class Fake:
    attached, exe, pid, profile = True, "pcsx2-qt.exe", 1, "ps2"
    regions = None
    def snapshot(self):
        with LOCK: return MEM.copy()
    def read(self, a, vt):
        with LOCK: return core.decode(vt, MEM[a:a + core.TYPES[vt][2]].tobytes())
    def read_block(self, off, n):
        with LOCK: return MEM[off:off + n].copy()
    def write(self, a, vt, v):
        raw = core.encode(vt, v)
        with LOCK: MEM[a:a + len(raw)] = np.frombuffer(raw, np.uint8)
        return True
root = tk.Tk(); app = app_mod.App(root); app.ps2 = Fake()
def pump(sec):
    end = time.time() + sec
    while time.time() < end:
        root.update(); time.sleep(0.01)
P = app.ps2
# player struct with health as a float (real), the HUD keeps a u32 copy, ammo is a byte
STRUCT = 0x00A00000
REAL, HUD, AMMO = STRUCT + 12, 0x00C00010, STRUCT + 40
blob = struct.pack("<IIff", 0xBEEF, 7, 150.0, 100.0) + b"PLAYER01" + bytes(range(16)) + bytes([30]) + bytes(40)
MEM[STRUCT:STRUCT + len(blob)] = np.frombuffer(blob, np.uint8)
DECOY = STRUCT + 36          # a byte in the same struct that just happens to equal 100 (nothing reads it)
P.write(DECOY, "byte", 100)
G = {"run": True}
def game():
    while G["run"]:
        with LOCK:
            hp = struct.unpack("<f", MEM[REAL:REAL + 4].tobytes())[0]
        P.write(HUD, "u32", int(hp))            # HUD drawn from the real float every frame
        time.sleep(1 / 60)
threading.Thread(target=game, daemon=True).start()

# ---------------- 1) scanner, any type -------------------------------------------------------
app.sc_type.set(app_mod.ANY_TYPE); app.sc_first_mode.set("unknown")
app.first_scan("unknown")
for hp, mode in ((80, "decreased"), (60, "decreased"), (90, "increased"), (90, "unchanged"), (45, "decreased")):
    P.write(REAL, "float", float(hp)); P.write(AMMO, "byte", hp // 3); pump(0.1)
    app.next_scan(mode)
ids = app.sc_tree.get_children()
print("scanner rows:", [app.sc_tree.item(i, "values")[0] for i in ids][:8])
assert f"float:{REAL}" in ids and f"u32:{HUD}" in ids
# freeze from the scanner, set a value, quick-add without naming
app.sc_tree.selection_set((f"float:{REAL}", f"u32:{HUD}"))
app.scan_toggle_freeze()
assert app.sc_tree.set(f"float:{REAL}", "frozen").startswith("FROZEN")
P.write(REAL, "float", 10.0); pump(0.3)
assert P.read(REAL, "float") == 45.0, "frozen value kept"
app.sc_tree.selection_set((f"float:{REAL}",))
FORM.append({"value": "66"}); app.scan_set_value(); pump(0.3)
assert P.read(REAL, "float") == 66.0 and app.sc_frozen[(REAL, "float")] == 66.0
app.scan_unfreeze_all()
app.sc_tree.selection_set((f"u32:{HUD}", f"u16:{HUD}"))
app.scan_quick_add()
assert [e["name"] for e in app.library[-2:]] == ["Unnamed 1 (u32)", "Unnamed 1 (u16)"] or \
       [e["name"] for e in app.library[-2:]] == ["Unnamed 1 (u32)", "Unnamed 2 (u16)"], [e["name"] for e in app.library]
assert app.library[-1]["category"] == "Unsorted"
del app.library[-2:]
P.write(REAL, "float", 45.0); pump(0.2)
app.sc_tree.selection_set(f"float:{REAL}")
FORM.append({"name": "Health", "category": "Health"}); app.add_scan_to_library()
assert app.library[-1]["type"] == "float" and app.library[-1]["addr"] == REAL
pump(1.0)
assert app.library[-1].get("fp"), "fingerprinted when saved"

# ---------------- 2) recorder: shoot twice, reload ------------------------------------------
app.watch_clear()
for a, vt in ((AMMO, "byte"), (HUD, "u32"), (DECOY, "byte"), (REAL, "float")):
    app._add_watch(a, vt, f"w{a:X}")
app.rec_event.set(core.EVENT_RECIPES["shoot"]["label"])
P.write(AMMO, "byte", 30)
app.rec_toggle(); pump(0.8)
ammo = 30
for i in range(6):
    step, exp = app._rec_step(len(app.rec_data["marks"]))
    ammo = ammo - 1 if exp == -1 else 30
    P.write(AMMO, "byte", ammo)
    app.rec_mark(); pump(1.3)
app.rec_toggle(); pump(0.6)
best = app.rec_data["watch"][app.rec_results[0]["key"]]
print("recorder:", [(app.rec_data["watch"][r["key"]]["name"], r["kind"], r["score"]) for r in app.rec_results])
assert best["addr"] == AMMO and app.rec_results[0]["kind"] == "counter"

# ---------------- 3) auto-test: decoy kept -> you say NO -> neighbours -> real float -----------
app.plan = {"category": "Health", "steps": [], "loop": [], "title": "Health"}
app._show_coach_results([("u32", HUD, 45), ("byte", DECOY, 100)])
P.write(REAL, "float", 100.0); pump(0.2)
app.auto_test_scan()
t0 = time.time()
answered = 0
while time.time() - t0 < 40:
    pump(0.1)
    if app.overlay.yes_btn.winfo_ismapped():
        print("overlay asks:", app.overlay.msg.cget("text"))
        answered += 1
        app.overlay.no_btn.invoke()
    if "REAL one is" in app.coach_status.cget("text") or "Couldn't pin" in app.coach_status.cget("text"):
        break
print("result:", app.coach_status.cget("text"))
assert answered >= 1 and f"REAL one is {REAL:08X}" in app.coach_status.cget("text")
assert P.read(DECOY, "byte") == 100, "decoy restored after the on-screen check"

# ---------------- 4) the game restarts: the player struct is somewhere else -------------------
ent = next(e for e in app.library if e["name"] == "Health")
G["run"] = False; pump(0.1)
NEW = 0x01234560
with LOCK:
    seg = MEM[STRUCT:STRUCT + len(blob)].copy()
    MEM[STRUCT:STRUCT + len(blob)] = 0
    MEM[NEW:NEW + len(blob)] = seg
import numpy as _n; _s = P.snapshot(); print("DBG score old", core.fp_score(_s, ent["fp"], ent["addr"]), "new", core.fp_score(_s, ent["fp"], NEW + 12), "hits", core.fp_find(_s, ent["fp"], 0.5)[:3])
app.relocate_all(report=True)
pump(2.0)
print("status:", app.status.get())
assert ent["addr"] == NEW + 12 and ent.get("moved") == 1
assert "moved" in app._moves_text(ent)
# mark as moving -> pointer paths found (static pointer to the struct)
P.write(0x00300040, "u32", NEW)
app.lib_items_rev = None
iid = next(i for i, (e, f) in app.lib_items.items() if e is ent)
app.lib_tree.selection_set(iid); app.lib_toggle_moving(); pump(3.0)
assert ent["moving"] and any(b == 0x00300040 for b, p in ent["paths"]), ent.get("paths", [])[:5]
# while playing, a respawn moves it again: the live watcher follows the pointer
NEW2 = 0x01300000
with LOCK:
    seg = MEM[NEW:NEW + len(blob)].copy(); MEM[NEW:NEW + len(blob)] = 0; MEM[NEW2:NEW2 + len(blob)] = seg
P.write(0x00300040, "u32", NEW2)
pump(2.6)
assert ent["addr"] == NEW2 + 12, f"{ent['addr']:08X}"
root.destroy()
print("MOVING / ANY-TYPE / EVENTS / NEIGHBOUR GUI TEST PASSED")
