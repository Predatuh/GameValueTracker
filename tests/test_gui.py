"""Headless smoke test of the tracker UI against a fake PCSX2 with a simulated game."""
import sys, os, struct, threading, time, json
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), ".."))
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import tkinter as tk
import ps2core as core
import ps2_tracker as app_mod

app_mod.SAVE_FILE = os.path.abspath("gui_test_library.json")
if os.path.exists(app_mod.SAVE_FILE):
    os.remove(app_mod.SAVE_FILE)

rng = np.random.default_rng(3)
MEM = np.zeros(core.EE_SIZE, dtype=np.uint8)
MEM[rng.integers(0, core.EE_SIZE, 300000)] = rng.integers(0, 256, 300000, dtype=np.uint8)
BASE, STRIDE, N = 0x00A31240, 0x88, 100
OFFS = {"SPD": 0x10, "ACC": 0x11, "STR": 0x14, "KPW": 0x1C, "KAC": 0x1D, "AWR": 0x20}
for i in range(N):
    vals = rng.choice(np.arange(40, 100), size=len(OFFS), replace=False)
    for (k, off), v in zip(OFFS.items(), vals):
        MEM[BASE + i * STRIDE + off] = v
COPY = 0x01200000
MEM[COPY:COPY + N * STRIDE] = MEM[BASE:BASE + N * STRIDE]
BALL = 0x00650100  # pos x,y,z then vel x,y,z (floats)
LOCK = threading.Lock()


class FakePcsx2:
    attached = True
    exe, pid, ee_base, base_source = "pcsx2-qt.exe", 1234, 0x150C14D0000, "fake"

    def attach(self, manual=None):
        pass

    def snapshot(self):
        with LOCK:
            return MEM.copy()

    def read(self, addr, vtype):
        size = core.TYPES[vtype][2]
        with LOCK:
            return core.decode(vtype, MEM[addr:addr + size].tobytes())

    def write(self, addr, vtype, value):
        raw = core.encode(vtype, value)
        with LOCK:
            MEM[addr:addr + len(raw)] = np.frombuffer(raw, dtype=np.uint8)
        return True


def set_f(addr, v):
    with LOCK:
        MEM[addr:addr + 4] = np.frombuffer(struct.pack("<f", v), dtype=np.uint8)


# ---- auto answers for dialogs ----------------------------------------------
LOG = []
FORM_ANSWERS = []


def fake_form(parent, title, fields, extra=None):
    ans = FORM_ANSWERS.pop(0)
    LOG.append(("form", title, ans))
    return ans


app_mod.ask_form = fake_form
for name in ("showinfo", "showwarning", "showerror"):
    setattr(app_mod.messagebox, name, lambda t, m, _n=name: LOG.append((_n, m)))
app_mod.messagebox.askyesno = lambda t, m: (LOG.append(("ask", m)) or True)

root = tk.Tk()
app = app_mod.App(root)
app.ps2 = FakePcsx2()
root.update()


def pump(sec=0.1):
    end = time.time() + sec
    while time.time() < end:
        root.update()
        time.sleep(0.01)


# ---- ratings finder: edit method ------------------------------------------
def pin(player, which):
    a = BASE + player * STRIDE + OFFS["SPD"]
    old = int(MEM[a])
    app.ed_old.delete(0, "end"); app.ed_old.insert(0, str(old))
    app.edit_snapshot()
    MEM[a] = old + 1                        # "change it in Edit Player"
    app.ed_new.delete(0, "end"); app.ed_new.insert(0, str(old + 1))
    app.edit_find()
    hits = list(app.ed_hits.get(0, "end"))
    assert hits == [f"{a:08X}"], hits
    app.ed_hits.selection_set(0)
    app.set_anchor(which)


def ratings_text(player):
    return "\n".join(f"{k}={int(MEM[BASE + player * STRIDE + o])}" for k, o in OFFS.items())


