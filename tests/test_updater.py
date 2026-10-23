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

bad = updater.Updater("Predatuh/GameValueTracker", "WRONG", api=api, app_dir=app)
try:
    bad.check(); raise SystemExit("should fail")
except RuntimeError as e:
    assert "token" in str(e)
up = updater.Updater("Predatuh/GameValueTracker", "TOK", api=api, app_dir=app)
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
print("UPDATER TESTS PASSED")
