import sys; sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), ".."))
import ps2core as c
b = c.Booster(factor=3, reverse_only=True, cooldown=1.0)
dt = 1/60
t = 0.0
events = []
def run(seq):
    global t
    for v in seq:
        r = b.step(t, v); t += dt
        events.append((round(t, 2), v, r))
# at rest, pitch released (rest -> toward plate), travels, HIT (reverses), flies with gravity, lands, bounces, stops
run([[0, 0, 0]] * 30)
run([[0, -0.5, -35]] * 25)                                   # pitch: must NOT boost
run([[0, 12 - 9.8 * i * dt, 40] for i in range(40)])        # hit: boost once at first frame
hits = [e for e in events if e[2]]
assert len(hits) == 1 and hits[0][1] == [0, 12, 40], hits
assert hits[0][2] == [0, 36, 120]
run([[0, -5, 30]] * 3 + [[0, 4, 28]] * 3)                    # bounce: vertical flips only -> no boost
run([[0, 0, 0]] * 30)
assert b.count == 1, b.count
# second at-bat after cooldown
run([[0, -0.5, -35]] * 25); run([[1, 10, 38]] * 5)
assert b.count == 2, b.count
# single forward component works too
s = c.Booster(factor=5)
assert s.step(0, [0]) is None and s.step(0.1, [-30]) is None
assert s.step(0.2, [40]) == [200]
# garbage resets
assert s.step(5, [float("nan")]) is None
print("BOOST TESTS PASSED")