pin(10, 1)
pin(55, 2)
app.p1_text.delete("1.0", "end"); app.p1_text.insert("1.0", ratings_text(10))
app.p2_text.delete("1.0", "end"); app.p2_text.insert("1.0", ratings_text(55))
app.find_table_exact()
assert app.found and app.found["stride"] == STRIDE and app.found["count"] == N, app.found
FORM_ANSWERS.append({"name": "Player ratings", "category": "Ratings"})
app.save_found_table()
assert app.library[-1]["kind"] == "table"
pump(0.2)

# ---- auto search ------------------------------------------------------------
app.find_table_auto()
assert app.found and app.found["stride"] == STRIDE, app.found
print("ratings finder OK (exact + auto)")

# ---- library: edit, verify, copies ------------------------------------------
tbl = app.library[-1]
app.show_record.set(3)
app.rebuild_library_tree()
spd_iid = next(i for i, (e, f) in app.lib_items.items() if e is tbl and f == "SPD")
app.lib_tree.selection_set(spd_iid)
FORM_ANSWERS.append({"value": "77"})
app.lib_edit_value()
pump(0.8)
assert MEM[BASE + 3 * STRIDE + OFFS["SPD"]] == 77
app.lib_find_copies()
assert tbl.get("mirrors"), LOG[-1]
FORM_ANSWERS.append({"value": "88"})
app.lib_tree.selection_set(next(i for i, (e, f) in app.lib_items.items() if e is tbl and f == "SPD"))
app.lib_edit_value()
pump(0.8)
assert MEM[BASE + 3 * STRIDE + OFFS["SPD"]] == 88 and MEM[COPY + 3 * STRIDE + OFFS["SPD"]] == 88
print("library edit + copies OK")

# ---- a value the "game" keeps resetting -> freeze offer ----------------------
RESET = 0x00700000
stop_reset = False


def game_resets():
    while not stop_reset:
        with LOCK:
            MEM[RESET:RESET + 4] = np.frombuffer(struct.pack("<I", 5), dtype=np.uint8)
        time.sleep(0.05)


threading.Thread(target=game_resets, daemon=True).start()
app.library.append(core.new_value_entry("Reset me", "Other", RESET, "u32"))
app.library_changed()
iid = next(i for i, (e, f) in app.lib_items.items() if e["name"] == "Reset me")
app.lib_tree.selection_set(iid)
FORM_ANSWERS.append({"value": "500"})
app.lib_edit_value()
pump(1.0)
assert any(x[0] == "ask" and "changed" in x[1] for x in LOG), LOG[-3:]
assert app.library[-1]["freeze"] and app.library[-1]["freeze_value"] == 500
stop_reset = True
print("revert detection + freeze OK")

# ---- scanner ------------------------------------------------------------------
SC = 0x00400010
FakePcsx2().write(SC, "u32", 30)
app.sc_type.set("u32"); app.sc_first_mode.set("exact")
app.sc_value.delete(0, "end"); app.sc_value.insert(0, "30")
app.first_scan()
FakePcsx2().write(SC, "u32", 29)
app.sc_next_mode.set("exact"); app.sc_value.delete(0, "end"); app.sc_value.insert(0, "29")
app.next_scan()
assert str(SC) in app.sc_tree.get_children(), app.sc_tree.get_children()[:5]
app.sc_tree.selection_set(str(SC))
FORM_ANSWERS.append({"name": "Kick meter", "category": "Kicking"})
app.add_scan_to_library()
print("scanner OK")

# ---- recorder: simulated fly balls ------------------------------------------------
for off in range(0, 24, 4):
    set_f(BALL + off, 0.0)
set_f(BALL + 4, 1.0)
app.watch_clear()
for a in (BALL + 4, BALL + 0x10, 0x01FD5744, 0x0183F1D4):
    app._add_watch(a, "float", f"cand {a:08X}")
app._refresh_watch_tree()
app.w_tree.selection_set("0")
app.watch_neighbours()
assert any(w["addr"] == BALL + 0x14 for w in app.watch)

sim_stop = False
hit_times = []


