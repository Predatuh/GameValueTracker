import sys, os, struct, threading, time
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), ".."))
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import tkinter as tk
import ps2core as core
import ps2_tracker as app_mod

app_mod.SAVE_FILE = os.path.abspath("gui_eff_library.json")
app_mod.SETTINGS_FILE = os.path.abspath("gui_eff_settings.json")
for p in (app_mod.SAVE_FILE, app_mod.SETTINGS_FILE):
    if os.path.exists(p):
        os.remove(p)
rng = np.random.default_rng(9)
MEM = np.zeros(core.EE_SIZE, dtype=np.uint8)
MEM[rng.integers(0, core.EE_SIZE, 1_500_000)] = rng.integers(0, 256, 1_500_000, dtype=np.uint8)
LOCK = threading.RLock()


class FakePcsx2:
    attached = True
    exe, pid, ee_base, base_source = "pcsx2-qt.exe", 1, 0x1000, "fake"

    def snapshot(self):
        with LOCK:
            return MEM.copy()

    def read(self, a, vt):
        with LOCK:
            return core.decode(vt, MEM[a:a + core.TYPES[vt][2]].tobytes())

    def write(self, a, vt, v):
        raw = core.encode(vt, v)
        with LOCK:
            MEM[a:a + len(raw)] = np.frombuffer(raw, dtype=np.uint8)
        return True


P = FakePcsx2()
for name in ("showinfo", "showwarning", "showerror"):
    setattr(app_mod.messagebox, name, lambda t, m: print("MSG:", m))
root = tk.Tk()
app = app_mod.App(root)
app.ps2 = P


def pump(sec):
    end = time.time() + sec
    while time.time() < end:
        root.update()
        time.sleep(0.01)


# ---------------- the game: physics + HUD read real values from memory -----------------
AMMO, HUD = 0x00456780, 0x00456980
POS, VEL, VCOPY = 0x00C00000, 0x00C0000C, 0x00D00010
G = {"run": True, "plays": [], "t0": time.perf_counter(), "phase": None}
P.write(AMMO, "u32", 40)


def game():
    dt = 1 / 60
    while G["run"]:
        t = time.perf_counter() - G["t0"]
        with LOCK:
            P.write(HUD, "u16", P.read(AMMO, "u32"))                 # HUD drawn from real ammo
            p = [P.read(POS + 4 * i, "float") for i in range(3)]
            v = [P.read(VEL + 4 * i, "float") for i in range(3)]
            ph = None
            for k, pt in enumerate(G["plays"]):
                if pt - 0.6 <= t < pt:
                    ph = ("pitch", k)
                elif pt <= t < pt + 4.5:
                    ph = ("flight", k)
            if ph != G["phase"]:                                      # phase change events
                if ph and ph[0] == "pitch":
                    p, v = [0.0, 1.5, 18.0], [0.0, -0.3, -30.0]
                elif ph and ph[0] == "flight":
                    v = [rng.uniform(-5, 5), rng.uniform(9, 13), rng.uniform(26, 36)]
                    p = [0.0, 1.0, 0.0]
                else:
                    p, v = [0.0, 1.5, 18.0], [0.0, 0.0, 0.0]
                G["phase"] = ph
            if ph and (ph[0] == "pitch" or p[1] > 0):
                if ph[0] == "flight":
                    v[1] -= 9.8 * dt
                p = [p[i] + v[i] * dt for i in range(3)]
            elif ph and ph[0] == "flight":
                v = [0.0, 0.0, 0.0]
            for i in range(3):
                P.write(POS + 4 * i, "float", p[i]); P.write(VEL + 4 * i, "float", v[i])
                P.write(VCOPY + 4 * i, "float", v[i])                 # render copy
        time.sleep(dt)


threading.Thread(target=game, daemon=True).start()

