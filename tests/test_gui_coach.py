"""Headless test of the AI Coach tab + overlay with a fake PCSX2 running fake games."""
import sys, os, struct, threading, time
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), ".."))
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import tkinter as tk
import ps2core as core
import ps2_tracker as app_mod

app_mod.SAVE_FILE = os.path.abspath("gui_coach_library.json")
app_mod.SETTINGS_FILE = os.path.abspath("gui_coach_settings.json")
for p in (app_mod.SAVE_FILE, app_mod.SETTINGS_FILE):
    if os.path.exists(p):
        os.remove(p)

rng = np.random.default_rng(5)
MEM = np.zeros(core.EE_SIZE, dtype=np.uint8)
MEM[rng.integers(0, core.EE_SIZE, 1_500_000)] = rng.integers(0, 256, 1_500_000, dtype=np.uint8)
LOCK = threading.Lock()
FNOISE = rng.choice(core.EE_SIZE // 4, 30_000, replace=False)
FNOISE = FNOISE[np.abs(FNOISE - 0x00C00000 // 4) > 64]


class FakePcsx2:
    attached = True
    exe, pid, ee_base, base_source = "pcsx2-qt.exe", 1, 0x1000, "fake"

    def snapshot(self):
        with LOCK:
            return MEM.copy()

    def read(self, addr, vt):
        with LOCK:
            return core.decode(vt, MEM[addr:addr + core.TYPES[vt][2]].tobytes())

    def write(self, addr, vt, value):
        raw = core.encode(vt, value)
        with LOCK:
            MEM[addr:addr + len(raw)] = np.frombuffer(raw, dtype=np.uint8)
        return True


def put(addr, vt, v):
    FakePcsx2().write(addr, vt, v)


LOG = []
app_mod.messagebox.showinfo = lambda t, m: LOG.append(m)
app_mod.messagebox.showerror = lambda t, m: LOG.append(m)
app_mod.messagebox.showwarning = lambda t, m: LOG.append(m)

root = tk.Tk()
app = app_mod.App(root)
app.ps2 = FakePcsx2()


def pump(sec):
    end = time.time() + sec
    while time.time() < end:
        root.update()
        time.sleep(0.01)


stop_noise = False


def noise():
    while not stop_noise:
        with LOCK:
            fv = MEM.view("<f4")
            fv[FNOISE] = fv[FNOISE] * 0.98 + rng.normal(0, 1, len(FNOISE)).astype("<f4")
        time.sleep(0.05)


threading.Thread(target=noise, daemon=True).start()

# ======================= 1) "ammo, I have 40" through the overlay ======================
AMMO = 0x00456780
for d in (0x00100000, 0x00200040):
    put(d, "u32", 40)
put(AMMO, "u32", 40)
ammo = 40
app.ask_var.set("ammo, I have 40")
app.make_plan()
assert app.plan and app.plan["title"] == "Ammo", app.plan
plan_txt = app.plan_text.get("1.0", "end")
assert "Looking for ammo = 40" in plan_txt
app.coach_start()
pump(0.2)
assert app.overlay.winfo_viewable()
for _ in range(20):
    if app.coach.done:
        break
    s = app.coach.current()
    if app.coach_wait == "number":
        if "shoot" in s["say"]:
            ammo -= 3
        else:
            ammo += 12
        put(AMMO, "u32", ammo)
        assert app.overlay.num.winfo_ismapped()
        app.overlay.num.delete(0, "end"); app.overlay.num.insert(0, str(ammo))
        app.overlay._send_number()
    pump(0.3)
assert app.coach.done and not app.coach.failed, app.coach.history
rows = list(app.coach_rows.values())
print("ammo result:", [(vt, f"{a:08X}") for vt, a in rows], "| overlay:", app.overlay.msg.cget("text"))
assert ("u32", AMMO) in rows
app.coach_tree.selection_set(next(i for i, v in app.coach_rows.items() if v == ("u32", AMMO)))
app_mod.ask_form = lambda *a, **k: {"name": "Ammo", "category": "Weapons"}
app.coach_save()
assert app.library[-1]["name"] == "Ammo" and app.library[-1]["addr"] == AMMO

# ======================= 2) health with timers + ] key (speed up timers) ================
HP = 0x00876540
put(HP, "float", 100.0)
hp = 100.0
app.ask_var.set("health, I'm at full health")
app.make_plan()
for part in ("steps", "loop"):
    for s in app.plan[part]:
        if s["until"] == "timer":
            s["secs"] = 0.3
app.coach_start()
for _ in range(80):
    if app.coach.done:
        break
    if app.coach_wait == "key":
        s = app.coach.current()
        hp = hp - 15 if "Lose" in s["say"] else min(100.0, hp + 7)
        put(HP, "float", hp)
        app._hotkey("rec_mark")          # the ] key
    pump(0.25)
rows = list(app.coach_rows.values())
print("health result:", [(vt, f"{a:08X}") for vt, a in rows][:5], "|", app.coach_status.cget("text"))
assert ("float", HP) in rows

# ======================= 3) ball after a hit: fully automatic hunt =====================
BALL = 0x00C00000   # pos x,y,z vel x,y,z
plays = [3.0 + 5.5 * k for k in range(8)]
v0s = {p: (rng.uniform(-6, 6), rng.uniform(9, 14), rng.uniform(28, 40)) for p in plays}
sim = {"t0": None, "stop": False}


def ball_sim():
    t0 = time.perf_counter()
    sim["t0"] = t0
    while not sim["stop"]:
        t = time.perf_counter() - t0
        pos, vel = [0.0, 1.5, 18.0], [0.0, 0.0, 0.0]
        for p in plays:
            if p - 0.6 <= t < p:
                tt = t - (p - 0.6); vel = [0.0, -0.3, -30.0]; pos = [0.0, 1.5 - 0.3 * tt, 18 - 30 * tt]
            if p <= t < p + 5.0:
                tt = t - p; vx, vy, vz = v0s[p]; fl = 2 * vy / 9.8
                if tt < fl:
                    vel = [vx, vy - 9.8 * tt, vz]; pos = [vx * tt, 1.0 + vy * tt - 4.9 * tt * tt, vz * tt]
                else:
                    pos = [vx * fl, 0.0, vz * fl]
        with LOCK:
            MEM[BALL:BALL + 24] = np.frombuffer(struct.pack("<6f", *pos, *vel), dtype=np.uint8)
        time.sleep(1 / 60)


app.ask_var.set("ball speed after I hit it")
app.make_plan()
assert app.plan["mode"] == "event"
app.coach_start()
threading.Thread(target=ball_sim, daemon=True).start()
marked = set()
start = time.time()
while time.time() - start < plays[-1] + 4:
    if sim["t0"]:
        t = time.perf_counter() - sim["t0"]
        for p in plays:
            if p not in marked and t >= p + 0.1:
                app._hotkey("rec_mark"); marked.add(p)
    pump(0.02)
    if app.hunter and app.hunter.results and len(marked) >= 5:
        best = app.hunter.results[0]
        if best["addr"] in (BALL + 20, BALL + 4, BALL + 16) and best["score"] > 0.5:
            break
sim["stop"] = True
app.coach_stop()
res = app.hunter.results
print("\n".join(app.hunter.log[-4:]))
top = [(f"{r['addr']:08X}", r["kind"], r["score"]) for r in res[:5]]
print("ball top:", top)
kinds = {r["addr"]: r["kind"] for r in res}
assert kinds.get(BALL + 20) == "speed", kinds.get(BALL + 20)
assert any(v == ("float", BALL + 20) for v in app.coach_rows.values())
# send forward speed to Power boost
app.coach_tree.selection_set(next(i for i, v in app.coach_rows.items() if v == ("float", BALL + 20)))
app.coach_to_boost()
assert app.boost_axes[0].get() == f"{BALL + 20:08X}"
stop_noise = True
for tab in app.nb.tabs():
    app.nb.select(tab); pump(0.05)
root.destroy()
print("COACH GUI TEST PASSED")
