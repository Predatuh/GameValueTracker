import sys, os, io, json, zipfile, threading, tempfile, shutil
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), ".."))
from http.server import BaseHTTPRequestHandler, HTTPServer
import updater

def make_zip(version, extra=None):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        root = "Predatuh-GameValueTracker-abc123/"
        z.writestr(root + "VERSION", version + "\n")
        z.writestr(root + "ps2core.py", "# new core " + version)
        z.writestr(root + "ps2_tracker.py", "# new app")
        z.writestr(root + "README.md", "new readme")
        z.writestr(root + "tracker_settings.json", '{"evil": 1}')     # must never overwrite settings
        z.writestr(root + "tests/test_x.py", "x")
        z.writestr(root + "libraries/x.json", "{}")
        for k, v in (extra or {}).items():
            z.writestr(root + k, v)
    return b.getvalue()

STATE = {"version": "2026.10.24.1"}
SEEN = []
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        SEEN.append((self.path, self.headers.get("Authorization")))
        if self.headers.get("Authorization") != "Bearer TOK":
            self.send_response(404); self.end_headers(); return
        if "/contents/VERSION" in self.path:
            body = STATE["version"].encode()
        elif "/contents/CHANGELOG.md" in self.path:
            body = b"- faster searches"
        elif "/zipball/" in self.path:
            body = make_zip(STATE["version"])
        else:
            self.send_response(404); self.end_headers(); return
        self.send_response(200); self.end_headers(); self.wfile.write(body)
srv = HTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
api = f"http://127.0.0.1:{srv.server_port}"

app = tempfile.mkdtemp()
open(os.path.join(app, "VERSION"), "w").write("2026.10.23.1")
open(os.path.join(app, "ps2core.py"), "w").write("# old core")
open(os.path.join(app, "tracker_settings.json"), "w").write('{"mine": 1}')
assert updater.is_newer("2026.10.24.1", "2026.10.23.12") and not updater.is_newer("2026.10.23.2", "2026.10.23.10")

bad = updater.Updater("Predatuh/GameValueTracker", "WRONG", api=api, app_dir=app, raw=api + "/raw", codeload=api + "/cl")
try:
    bad.check(); raise SystemExit("should fail")
except RuntimeError as e:
    assert "token" in str(e)
up = updater.Updater("Predatuh/GameValueTracker", "TOK", api=api, app_dir=app, raw=api + "/raw", codeload=api + "/cl")
avail, remote, local = up.check()
assert avail and remote == "2026.10.24.1" and local == "2026.10.23.1"
assert "faster" in up.changelog()
changed, v = up.update()
print("changed:", sorted(changed))
assert set(changed) == {"VERSION", "ps2core.py", "ps2_tracker.py", "README.md"}
assert open(os.path.join(app, "ps2core.py")).read() == "# new core 2026.10.24.1"
assert json.load(open(os.path.join(app, "tracker_settings.json"))) == {"mine": 1}
assert open(os.path.join(app, "_previous_version", "ps2core.py")).read() == "# old core"
assert not os.path.exists(os.path.join(app, "tests")) and not os.path.exists(os.path.join(app, "libraries"))
assert up.check()[0] is False
shutil.rmtree(app)

# public repo + an old token GitHub rejects (and the API itself refusing): the public links still work
PUB = {"version": "2026.10.25.1", "limited": False}
class P(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        if self.path.startswith("/repos/"):
            self.send_response(403)
            if PUB["limited"]:
                self.send_header("X-RateLimit-Remaining", "0")
            self.end_headers(); return
        if self.headers.get("Authorization"):
            self.send_response(401); self.end_headers(); return
        if self.path == "/raw/Predatuh/GameValueTracker/main/VERSION":
            body = PUB["version"].encode()
        elif self.path == "/codeload/Predatuh/GameValueTracker/zip/refs/heads/main":
            body = make_zip(PUB["version"])
        else:
            self.send_response(404); self.end_headers(); return
        self.send_response(200); self.end_headers(); self.wfile.write(body)
psrv = HTTPServer(("127.0.0.1", 0), P)
threading.Thread(target=psrv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{psrv.server_port}"
app = tempfile.mkdtemp()
open(os.path.join(app, "VERSION"), "w").write("2026.10.23.1")
pub = updater.Updater("Predatuh/GameValueTracker", "github_pat_OLD", api=base, app_dir=app,
                      raw=base + "/raw", codeload=base + "/codeload")
changed, v = pub.update()
assert v == "2026.10.25.1" and "ps2core.py" in changed and pub.token_dropped
assert open(os.path.join(app, "VERSION")).read().strip() == "2026.10.25.1"
# rate limit: a plain-words message (when the public link can't help either)
PUB["limited"] = True
lim = updater.Updater("Predatuh/GameValueTracker", "", api=base, app_dir=app, raw=base + "/nothing")
try:
    lim.check(); raise SystemExit("should fail")
except RuntimeError as e:
    assert "limit" in str(e), e
shutil.rmtree(app)

# the PC can't reach api.github.com / codeload at all (they time out) - only raw.githubusercontent.com works:
# the check is quick and the update comes file by file
FILES = {"VERSION": "2026.10.26.1\n", "ps2core.py": "# raw core", "MANIFEST.txt": "# list\nps2core.py\nMANIFEST.txt\n"}
class R(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        name = self.path.rsplit("/", 1)[-1]
        if not self.path.startswith("/raw/Predatuh/GameValueTracker/main/") or name not in FILES:
            self.send_response(404); self.end_headers(); return
        self.send_response(200); self.end_headers(); self.wfile.write(FILES[name].encode())
rsrv = HTTPServer(("127.0.0.1", 0), R)
threading.Thread(target=rsrv.serve_forever, daemon=True).start()
rbase = f"http://127.0.0.1:{rsrv.server_port}"
dead = "http://127.0.0.1:9"                      # nothing listens there
app = tempfile.mkdtemp()
open(os.path.join(app, "VERSION"), "w").write("2026.10.23.1")
import time as _t
t0 = _t.time()
ru = updater.Updater("Predatuh/GameValueTracker", "", api=dead, app_dir=app, raw=rbase + "/raw", codeload=dead)
assert ru.check() == (True, "2026.10.26.1", "2026.10.23.1")
changed, v = ru.update()
assert sorted(changed) == ["MANIFEST.txt", "VERSION", "ps2core.py"] and v == "2026.10.26.1", changed
assert open(os.path.join(app, "ps2core.py")).read() == "# raw core" and _t.time() - t0 < 10
shutil.rmtree(app)

# MANIFEST.txt must list every program file the repo ships (or the file-by-file route misses new ones)
import subprocess
root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
try:
    tracked = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True, timeout=30).stdout.split()
except Exception:
    tracked = []
if tracked:
    ship = {f for f in tracked if "/" not in f and (f.endswith(updater.UPDATABLE) or f == "VERSION")}
    listed = {l.strip() for l in open(os.path.join(root, "MANIFEST.txt"), encoding="utf-8") if l.strip() and not l.startswith("#")}
    assert ship - {"MANIFEST.txt"} <= listed, f"add to MANIFEST.txt: {sorted(ship - listed)}"
print("UPDATER TESTS PASSED")