# ================= 1) ammo: coach finds real + HUD, auto-test picks the real one =========
ammo = 40
app.ask_var.set("ammo, I have 40")
app.make_plan()
app.coach_start()
for _ in range(30):
    if app.coach.done:
        break
    if app.coach_wait == "number":
        s = app.coach.current()
        ammo += -3 if "shoot" in s["say"] else 10
        P.write(AMMO, "u32", ammo)
        pump(0.1)
        app.overlay.num.delete(0, "end"); app.overlay.num.insert(0, str(ammo))
        app.overlay._send_number()
    pump(0.2)
print("coach found:", [(vt, f"{a:08X}") for vt, a in app.coach_rows.values()])
pump(2.0)                                       # auto-test starts 1.5 s after "Found it"
t_end = time.time() + 20
while (app.testing or not app.test_results) and time.time() < t_end:
    pump(0.1)
print("DBG testing", app.testing, "results", len(app.test_results), "left", round(t_end - time.time(), 1)); notes = {a: app.coach_tree.set(i, "note") for i, (vt, a) in app.coach_rows.items()}
print("ammo tests:", {f"{a:08X}": n[:40] for a, n in notes.items()})
print("overlay:", app.overlay.msg.cget("text"))
assert notes[AMMO].startswith("TEST: CONTROLS"), notes
assert HUD not in notes or notes[HUD].startswith("TEST: COPY"), notes
assert "REAL one is 00456780" in app.overlay.msg.cget("text")
assert P.read(AMMO, "u32") == ammo, "value restored after test"

# ================= 2) ball: hunt, then auto-test between hits =============================
G["t0"] = time.perf_counter()
G["plays"] = [3.0 + 5.0 * k for k in range(16)]
app.ask_var.set("ball speed after I hit it")
app.make_plan()
app.coach_start()
marked = set()
start = time.time()
while time.time() - start < G["plays"][-1] + 3:
    t = time.perf_counter() - G["t0"]
    for pt in G["plays"]:
        if pt not in marked and t >= pt + 0.05:
            app._hotkey("rec_mark"); marked.add(pt)
    pump(0.02)
    if app.ball_test and app.ball_test["done"]:
        break
bt = app.ball_test
assert bt and bt["done"], ("tests not finished", bt and bt["queue"], len(marked))
print("ball candidates:", [f"{a:08X}" for a in bt["cands"]])
for r in core.rank_tests(bt["results"]):
    print(f"  {r['addr']:08X} {r['verdict']:9s} {r.get('note', '')}")
print("overlay:", bt["message"], "| hits used:", len(marked))
assert VCOPY + 8 in bt["cands"] and VEL + 8 in bt["cands"], "both real and copy were candidates"
assert app.boost_axes[0].get() == f"{VEL + 8:08X}", app.boost_axes[0].get()
assert all(cb.get() != f"{VCOPY + 8:08X}" for cb in app.boost_axes)
app.coach_stop()

# ================= 3) boost warns when pointed at the copy ==================================
for cb in app.boost_axes:
    cb.set("")
app.boost_axes[0].set(f"{VCOPY + 8:08X}")
app.boost_toggle()
G["t0"] = time.perf_counter(); G["plays"] = [1.0, 6.0]
pump(8)
print("boost status:", app.boost_info.cget("text").replace("\n", " | "))
assert "copy" in app.boost_warn, app.boost_warn
app.boost_toggle(); pump(0.3)
for cb in app.boost_axes:
    cb.set("")
app.boost_axes[0].set(f"{VEL + 8:08X}")
app.boost_toggle()
G["t0"] = time.perf_counter(); G["plays"] = [1.0]
far = 0.0
end = time.time() + 6
while time.time() < end:
    pump(0.05)
    far = max(far, P.read(POS + 8, "float"))
app.boost_toggle(); pump(0.2)
print(f"boosted ball went {far:.0f} m (normal is ~55-70 m); warning: {app.boost_warn!r}")
assert far > 120 and not app.boost_warn
G["run"] = False
root.destroy()
print("EFFECT GUI TEST PASSED")
