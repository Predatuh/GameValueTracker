"""
brain.py - plug in any AI as the tool's brain.

Providers:
  anthropic  - Claude (api.anthropic.com)
  google     - Gemini (generativelanguage.googleapis.com, key from Google AI Studio)
  openai     - OpenAI, or anything "OpenAI compatible": OpenRouter, Groq, DeepSeek, xAI, Together,
               Mistral, and local ones like Ollama / LM Studio (set the base URL)
Everything goes through chat(system, user) -> text, so the rest of the tool doesn't care which one.
"""
import json
import urllib.error
import urllib.parse
import urllib.request

PROVIDERS = {
    "anthropic": {"label": "Claude (Anthropic)", "model": "claude-sonnet-5-5", "base": "https://api.anthropic.com"},
    "google":    {"label": "Gemini (Google AI Studio)", "model": "gemini-3.8-flash",
                  "base": "https://generativelanguage.googleapis.com"},
    "openai":    {"label": "OpenAI / OpenAI-compatible (OpenRouter, Groq, Ollama...)", "model": "gpt-5-mini",
                  "base": "https://api.openai.com/v1"},
}
PRESETS = {   # handy base URLs for the OpenAI-compatible option
    "OpenAI": "https://api.openai.com/v1",
    "OpenRouter": "https://openrouter.ai/api/v1",
    "Groq": "https://api.groq.com/openai/v1",
    "DeepSeek": "https://api.deepseek.com/v1",
    "xAI (Grok)": "https://api.x.ai/v1",
    "Mistral": "https://api.mistral.ai/v1",
    "Together": "https://api.together.xyz/v1",
    "Ollama (this PC)": "http://localhost:11434/v1",
    "LM Studio (this PC)": "http://localhost:1234/v1",
}


class Brain:
    def __init__(self, provider="anthropic", key="", model="", base=""):
        self.provider = provider if provider in PROVIDERS else "anthropic"
        self.key = (key or "").strip()
        self.model = (model or "").strip() or PROVIDERS[self.provider]["model"]
        self.base = (base or "").strip().rstrip("/") or PROVIDERS[self.provider]["base"]

    @property
    def usable(self):
        local = self.provider == "openai" and ("localhost" in self.base or "127.0.0.1" in self.base)
        return bool(self.key) or local

    @property
    def name(self):
        return {"anthropic": "Claude", "google": "Gemini", "openai": self.model}[self.provider]

    # ---- one question, one answer ----
    def chat(self, system, user, max_tokens=1500, timeout=60):
        if self.provider == "anthropic":
            data = self._post(f"{self.base}/v1/messages",
                              {"model": self.model, "max_tokens": max_tokens, "system": system,
                               "messages": [{"role": "user", "content": user}]},
                              {"x-api-key": self.key, "anthropic-version": "2023-06-01"}, timeout)
            return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        if self.provider == "google":
            url = (f"{self.base}/v1beta/models/{urllib.parse.quote(self.model)}:generateContent"
                   f"?key={urllib.parse.quote(self.key)}")
            data = self._post(url, {"system_instruction": {"parts": [{"text": system}]},
                                    "contents": [{"role": "user", "parts": [{"text": user}]}],
                                    "generationConfig": {"maxOutputTokens": max_tokens}}, {}, timeout)
            cands = data.get("candidates") or []
            if not cands:
                raise RuntimeError(f"Gemini gave no answer: {json.dumps(data)[:200]}")
            return "".join(p.get("text", "") for p in cands[0].get("content", {}).get("parts", []))
        headers = {"Authorization": f"Bearer {self.key}"} if self.key else {}
        body = {"model": self.model, "max_tokens": max_tokens,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        try:
            data = self._post(f"{self.base}/chat/completions", body, headers, timeout)
        except RuntimeError as e:
            if "max_tokens" not in str(e):
                raise
            body["max_completion_tokens"] = body.pop("max_tokens")      # newer OpenAI models want this
            data = self._post(f"{self.base}/chat/completions", body, headers, timeout)
        return data["choices"][0]["message"]["content"] or ""

    def list_models(self, timeout=20):
        """Model names this key can use (so you don't have to guess)."""
        if self.provider == "anthropic":
            data = self._get(f"{self.base}/v1/models", {"x-api-key": self.key, "anthropic-version": "2023-06-01"},
                             timeout)
            return [m["id"] for m in data.get("data", [])]
        if self.provider == "google":
            data = self._get(f"{self.base}/v1beta/models?key={urllib.parse.quote(self.key)}&pageSize=200", {}, timeout)
            return [m["name"].split("/", 1)[-1] for m in data.get("models", [])
                    if "generateContent" in m.get("supportedGenerationMethods", [])]
        headers = {"Authorization": f"Bearer {self.key}"} if self.key else {}
        data = self._get(f"{self.base}/models", headers, timeout)
        return sorted(m["id"] for m in data.get("data", []))

    # ---- http ----
    @staticmethod
    def _send(req, timeout):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")[:300]
            raise RuntimeError(f"HTTP {e.code}: {body}") from None

    def _post(self, url, body, headers, timeout):
        req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                     headers={"content-type": "application/json", **headers})
        return self._send(req, timeout)

    def _get(self, url, headers, timeout):
        return self._send(urllib.request.Request(url, headers=headers), timeout)


def from_settings(settings):
    """Brain from the saved settings (old Claude-only settings still work)."""
    return Brain(settings.get("provider", "anthropic"), settings.get("api_key", ""),
                 settings.get("model", ""), settings.get("base_url", ""))
