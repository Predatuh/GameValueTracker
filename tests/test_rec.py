import sys; sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), ".."))
import numpy as np, ps2core as c
rng = np.random.default_rng(0)
t = np.arange(0, 20, 1/120)
marks = [3.0, 9.0, 15.0]
height = np.full_like(t, 1.0); vy = np.zeros_like(t); vx = np.zeros_like(t)
for m in marks:
    v0 = rng.uniform(15, 25); vxo = rng.uniform(30, 45)
    # pitch before the hit: ball moves horizontally toward plate
    p = (t >= m - 0.5) & (t < m); vx[p] = -35
    a = (t >= m)
    tt = t[a] - m
    hgt = 1 + v0 * tt - 4.9 * tt**2
    land = hgt <= 0
    seg_h = np.where(land, 0, hgt); seg_vy = np.where(land, 0, v0 - 9.8 * tt); seg_vx = np.where(land, 0, vxo * np.exp(-0.2*tt))
    nxt = (t >= m) & (t < m + 5.5)
    height[nxt] = seg_h[:nxt.sum()]; vy[nxt] = seg_vy[:nxt.sum()]; vx[nxt] = seg_vx[:nxt.sum()]
traces = {
    "height": height, "vy": vy, "vx": vx,
    "stack": rng.normal(0, 5, len(t)),
    "clock": t * 1.0,                       # changes smoothly all the time
    "zero": np.zeros_like(t),
}
res = c.analyze_traces(t, traces, marks)
for r in res: print(r)
kinds = {r["key"]: r["kind"] for r in res}
assert res[0]["key"] in ("height", "vy", "vx")
assert kinds["height"] == "height", kinds
assert kinds["vy"] == "vspeed", kinds
assert kinds["vx"] == "speed", kinds
assert kinds["stack"] == "noise" and kinds["zero"] == "static", kinds
assert kinds["clock"] in ("active", "noise"), kinds
print("RECORDER TESTS PASSED")
