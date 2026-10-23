import sys, os, time, threading
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), ".."))
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import numpy as np, tkinter as tk
import ps2core as core
import ps2_tracker as app_mod
app_mod.SAVE_FILE = os.path.abspath("gui_pulse_library.json")
app_mod.SETTINGS_FILE = os.path.abspath("gui_pulse_settings.json")
for p in (app_mod.SAVE_FILE, app_mod.SETTINGS_FILE):
    if os.path.exists(p): os.remove(p)
FORM = []
app_mod.ask_form = lambda *a, **k: FORM.pop(0) if FORM else None
for name in ("showinfo", "showwarning", "showerror"):
    setattr(app_mod.messagebox, name, lambda t, m, **k: print("MSG:", m[:120].replace("\n", " ")))
rng = np.random.default_rng(8)
MEM = np.zeros(core.EE_SIZE, np.uint8)
MEM[rng.integers(0, core.EE_SIZE, 1_000_000)] = rng.integers(0, 256, 1_000_000, dtype=np.uint8)
FV = MEM.view("<f4")
LOCK = threading.RLock()
class Fake:
    attached, exe, pid, profile = True, "pcsx2-qt.exe", 1, "ps2"
    regions = None
    def snapshot(self):
        with LOCK: return MEM.copy()
    def read(self, a, vt):
        with LOCK: return core.decode(vt, MEM[a:a + core.TYPES[vt][2]].tobytes())
    def write(self, a, vt, v):
        raw = core.encode(vt, v)
        with LOCK: MEM[a:a + len(raw)] = np.frombuffer(raw, np.uint8)
        return True
root = tk.Tk(); app = app_mod.App(root); app.ps2 = Fake()
def pump(sec):
    end = time.time() + sec
    while time.time() < end:
        root.update(); time.sleep(0.01)

SPEED, POS, ANIM_SPD, STEP_SND = 0x00800010, 0x00800020, 0x00900000, 0x00900040
anim = rng.choice(np.arange(0x200000, 0x600000), 30000, replace=False)
G = {"run": False, "alive": True}
def game():
    dt = 1 / 60
    while G["alive"]:
        with LOCK:
            sp = float(FV[SPEED // 4])
            target = 6.0 if G["run"] else 0.0
            sp = sp + (target - sp) * 0.25
            if abs(sp) < 1e-3: sp = 0.0
            FV[SPEED // 4] = sp
            FV[POS // 4] += sp * dt
            FV[ANIM_SPD // 4] = sp * 0.5 + 1.0               # walk-animation rate: also rises and returns
            FV[STEP_SND // 4] = (FV[STEP_SND // 4] + (0.3 if G["run"] else 0)) % 50
            FV[anim // 4] += rng.normal(0, 0.2, len(anim)).astype("<f4")
        time.sleep(dt)
threading.Thread(target=game, daemon=True).start()

app.ask_var.set("run speed"); app.make_plan()
assert app.plan["mode"] == "pulse", app.plan
app.coach_start(); pump(0.5)
for k in range(6):
    if not app.pulsing:
        break
    app._hotkey("rec_mark")
    G["run"] = True; pump(2.0); G["run"] = False
    pump(app.plan["pulse"]["post"] - 2.0 + 0.8)
print("pulse log:", app.pulser.log)
cands = app.pulser.candidates()
print("candidates:", [(f"{a:08X}", vt) for a, vt in cands][:10])
assert (SPEED, "float") in cands

with LOCK: n0 = float(FV[POS // 4])
G["run"] = True; pump(0.8); G["run"] = False
with LOCK: normal = float(FV[POS // 4]) - n0
pump(1.2)
print("normal run distance:", round(normal, 2))
app.group_test_start("hold")
for q in range(30):
    pump(0.3)
    if app.gt is None:
        break
    with LOCK: p0 = float(FV[POS // 4])
    G["run"] = True; pump(0.8); G["run"] = False
    with LOCK: p1 = float(FV[POS // 4])
    app._group_answer((p1 - p0) < 0.5 * normal)
    pump(1.2)
print("result:", app.coach_status.cget("text"))
assert f"FOUND IT: {SPEED:08X}" in app.coach_status.cget("text")

app.coach_tree.selection_set("0")
app.speed_hack_toggle(); pump(0.2)
with LOCK: p0 = float(FV[POS // 4])
G["run"] = True; pump(1.5); G["run"] = False
with LOCK: p1 = float(FV[POS // 4])
app.speed_hack_toggle(); pump(1.0)
with LOCK: q0 = float(FV[POS // 4])
G["run"] = True; pump(1.5); G["run"] = False
with LOCK: q1 = float(FV[POS // 4])
print(f"distance with hack {p1 - p0:.1f}, without {q1 - q0:.1f}")
assert 2.0 * (q1 - q0) < (p1 - p0) < 4.0 * (q1 - q0) + 1

G["alive"] = False
app.ask_var.set("ammo, I have 30"); app.make_plan()
P = app.ps2; AM = 0x00700000; P.write(AM, "u32", 30)
for extra in range(40):
    P.write(0x00710000 + extra * 64, "u32", 30)
app.coach_start(); pump(0.3)
ammo = 30
for _ in range(60):
    if app.coach.done: break
    if app.coach_wait == "number":
        ammo -= 1
        P.write(AM, "u32", ammo)
        for extra in range(40): P.write(0x00710000 + extra * 64, "u32", ammo)
        app.overlay.num.delete(0, "end"); app.overlay.num.insert(0, str(ammo)); app.overlay._send_number()
    pump(0.1)
left = app.coach.total
print("ammo search left:", left, "|", app.coach_status.cget("text"))
assert left > 3 and "What next" in app.coach_status.cget("text")
loops_before = app.coach.loops
app.coach_start()
assert app.coach.total == left and not app.coach.done and app.coach.loops == loops_before
root.destroy()
print("PULSE / TEST-WITH-ME / SPEED HACK / CONTINUE GUI TEST PASSED")
