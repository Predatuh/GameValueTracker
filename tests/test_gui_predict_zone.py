import sys, os, threading, time
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), ".."))
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import tkinter as tk
import ps2core as core
import ps2_tracker as app_mod

app_mod.SAVE_FILE = os.path.abspath("gui_pred_library.json")
app_mod.SETTINGS_FILE = os.path.abspath("gui_pred_settings.json")
for p in (app_mod.SAVE_FILE, app_mod.SETTINGS_FILE):
    if os.path.exists(p):
        os.remove(p)
rng = np.random.default_rng(4)
NF = core.EE_SIZE // 4
MEM = np.zeros(core.EE_SIZE, dtype=np.uint8)
MEM[rng.integers(0, core.EE_SIZE, 1_500_000)] = rng.integers(0, 256, 1_500_000, dtype=np.uint8)
FV = MEM.view("<f4")
LOCK = threading.RLock()
BALL, TGT, MITT = 3_000_000, 3_100_000, 3_100_040
anim = rng.choice(NF, 60_000, replace=False)
anim = anim[(np.abs(anim - BALL) > 10) & (np.abs(anim - TGT) > 50)]


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


for name in ("showinfo", "showwarning", "showerror"):
    setattr(app_mod.messagebox, name, lambda t, m: print("MSG:", m))
root = tk.Tk()
app = app_mod.App(root)
app.ps2 = FakePcsx2()


def pump(sec):
    end = time.time() + sec
    while time.time() < end:
        root.update()
        time.sleep(0.01)


CYCLE, WIND = 4.2, 1.8
ZX = [-0.5, 0.0, 0.5] * 3; ZY = [1.3] * 3 + [0.9] * 3 + [0.5] * 3
pitches = []
for k in range(24):
    z = int(rng.integers(0, 9))
    pitches.append({"start": 1.0 + k * CYCLE, "zone": z, "tx": ZX[z], "ty": ZY[z], "hit": bool(rng.random() < 0.5)})
STATE = 3_200_000
G = {"run": True, "t0": None}


def k_of(p):
    return pitches.index(p)


def game():
    G["t0"] = time.perf_counter()
    while G["run"]:
        t = time.perf_counter() - G["t0"]
        cur = next((p for p in pitches if p["start"] <= t < p["start"] + CYCLE), None)
        with LOCK:
            FV[anim] += rng.normal(0, 0.3, len(anim)).astype("<f4")
            if cur:
                tt = t - cur["start"]
                tgt = (cur["tx"], cur["ty"])
                if tt < WIND:
                    pos = (0.3 * np.sin(tt * 4), 1.8 + 0.4 * np.sin(tt * 3), 18.0 - 0.2 * np.sin(tt * 2))
                    m = min(1, tt / WIND)
                    mitt = (tgt[0] * m, 1 + (tgt[1] - 1) * m)
                else:
                    ft = tt - WIND
                    a = min(1.0, ft / 0.45)
                    pos = (tgt[0] * a, 1.8 + (tgt[1] - 1.8) * a, 18.0 * (1 - a))
                    if cur["hit"] and ft > 0.45:
                        b = ft - 0.45
                        pos = (tgt[0] + 3 * b, tgt[1] + 8 * b, 30 * b)
                    mitt = tgt
                FV[BALL:BALL + 3] = pos
                MEM.view("<u4")[STATE] = 2 | (cur["zone"] << 8) | (int(k_of(cur)) % 4 << 16)
        time.sleep(1 / 60)


app.ask_var.set("i want to know where the pitcher is gonna throw the ball before he does so i know to swing or not")
app.make_plan()
assert app.plan["mode"] == "predict", app.plan
print(app.plan_text.get("1.0", "3.0").strip())
app.coach_start()
threading.Thread(target=game, daemon=True).start()
pump(0.3)
marked, checks, strikes_labeled = set(), [], 0
LBL = set()
end = time.time() + pitches[-1]["start"] + CYCLE
while time.time() < end:
    t = time.perf_counter() - G["t0"]
    for k, p in enumerate(pitches):
        rel = p["start"] + WIND
        if k not in marked and t >= rel + rng.uniform(-0.05, 0.08):
            app._hotkey("rec_mark"); marked.add(k)
        # mid-wind-up: what does the overlay show?
        mid = p["start"] + 0.9
        if app.predictor.phase == "ready" and abs(t - mid) < 0.12 and k not in [c[0] for c in checks]:
            pump(0.1)
            checks.append((k, app.last_pred, p["tx"], p["ty"], app.overlay._plate_on))
        # after the pitch lands, tell it strike/ball for a few pitches (inner area = strike)
        if app.predictor.phase == "ready" and abs(t - (rel + 0.8)) < 0.08 and strikes_labeled < 12 and k not in LBL:
            inside = abs(p["tx"]) < 0.35 and 0.6 < p["ty"] < 1.2
            app._hotkey("zone_strike" if inside else "zone_ball"); strikes_labeled += 1; LBL.add(k)
    pump(0.01)
G["run"] = False
lp = app.predictor
print("\n".join(lp.log[-40:])); print("SL", None if lp.shortlist is None else len(lp.shortlist), lp.sl_tracked, None if lp.sl_good is None else int((lp.sl_good>=lp.sl_tracked).sum()), BALL+2 in set(lp.ball_cand.tolist()) if lp.ball_cand is not None else None)
print("zone model:", lp.zone and (f"{lp.zone['addr']:08X}", lp.zone["part"]), "candidates:", lp.candidates)
assert lp.phase == "ready"
assert lp.zone and lp.zone["addr"] == STATE * 4 and lp.zone["part"] == "b1"
assert len(checks) >= 3, checks
checks = [c for c in checks if c[1]]
for k, pred, tx, ty, plate_on in checks:
    print(f"pitch {k}: overlay showed ({pred['h']:+.2f}, {pred['v']:.2f}) mid-wind-up, real target ({tx:+.2f}, {ty:.2f})")
    if not (plate_on and abs(pred["h"] - tx) < 0.05 and abs(pred["v"] - ty) < 0.05):
        print("MISS", k, pred, tx, ty, pitches[k]["zone"], pitches[k]["hit"], lp.zone["table"])
        bad = True
assert not globals().get("bad")
zone = app.strike_zone()
print("zone:", [round(z, 2) if isinstance(z, float) else z for z in zone], "labeled:", len(app._labeled()))
if "learned" in zone[4]:
    assert zone[1] - zone[0] > 0.2 and zone[3] - zone[2] > 0.2, zone
assert len(app.plate.find_all()) if hasattr(app, "plate") else True
assert len(app.overlay.plate.find_all()) > 5
assert any((vt, a) == ("byte", STATE * 4 + 1) for vt, a in app.coach_rows.values()), app.coach_rows
path = app.predict_export(); import json; d = json.load(open(path)); print("export:", path, d["model"]); os.remove(path)
app.coach_stop(); pump(0.3)
root.destroy()
print("PREDICT ZONE GUI TEST PASSED")
