import sys, os, time, threading
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), ".."))
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import numpy as np, tkinter as tk
import ps2core as core, coach
import ps2_tracker as app_mod
app_mod.SAVE_FILE = os.path.abspath("gui_fast_library.json")
app_mod.SETTINGS_FILE = os.path.abspath("gui_fast_settings.json")
for p in (app_mod.SAVE_FILE, app_mod.SETTINGS_FILE):
    if os.path.exists(p): os.remove(p)
for name in ("showinfo", "showwarning", "showerror"):
    setattr(app_mod.messagebox, name, lambda t, m, **k: print("MSG:", m[:120].replace("\n", " ")))
rng = np.random.default_rng(12)
MEM = np.zeros(core.EE_SIZE, np.uint8)
MEM[rng.integers(0, core.EE_SIZE, 1_500_000)] = rng.integers(0, 256, 1_500_000, dtype=np.uint8)
LOCK = threading.RLock()
class Fake:
    attached, exe, pid, profile = True, "rpcs3.exe", 1, "ps3"
    regions = None
    def snapshot(self):
        with LOCK: return MEM.copy()
    def read(self, a, vt):
        with LOCK: return core.decode(vt, MEM[a:a + core.TYPES[vt][2]].tobytes())
    def write(self, a, vt, v):
        raw = core.encode(vt, v)
        with LOCK: MEM[a:a + len(raw)] = np.frombuffer(raw, np.uint8)
        return True
root = tk.Tk(); app = app_mod.App(root); app.ps2 = P = Fake()
def pump(sec):
    end = time.time() + sec
    while time.time() < end:
        root.update(); time.sleep(0.01)
REAL = 0x01DC3DA0                       # the real ammo (u16), copies in a render buffer
COPIES = [0x00D7C000 + 0x40 * i for i in range(10)]
G = {"alive": True}
def game():
    while G["alive"]:
        a = P.read(REAL, "u16")
        for c in COPIES:
            P.write(c, "u32", a)        # HUD / render copies rebuilt from the real one every frame
        time.sleep(1 / 60)
P.write(REAL, "u16", 8)
threading.Thread(target=game, daemon=True).start()
pump(0.2)

# the plan Claude gave in the screenshot (with the separate "press ]" step)
plan = coach.validate_recipe({"title": "Weapon ammo", "category": "Weapons", "types": ["u32", "u16", "byte"],
    "steps": [{"say": "Equip a gun and stand still. Read the ammo number and type it.", "scan": "exact", "value": "ask", "until": "key"}],
    "loop": [{"say": "Fire a few shots (not reloading), then stop and press ].", "scan": None, "until": "key"},
             {"say": "Do nothing for a moment.", "scan": "unchanged", "secs": 1},
             {"say": "Type the ammo number now shown on the HUD, then press ].", "scan": "exact", "value": "ask", "until": "key"}],
    "target": 4, "max_loops": 8})
assert len(plan["loop"]) == 2, plan["loop"]
app.plan = plan
app.coach_start(); pump(0.3)
ammo, actions = 8, 0
t_end = time.time() + 120
while time.time() < t_end:
    pump(0.1)
    if "REAL one is" in app.coach_status.cget("text") or "Couldn't" in app.coach_status.cget("text"):
        break
    if app.coach_wait == "number" and app.coach and not app.coach.done:
        s = app.coach.current()["say"]
        if "Fire" in s:
            ammo -= 2 if ammo > 2 else -20
            P.write(REAL, "u16", ammo); actions += 1; pump(0.1)
        app.overlay.num.delete(0, "end"); app.overlay.num.insert(0, str(ammo)); app.overlay._send_number()
print("player fired", actions, "times |", app.coach_status.cget("text"), "| loops:", app.coach.loop_totals)
assert f"REAL one is {REAL:08X}" in app.coach_status.cget("text")
assert actions <= 4, actions

# freeze test: buttons visible + ] answers
app.group_test_start("hold"); pump(0.5)
ov = app.overlay
assert ov._choice_btns and all(b.winfo_ismapped() for b in ov._choice_btns)
assert ov._choice_btns[0].winfo_rooty() + ov._choice_btns[0].winfo_height() <= ov.winfo_rooty() + ov.winfo_height() + 1, "button cut off"
print("question:", ov.msg.cget("text"))
assert "Fire a few shots" in ov.msg.cget("text") and "press ]" not in ov.msg.cget("text").lower()
before = app.gt.asked
app._hotkey("rec_mark"); pump(0.8)                # ] = YES
assert app.gt is None or app.gt.asked == before + 1
G["alive"] = False
root.destroy()
print("FAST NARROWING / ANSWER KEYS GUI TEST PASSED")
