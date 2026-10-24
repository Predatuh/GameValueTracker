"""
updater.py - over-the-air updates from your GitHub repo.

The repo holds the tracker's files plus a VERSION file. On start the app compares its own VERSION
with the repo's; if the repo is newer it can download the repo, copy the program files over the
old ones (keeping your settings, libraries and logs), and restart.

Private repo: give it a GitHub token that can read the repo (fine-grained token, "Contents: Read").
Public repo: no token needed. A saved token that GitHub rejects is skipped (and the app forgets it).
"""
import io
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.request
import zipfile

API = "https://api.github.com"
APP_DIR = os.path.dirname(os.path.abspath(__file__))
# only program files are ever replaced - your settings / libraries / logs are never touched
UPDATABLE = (".py", ".pyw", ".md", ".bat", ".txt")
KEEP = ("tracker_settings.json", "tracker_library.json", "tracker_errors.log")
SKIP_DIRS = ("tests", ".github", "libraries")


def local_version(app_dir=APP_DIR):
    try:
        with open(os.path.join(app_dir, "VERSION"), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return "0"


def _key(v):
    """'2026.10.23.4' -> (2026, 10, 23, 4) so versions compare properly."""
    out = []
    for part in str(v).strip().lstrip("v").split("."):
        num = "".join(ch for ch in part if ch.isdigit())
        out.append(int(num) if num else 0)
    return tuple(out)


def is_newer(remote, local):
    return _key(remote) > _key(local)


RAW = "https://raw.githubusercontent.com"
CODELOAD = "https://codeload.github.com"


class Updater:
    def __init__(self, repo, token="", branch="main", api=API, app_dir=APP_DIR, raw=RAW, codeload=CODELOAD):
        self.repo = (repo or "").strip().strip("/")
        self.token = (token or "").strip()
        self.branch = branch or "main"
        self.api = api.rstrip("/")
        self.raw = raw.rstrip("/")
        self.codeload = codeload.rstrip("/")
        self.app_dir = app_dir
        self.token_dropped = False       # the saved token was rejected but the repo is public - forget it

    def _public(self, url, timeout=10):
        """Plain download with no token (public repo). Not counted against GitHub's API limit."""
        req = urllib.request.Request(url, headers={"User-Agent": "GameValueTracker-updater"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()

    def _get(self, api_url, public_url, accept="application/vnd.github+json", timeout=10):
        """
        Public link first when there's no token (raw.githubusercontent.com answers fast even on PCs where
        api.github.com keeps timing out); the API first when there is one (private repos).
        """
        if not self.token:
            try:
                return self._public(public_url, timeout)
            except (urllib.error.URLError, OSError):
                return self._req(api_url, accept, timeout)
        try:
            return self._req(api_url, accept, timeout)
        except (RuntimeError, urllib.error.URLError, OSError) as first:
            try:
                data = self._public(public_url, timeout)
            except (urllib.error.URLError, OSError):
                raise RuntimeError(str(first)) from None
            self.token_dropped = True
            return data

    @property
    def ready(self):
        return "/" in self.repo

    def _req(self, url, accept="application/vnd.github+json", timeout=20):
        headers = {"Accept": accept, "User-Agent": "GameValueTracker-updater",
                   "X-GitHub-Api-Version": "2022-11-28"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            limited = e.code in (403, 429) and e.headers.get("X-RateLimit-Remaining") == "0"
            if e.code in (401, 403) and self.token:
                # a public repo doesn't need a token - a stale / wrong one shouldn't block updates
                headers.pop("Authorization", None)
                try:
                    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as resp:
                        self.token_dropped = True
                        return resp.read()
                except urllib.error.HTTPError:
                    pass
            if limited:
                raise RuntimeError("GitHub's limit for update checks was reached - try again in an hour.") from None
            if e.code in (401, 403, 404):
                raise RuntimeError(f"GitHub said {e.code}. Check the repo name and that your token can read it "
                                   "(private repo: fine-grained token with Contents: Read).") from None
            raise RuntimeError(f"GitHub error {e.code}") from None

    def remote_version(self):
        raw = self._get(f"{self.api}/repos/{self.repo}/contents/VERSION?ref={self.branch}",
                        f"{self.raw}/{self.repo}/{self.branch}/VERSION", accept="application/vnd.github.raw")
        return raw.decode("utf-8", "replace").strip()

    def changelog(self):
        try:
            raw = self._get(f"{self.api}/repos/{self.repo}/contents/CHANGELOG.md?ref={self.branch}",
                            f"{self.raw}/{self.repo}/{self.branch}/CHANGELOG.md", accept="application/vnd.github.raw")
            return raw.decode("utf-8", "replace")
        except Exception:
            return ""

    def check(self):
        """(update available?, remote version, local version)"""
        remote, local = self.remote_version(), local_version(self.app_dir)
        return is_newer(remote, local), remote, local

    def download(self):
        """The repo as a zip. Several routes, quickest first - one blocked GitHub server doesn't stop updates."""
        errors = []
        routes = [lambda: self._public(f"{self.codeload}/{self.repo}/zip/refs/heads/{self.branch}", 30),
                  lambda: self._req(f"{self.api}/repos/{self.repo}/zipball/{self.branch}", timeout=30),
                  self._download_files]
        if self.token:
            routes.insert(0, routes.pop(1))
        for route in routes:
            try:
                data = route()
                if data:
                    return data
            except (RuntimeError, urllib.error.URLError, OSError, ValueError) as e:
                errors.append(str(e))
        raise RuntimeError("Couldn't download the update (" + "; ".join(errors)[:200] + ")")

    def _download_files(self):
        """Last resort: each program file from raw.githubusercontent.com (MANIFEST.txt lists them), as a zip."""
        base = f"{self.raw}/{self.repo}/{self.branch}/"
        names = [n.strip() for n in self._public(base + "MANIFEST.txt").decode("utf-8", "replace").splitlines()
                 if n.strip() and not n.startswith("#")]
        if not names:
            raise ValueError("empty file list")
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as z:
            for n in dict.fromkeys(names + ["VERSION"]):
                if "/" in n or "\\" in n or ".." in n:
                    continue
                z.writestr("repo/" + n, self._public(base + n, 30))
        return out.getvalue()

    def install(self, zip_bytes):
        """Copy the new program files in. Old ones go to _previous_version/ first. Returns files updated."""
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
        names = [n for n in zf.namelist() if not n.endswith("/")]
        if not names:
            raise RuntimeError("The download was empty.")
        root = names[0].split("/", 1)[0] + "/"          # GitHub wraps everything in one folder
        files = {}
        for n in names:
            rel = n[len(root):] if n.startswith(root) else n
            if not rel or rel.split("/", 1)[0] in SKIP_DIRS or "/" in rel:
                continue                                  # only top-level program files
            if rel in KEEP or not (rel.endswith(UPDATABLE) or rel == "VERSION"):
                continue
            if ".." in rel or rel.startswith(("/", "\\")):
                continue
            files[rel] = zf.read(n)
        if not any(r.endswith(".py") for r in files) or "VERSION" not in files:
            raise RuntimeError("That download doesn't look like the tracker (no program files / VERSION).")
        backup = os.path.join(self.app_dir, "_previous_version")
        os.makedirs(backup, exist_ok=True)
        changed = []
        for rel, data in files.items():
            dst = os.path.join(self.app_dir, rel)
            old = None
            if os.path.exists(dst):
                with open(dst, "rb") as f:
                    old = f.read()
                if old == data:
                    continue
                shutil.copy2(dst, os.path.join(backup, rel))
            tmp = dst + ".new"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, dst)
            changed.append(rel)
        return changed

    def update(self):
        avail, remote, local = self.check()
        if not avail:
            return [], remote
        return self.install(self.download()), remote


def restart():
    """Start the tracker again (with no console window) and quit this one."""
    import subprocess
    app = os.path.join(APP_DIR, "GameValueTracker.pyw")
    exe = sys.executable
    if os.name == "nt" and exe.lower().endswith("python.exe") and os.path.exists(exe[:-10] + "pythonw.exe"):
        exe = exe[:-10] + "pythonw.exe"
    flags = 0x08000000 if os.name == "nt" else 0          # CREATE_NO_WINDOW
    subprocess.Popen([exe, app], cwd=APP_DIR, creationflags=flags)
    time.sleep(0.3)
    os._exit(0)