def game_sim():
    t0 = time.perf_counter()
    plays = [1.0, 4.0, 7.0]
    while not sim_stop:
        now = time.perf_counter() - t0
        set_f(0x01FD5744, float(rng.normal(0, 3)))  # stack junk
        h, vy, vx = 1.0, 0.0, 0.0
        for p in plays:
            tt = now - p
            if 0 <= tt < 2.5:
                v0 = 12.0
                hh = 1 + v0 * tt - 4.9 * tt * tt
                if hh > 0:
                    h, vy, vx = hh, v0 - 9.8 * tt, 30.0 * np.exp(-0.3 * tt)
                else:
                    h, vy, vx = 0.0, 0.0, 0.0
        set_f(BALL + 4, h); set_f(BALL + 0x10, vy); set_f(BALL + 0x0C, vx)
        time.sleep(1 / 60)


app.rec_toggle()
threading.Thread(target=game_sim, daemon=True).start()
start = time.time()
marks_done = set()
while time.time() - start < 9.5:
    el = time.time() - start
    for p in (1.0, 4.0, 7.0):
        if el >= p and p not in marks_done:
            app.rec_mark(); marks_done.add(p)
    pump(0.01)
app.rec_toggle()
pump(0.6)
sim_stop = True
res = app.rec_results
top = [(f"{app.rec_data['watch'][r['key']]['addr']:08X}", r["kind"], r["score"]) for r in res[:4]]
print("recorder ranking:", top)
kinds = {app.rec_data["watch"][r["key"]]["addr"]: r["kind"] for r in res}
assert kinds[BALL + 4] == "height", kinds
assert kinds[BALL + 0x10] == "vspeed", kinds
assert kinds[0x01FD5744] in ("noise", "active", "static"), kinds
assert res[0]["score"] >= 0.25
assert len(app.plot.find_all()) > 10
app.r_tree.selection_set(str(res[0]["key"]))
FORM_ANSWERS.append({"name": "Ball height", "category": "Game State"})
app.rec_save()
print("recorder OK")

# ---- cheats -------------------------------------------------------------------
app.library.append(core.new_value_entry("Pad", "Controller", 0x003A0000, "u16"))
FORM_ANSWERS.append({"name": "All 99 speed", "target": "Player ratings › SPD", "record": "all",
                     "value": "99", "act_entry": "Pad", "act_value": "FEFF"})
app.add_cheat()
text = app.pnach_text.get("1.0", "end")
assert "[All 99 speed]" in text and "E0" in text, text[:300]
# full-roster copy means 2 writes per player
assert text.count("extended,00000063") == 2 * N, text.count("extended,00000063")
print("cheat maker OK")


# ---- power boost -----------------------------------------------------------------
VEL = 0x00B76A20
for off in (0, 4, 8):
    set_f(VEL + off, 0.0)
app.library.append(core.new_value_entry("Ball fwd speed", "Game State", VEL, "float"))
app._boost_refresh_lists()
app.boost_axes[0].set("Ball fwd speed")
app.boost_axes[1].set(f"{VEL + 4:08X}")
app.boost_factor.set(3.0)
app.boost_toggle()
pump(0.3)
# pitch toward plate (should NOT boost)
set_f(VEL, -35.0); set_f(VEL + 4, -0.5)
pump(0.4)
assert app.booster.count == 0, app.booster.count
# bat contact: reverses direction
set_f(VEL, 40.0); set_f(VEL + 4, 12.0)
pump(0.4)
fwd = FakePcsx2().read(VEL, "float"); up = FakePcsx2().read(VEL + 4, "float")
assert app.booster.count == 1 and abs(fwd - 120) < 1e-3 and abs(up - 36) < 1e-3, (app.booster.count, fwd, up)
app.boost_toggle()
pump(0.3)
assert not app.boosting
set_f(VEL, 10.0)
app.boost_now()
assert abs(FakePcsx2().read(VEL, "float") - 30) < 1e-3
print("power boost OK:", app.boost_info.cget("text"))

# ---- save / reload ---------------------------------------------------------------
app.save_library(app_mod.SAVE_FILE)
data = json.load(open(app_mod.SAVE_FILE))
assert len(data["library"]) == len(app.library) and data["cheats"]
for tab in app.nb.tabs():
    app.nb.select(tab); pump(0.05)
root.destroy()
print("GUI SMOKE TEST PASSED")
