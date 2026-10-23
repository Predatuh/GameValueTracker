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
POWER, DIRV, FT = 0x00E00000, 0x00E00010, 0x00E00020
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
                    d = np.array([rng.uniform(-.15, .15), 0.35, 1.0]); d /= np.linalg.norm(d)
                    for i in range(3):
                        P.write(DIRV + 4 * i, "float", float(d[i]))
                    P.write(POWER, "float", rng.uniform(30, 38)); P.write(FT, "float", 0.0)
                    v = list(d * P.read(POWER, "float"))
                    p = [0.0, 1.0, 0.0]
                else:
                    p, v = [0.0, 1.5, 18.0], [0.0, 0.0, 0.0]
                G["phase"] = ph
            if ph and (ph[0] == "pitch" or p[1] > 0):
                if ph[0] == "flight":                      # rebuilt every frame (writes to v do nothing)
                    ft = P.read(FT, "float") + dt
                    P.write(FT, "float", ft)
                    pw = P.read(POWER, "float")
                    v = [P.read(DIRV + 4 * i, "float") * pw for i in range(3)]
                    v[1] -= 9.8 * ft
                p = [p[i] + v[i] * dt for i in range(3)]
            elif ph and ph[0] == "flight":
                v = [0.0, 0.0, 0.0]
            for i in range(3):
                P.write(POS + 4 * i, "float", p[i]); P.write(VEL + 4 * i, "float", v[i])
                P.write(VCOPY + 4 * i, "float", v[i])                 # render copy
        time.sleep(dt)


threading.Thread(target=game, daemon=True).start()


G["t0"] = time.perf_counter()
G["plays"] = [3.0 + 4.5 * k for k in range(40)]
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
    if app.deep and app.deep["done"]:
        break
d = app.deep
print("quick test:", app.ball_test and [(f"{r['addr']:08X}", r["verdict"]) for r in core.rank_tests(app.ball_test["results"])])
assert d and d["done"], ("deep test did not finish", d and d["gt"].log[-5:], len(marked))
print("\n".join(d["gt"].log[-5:]))
print("overlay:", d["message"], "| hits used:", len(marked))
assert d["gt"].found and any(a in (POWER, DIRV, DIRV + 4, DIRV + 8) for a, _ in d["gt"].found), d["gt"].found
assert app.boost_axes[0].get() in [f"{x:08X}" for x in (POWER, DIRV, DIRV + 4, DIRV + 8)], app.boost_axes[0].get()
assert app.boost_trigger.get() == app_mod.BOOST_TRIGGERS[1]
app.coach_stop(); pump(0.3)

# boost the hidden power value: ball must fly much farther
app.boost_toggle()
G["t0"] = time.perf_counter(); G["plays"] = [1.0]
far = 0.0
end = time.time() + 5
while time.time() < end:
    pump(0.05)
    far = max(far, P.read(POS + 8, "float"))
app.boost_toggle(); pump(0.2)
print(f"boosted ball went {far:.0f} m (normal ~55-75 m), boosts: {app.booster.count}")
assert far > 120
G["run"] = False
root.destroy()
print("DEEP GUI TEST PASSED")
