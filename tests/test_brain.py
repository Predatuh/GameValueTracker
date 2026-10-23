import sys, json, threading
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), ".."))
from http.server import BaseHTTPRequestHandler, HTTPServer
import brain, coach

PLAN = json.dumps({"title": "Run speed", "category": "Running", "mode": "pulse", "understood": "find run speed",
                   "types": ["float"], "pulse": {"kind": "run", "say": "Press ] and run", "mid": 1.2, "post": 3.5},
                   "steps": [], "loop": []})
SEEN = []
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _reply(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("content-type", "application/json"); self.end_headers()
        self.wfile.write(b)
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        SEEN.append((self.path, body, dict(self.headers)))
        if self.path.startswith("/v1/messages"):
            return self._reply({"content": [{"type": "text", "text": PLAN}]})
        if ":generateContent" in self.path:
            assert "key=GKEY" in self.path and body["system_instruction"]["parts"][0]["text"]
            return self._reply({"candidates": [{"content": {"parts": [{"text": "Here you go:\n" + PLAN}]}}]})
        if self.path.endswith("/chat/completions"):
            if "max_tokens" in body and body["model"] == "new-model":
                return self._reply({"error": {"message": "Unsupported parameter: 'max_tokens'"}}, 400)
            return self._reply({"choices": [{"message": {"content": PLAN}}]})
    def do_GET(self):
        if "/v1beta/models" in self.path:
            return self._reply({"models": [{"name": "models/gemini-3.8-flash", "supportedGenerationMethods": ["generateContent"]},
                                           {"name": "models/embed", "supportedGenerationMethods": ["embedContent"]}]})
        return self._reply({"data": [{"id": "m1"}, {"id": "new-model"}]})
srv = HTTPServer(("127.0.0.1", 0), H); port = srv.server_port
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{port}"

g = brain.Brain("google", "GKEY", "gemini-3.8-flash", base)
r, src, note = coach.make_plan("how fast do I run", brain=g, game_hint="GTA San Andreas")
assert src == "Gemini" and r["mode"] == "pulse" and not note, (src, note)
assert "GTA San Andreas" in SEEN[-1][1]["contents"][0]["parts"][0]["text"]
assert g.list_models() == ["gemini-3.8-flash"]
a = brain.Brain("anthropic", "AKEY", "", base)
r, src, _ = coach.make_plan("run speed", brain=a); assert src == "Claude" and {k.lower(): v for k, v in SEEN[-1][2].items()}["x-api-key"] == "AKEY"
o = brain.Brain("openai", "OKEY", "new-model", base + "/v1")
r, src, _ = coach.make_plan("run speed", brain=o)
assert src == "new-model" and "max_completion_tokens" in SEEN[-1][1], SEEN[-1][1]
assert o.list_models() == ["m1", "new-model"]
local = brain.Brain("openai", "", "llama3", "http://localhost:11434/v1"); assert local.usable
bad = brain.Brain("google", "GKEY", "gemini-3.8-flash", "http://127.0.0.1:1")
r, src, note = coach.make_plan("ammo I have 30", brain=bad)
assert src == "built-in" and "unavailable" in note
print("BRAIN TESTS PASSED")
