"""
Game Value Tracker - find, label, edit and turn game values into cheats (PS2/PS3/GC/Wii/PSP/PS1/PC).
Started for NCAA Football 2006 on PCSX2; works with PS3, GameCube/Wii, PSP, PS1 emulators and PC games.

Run:   python ps2_tracker.py
Needs: Windows, Python 3.10+, numpy  (pip install numpy)
"""
import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import numpy as np

import ps2core as core
import coach as coachlib
import brain as brainlib
import updater
import gameinfo
import modmenu
import spawner

APP_TITLE = "Game Value Tracker"
BOOST_TRIGGERS = ["the ball reverses direction (velocity values)",
                  "the value changes (hit power, launch strength...)",
                  "the value jumps a lot suddenly"]
BOOST_TRIGGER_KEYS = dict(zip(BOOST_TRIGGERS, ("reverse", "change", "jump")))
MODE_CHOICES = ["Let the AI decide", "Find a value (ammo, health, speed...)",
                "Find the ball after it's hit (for boosts)", "Predict where it will go (pitch, shot)"]
ANY_TYPE = "any type (all 4)"
PAD_SOURCES = ["Xbox-style controller (XInput: Xbox, DS4/DualSense via Steam or DS4Windows)",
               "Keyboard only", "Controller value found in game memory (Learn game pad)"]
MODE_KEYS = {MODE_CHOICES[1]: "scan", MODE_CHOICES[2]: "event", MODE_CHOICES[3]: "predict"}
APP_DIR = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
SAVE_FILE = os.path.join(APP_DIR, "tracker_library.json")
SETTINGS_FILE = os.path.join(APP_DIR, "tracker_settings.json")
LIB_DIR = os.path.join(APP_DIR, "libraries")

HOTKEYS = {  # virtual-key code -> (label, scanner action)
    0x74: ("F5", "unknown"),
    0x75: ("F6", "changed"),
    0x76: ("F7", "unchanged"),
    0x77: ("F8", "increased"),
    0x78: ("F9", "decreased"),
    0xDB: ("[", "rec_toggle"),   # start / stop recording
    0xDD: ("]", "rec_mark"),     # "ball hit now"
    0xDC: ("\\", "boost_toggle"), # power boost on / off
    0xBA: (";", "zone_strike"),    # predictor: last pitch was a strike
    0xDE: ("'", "zone_ball"),      # predictor: last pitch was a ball
}


# ---------------------------------------------------------------------------
# small form dialog
# ---------------------------------------------------------------------------
def ask_form(parent, title, fields, extra=None):
    """
    fields: [(key, label, kind, default, options)] kind = 'entry' | 'combo'
    extra:  optional callback(frame, widgets) to add custom widgets
    Returns dict of values or None.
    """
    dlg = tk.Toplevel(parent)
    dlg.title(title)
    dlg.transient(parent)
    dlg.resizable(False, False)
    frm = ttk.Frame(dlg, padding=12)
    frm.pack(fill="both", expand=True)
    widgets, result = {}, {}
    for row, (key, label, kind, default, options) in enumerate(fields):
        ttk.Label(frm, text=label).grid(row=row, column=0, sticky="w", pady=3, padx=(0, 8))
        var = tk.StringVar(value="" if default is None else str(default))
        if kind == "combo":
            w = ttk.Combobox(frm, textvariable=var, values=options or [], width=34)
        else:
            w = ttk.Entry(frm, textvariable=var, width=36)
        w.grid(row=row, column=1, sticky="ew", pady=3)
        widgets[key] = (var, w)
    next_row = len(fields)
    if extra:
        next_row = extra(frm, widgets, next_row)

    def ok():
        for k, (var, _) in widgets.items():
            result[k] = var.get().strip()
        dlg.destroy()

    btns = ttk.Frame(frm)
    btns.grid(row=next_row + 1, column=0, columnspan=3, pady=(10, 0), sticky="e")
    ttk.Button(btns, text="OK", command=ok).pack(side="left", padx=4)
    ttk.Button(btns, text="Cancel", command=dlg.destroy).pack(side="left")
    dlg.bind("<Return>", lambda e: ok())
    dlg.bind("<Escape>", lambda e: dlg.destroy())
    if fields:
        widgets[fields[0][0]][1].focus_set()
    dlg.grab_set()
    parent.wait_window(dlg)
    return result or None


# ---------------------------------------------------------------------------
# main app
# ---------------------------------------------------------------------------
class App:
    def __init__(self, root):
        self.root = root
        root.title(APP_TITLE)
        root.geometry("1150x780")
        root.minsize(900, 600)

        self.ps2 = core.Pcsx2()
        self.scanner = core.Scanner()
        self.library = []
        self.cheats = []
        self.game_title = tk.StringVar(value="NCAA Football 2006")
        self.edit_before = None
        self.p1_anchor = None
        self.p2_anchor = None
        self.found = None          # last ratings-finder result
        self.lib_items = {}        # tree iid -> (entry, field or None)
        self.show_record = tk.IntVar(value=0)
        self.watch = []            # [{'addr', 'type', 'name'}]
        self.recording = False
        self.rec_data = None       # {'t': [], 'vals': {i: []}, 'marks': []}
        self.rec_results = []
        self.boosting = False
        self.booster = None
        self.plan = None
        self.coach = None
        self.coach_wait = None     # 'timer' | 'key' | 'number' | None
        self.coach_token = 0
        self.overlay = None
        self.hunter = None
        self.hunting = False
        self.hunt_lock = threading.Lock()
        self.coach_rows = {}       # tree iid -> (type, addr)
        self.testing = False       # auto-test running
        self.test_results = []
        self.ball_test = None      # {'queue': [...], 'results': [...], 'busy': bool}
        self.deep = None           # deep test: {'gt': GroupTester, 'watchers': [...], 'busy': bool}
        self.boost_warn = ""
        self.predicting = False
        self.predictor = None
        self.pulsing = False
        self.pulser = None
        self.gt = None
        self.gt_token = 0
        self.pending_answer = None
        self.zone_labels = []      # (outcome dict, is_strike)
        self.last_pred = None
        self.settings = self._load_settings()
        self._ui_queue = queue.Queue()
        self.lib_path = SAVE_FILE
        self.game = None           # {'title', 'serial', 'key', 'found'}
        self.genre = "other"
        self.spawn = {"lists": [], "learned": {}, "observed": []}
        self.menu = None           # running MenuEngine
        self.menu_on = False
        self.menu_ov = None
        self.mem_pad = None
        self._holds = []           # (offset, type, value, until) - spawns held for a moment
        self.sc_frozen = {}        # (addr, type) -> value frozen from the Scanner tab

        self._build_ui()
        self.load_library(self.lib_path, quiet=True)
        self._refresh_hit_sources()
        self.tailor_ui("other")
        self._start_loops()

    # ======================= UI ===========================================
    def _build_ui(self):
        style = ttk.Style()
        try:
            style.theme_use("vista")
        except tk.TclError:
            pass

        top = ttk.Frame(self.root, padding=(8, 6))
        top.pack(fill="x")
        ttk.Label(top, text="Game:").pack(side="left")
        self.proc_var = tk.StringVar()
        self.proc_box = ttk.Combobox(top, textvariable=self.proc_var, width=46, state="readonly",
                                     postcommand=self.refresh_processes)
        self.proc_box.pack(side="left", padx=(2, 4))
        self.proc_box.bind("<<ComboboxSelected>>", self._proc_picked)
        ttk.Label(top, text="System:").pack(side="left")
        self.sys_var = tk.StringVar(value=core.PROFILES["auto"]["label"])
        ttk.Combobox(top, textvariable=self.sys_var, width=24, state="readonly",
                     values=[p["label"] for p in core.PROFILES.values()]).pack(side="left", padx=(2, 4))
        ttk.Button(top, text="Attach", command=self.attach).pack(side="left")
        ttk.Label(top, text="  Game type:").pack(side="left")
        self.genre_var = tk.StringVar(value=gameinfo.GENRES["other"]["label"])
        gb = ttk.Combobox(top, textvariable=self.genre_var, width=22, state="readonly",
                          values=[g["label"] for g in gameinfo.GENRES.values()])
        gb.pack(side="left", padx=(2, 4))
        gb.bind("<<ComboboxSelected>>", self._genre_picked)
        ttk.Label(top, text="  Base (hex, optional):").pack(side="left")
        self.base_override = tk.StringVar()
        ttk.Entry(top, textvariable=self.base_override, width=14).pack(side="left")
        self.procs = []
        ttk.Button(top, text="Updates...", command=self.update_dialog).pack(side="right")
        self.version_lbl = ttk.Label(top, text=f"v{updater.local_version(APP_DIR)}", foreground="#666")
        self.version_lbl.pack(side="right", padx=6)
        self.conn_label = ttk.Label(self.root, text="Not attached", foreground="#b00", padding=(10, 0))
        self.conn_label.pack(fill="x")
        self.update_bar = tk.Frame(self.root, background="#fef3c7")
        self.update_lbl = tk.Label(self.update_bar, text="", background="#fef3c7", font=("Segoe UI", 10, "bold"))
        self.update_lbl.pack(side="left", padx=10, pady=4)
        tk.Button(self.update_bar, text="Later", command=self.update_bar.pack_forget, bd=0, bg="#e5e7eb",
                  padx=8).pack(side="right", padx=4, pady=3)
        tk.Button(self.update_bar, text="What's new", command=self.update_whats_new, bd=0, bg="#e5e7eb",
                  padx=8).pack(side="right", padx=4, pady=3)
        tk.Button(self.update_bar, text="Update now", command=self.update_now, bd=0, bg="#22c55e",
                  padx=10).pack(side="right", padx=4, pady=3)

        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill="both", expand=True, padx=6, pady=4)
        self._build_coach_tab()
        self._build_scanner_tab()
        self._build_recorder_tab()
        self._build_boost_tab()
        self._build_ratings_tab()
        self._build_library_tab()
        self._build_cheat_tab()
        self._build_spawn_tab()
        self._build_help_tab()

        self.status = tk.StringVar(value="Start your emulator or game, pick it in the Game list, then click Attach.")
        ttk.Label(self.root, textvariable=self.status, relief="sunken", anchor="w",
                  padding=(6, 2)).pack(fill="x", side="bottom")

    # ---------------- scanner tab ------------------------------------------
    def _build_scanner_tab(self):
        tab = ttk.Frame(self.nb, padding=8)
        self.nb.add(tab, text="Scanner / Event tracker")

        row1 = ttk.Frame(tab)
        row1.pack(fill="x")
        ttk.Label(row1, text="Value type").pack(side="left")
        self.sc_type = ttk.Combobox(row1, values=list(core.TYPES) + [ANY_TYPE], width=16, state="readonly")
        self.sc_type.set("byte")
        self.sc_type.pack(side="left", padx=4)
        ttk.Label(row1, text="First scan").pack(side="left", padx=(12, 0))
        self.sc_first_mode = ttk.Combobox(row1, values=["exact", "greater than", "less than", "unknown"],
                                          width=12, state="readonly")
        self.sc_first_mode.set("exact")
        self.sc_first_mode.pack(side="left", padx=4)
        ttk.Label(row1, text="Value").pack(side="left", padx=(12, 0))
        self.sc_value = ttk.Entry(row1, width=12)
        self.sc_value.pack(side="left", padx=4)
        ttk.Button(row1, text="First scan", command=self.first_scan).pack(side="left", padx=4)

        row2 = ttk.Frame(tab)
        row2.pack(fill="x", pady=6)
        ttk.Label(row2, text="Next scan").pack(side="left")
        self.sc_next_mode = ttk.Combobox(row2, values=list(core.VALUE_MODES) + list(core.COMPARE_MODES),
                                         width=12, state="readonly")
        self.sc_next_mode.set("exact")
        self.sc_next_mode.pack(side="left", padx=4)
        ttk.Button(row2, text="Next scan", command=self.next_scan).pack(side="left", padx=4)
        ttk.Button(row2, text="Refresh values", command=self.show_scan_results).pack(side="left", padx=4)
        ttk.Button(row2, text="Reset", command=self.reset_scan).pack(side="left", padx=4)
        self.sc_count = ttk.Label(row2, text="No scan yet", font=("Segoe UI", 10, "bold"))
        self.sc_count.pack(side="left", padx=16)

        hk = ("Hotkeys work while you play (game window focused):  "
              "F5 = start new 'unknown value' scan   F6 = changed   F7 = unchanged   "
              "F8 = increased   F9 = decreased")
        ttk.Label(tab, text=hk, foreground="#335").pack(anchor="w", pady=(0, 6))

        frame = ttk.Frame(tab)
        frame.pack(fill="both", expand=True)
        self.sc_tree = ttk.Treeview(frame, columns=("addr", "value", "prev", "frozen"), show="headings",
                                    selectmode="extended")
        for col, text, w in (("addr", "Address", 170), ("value", "Current", 220),
                             ("prev", "At last scan", 220), ("frozen", "Frozen", 140)):
            self.sc_tree.heading(col, text=text)
            self.sc_tree.column(col, width=w, anchor="w")
        sb = ttk.Scrollbar(frame, command=self.sc_tree.yview)
        self.sc_tree.configure(yscrollcommand=sb.set)
        self.sc_tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.sc_tree.bind("<Double-1>", lambda e: self.scan_set_value())

        bb = ttk.Frame(tab)
        bb.pack(fill="x", pady=6)
        for text, cmd in (("Freeze / unfreeze", self.scan_toggle_freeze), ("Set value...", self.scan_set_value),
                          ("Unfreeze all", self.scan_unfreeze_all),
                          ("Add to library (name it later)", self.scan_quick_add),
                          ("Add & name...", self.add_scan_to_library)):
            ttk.Button(bb, text=text, command=cmd).pack(side="left", padx=(0, 4))
        ttk.Label(bb, foreground="#666", text="Freeze a few to test which one is real - frozen ones keep their value "
                  "while you play. Double-click a row to type a new value.").pack(side="left", padx=8)

    # ---------------- AI coach tab --------------------------------------------
    def _build_coach_tab(self):
        tab = ttk.Frame(self.nb, padding=10)
        self.coach_tab = tab
        self.nb.add(tab, text="AI Coach")

        ttk.Label(tab, text="What are you looking for? Say it like you'd tell a friend:",
                  font=("Segoe UI", 11, "bold")).pack(anchor="w")
        row = ttk.Frame(tab)
        row.pack(fill="x", pady=4)
        self.ask_var = tk.StringVar()
        ent = ttk.Entry(row, textvariable=self.ask_var, font=("Segoe UI", 12))
        ent.pack(side="left", fill="x", expand=True)
        ent.bind("<Return>", lambda e: self.make_plan())
        self.ask_var.trace_add("write", lambda *a: setattr(self, "plan", None))
        ttk.Label(row, text="  I want to:").pack(side="left")
        self.mode_var = tk.StringVar(value=MODE_CHOICES[0])
        ttk.Combobox(row, textvariable=self.mode_var, values=MODE_CHOICES, state="readonly",
                     width=34).pack(side="left", padx=4)
        ttk.Button(row, text="Make a plan", command=self.make_plan).pack(side="left", padx=6)
        self.mode_var.trace_add("write", lambda *a: setattr(self, "plan", None))
        self.examples_lbl = ttk.Label(tab, foreground="#666", text="")
        self.examples_lbl.pack(anchor="w")

        mid = ttk.Frame(tab)
        mid.pack(fill="x", pady=8)
        self.plan_text = tk.Text(mid, height=9, width=70, wrap="word", state="disabled",
                                 background="#f7f7f7", font=("Segoe UI", 9))
        self.plan_text.pack(side="left", fill="x", expand=True)
        side = ttk.Frame(mid)
        side.pack(side="left", fill="y", padx=8)
        self.coach_start_btn = ttk.Button(side, text="Start  (shows the overlay)", command=self.coach_start)
        self.coach_start_btn.pack(fill="x", pady=2)
        ttk.Button(side, text="Start over (new search)", command=lambda: self.coach_start(fresh=True)).pack(fill="x", pady=2)
        ttk.Button(side, text="Stop", command=self.coach_stop).pack(fill="x", pady=2)
        self.hit_frame = ttk.Frame(side)
        self.hit_frame.pack(fill="x")
        ttk.Label(self.hit_frame, text="Ball games - auto-detect hits from:", foreground="#444").pack(anchor="w", pady=(10, 0))
        self.hit_source = ttk.Combobox(self.hit_frame, width=30, state="readonly")
        self.hit_source.pack(fill="x")
        self.coach_status = ttk.Label(side, text="", font=("Segoe UI", 10, "bold"), wraplength=260)
        self.coach_status.pack(anchor="w", pady=8)

        res = ttk.Frame(tab)
        res.pack(fill="both", expand=True)
        self.coach_tree = ttk.Treeview(res, columns=("type", "addr", "value", "note"), show="headings", height=8)
        for col, text, w in (("type", "Type", 70), ("addr", "Address", 110), ("value", "Live value", 160),
                             ("note", "Notes", 520)):
            self.coach_tree.heading(col, text=text)
            self.coach_tree.column(col, width=w, anchor="w")
        self.coach_tree.pack(side="left", fill="both", expand=True)
        rb = ttk.Frame(res)
        rb.pack(side="left", fill="y", padx=6)
        self.coach_btns = {}
        for key, text, cmd in (("quick", "Add to library (name later)", self.coach_quick_add),
                               ("freeze", "Freeze / unfreeze", self.coach_toggle_freeze),
                               ("save", "Save & name...", self.coach_save),
                               ("more", "Keep narrowing", self.coach_more),
                               ("group", "Test them with me (freeze)", lambda: self.group_test_start("hold")),
                               ("speed", "Speed hack test (x3)", lambda: self.group_test_start("boost")),
                               ("hack", "Speed hack ON/OFF", self.speed_hack_toggle),
                               ("test", "Test: set value...", self.coach_test),
                               ("boost", "Send to Power boost", self.coach_to_boost),
                               ("rec", "Watch in Recorder", self.coach_to_recorder),
                               ("auto", "Auto-test: which is real?", self.auto_test_scan),
                               ("deep", "Deep test (ball hunts)", self.deep_start),
                               ("spawn", "Use as spawn ID", self.coach_to_spawn),
                               ("pexp", "Export predictor findings", self.predict_export)):
            b = ttk.Button(rb, text=text, command=cmd)
            b.pack(fill="x", pady=2)
            self.coach_btns[key] = b

        zf = ttk.LabelFrame(tab, text="Predictor display", padding=6)
        zf.pack(fill="x", pady=(8, 0))
        self.pred_frame = zf
        ttk.Label(zf, text="Strike zone size %").pack(side="left")
        self.zone_scale = tk.IntVar(value=100)
        ttk.Spinbox(zf, from_=40, to=200, increment=10, textvariable=self.zone_scale, width=6).pack(side="left", padx=4)
        self.flip_h = tk.BooleanVar(value=False)
        self.flip_v = tk.BooleanVar(value=False)
        ttk.Checkbutton(zf, text="Flip left/right", variable=self.flip_h).pack(side="left", padx=8)
        ttk.Checkbutton(zf, text="Flip up/down", variable=self.flip_v).pack(side="left", padx=8)
        ttk.Label(zf, text="(in game: ; = that pitch was a strike, ' = it was a ball - teaches the zone)",
                  foreground="#666").pack(side="left", padx=8)

        st = ttk.LabelFrame(tab, text="AI brain (optional - any AI you have a key for; leave the key blank to use the "
                                      "built-in brain)", padding=6)
        st.pack(fill="x", pady=(8, 0))
        self.claude_frame = st
        ttk.Label(st, text="Brain").pack(side="left")
        prov = self.settings.get("provider", "anthropic")
        self.provider_var = tk.StringVar(value=brainlib.PROVIDERS.get(prov, brainlib.PROVIDERS["anthropic"])["label"])
        pb = ttk.Combobox(st, textvariable=self.provider_var, state="readonly", width=30,
                          values=[p["label"] for p in brainlib.PROVIDERS.values()])
        pb.pack(side="left", padx=4)
        pb.bind("<<ComboboxSelected>>", self._provider_picked)
        ttk.Label(st, text="Key").pack(side="left", padx=(6, 0))
        keys = self.settings.setdefault("keys", {})
        if self.settings.get("api_key") and "anthropic" not in keys:
            keys["anthropic"] = self.settings["api_key"]          # older settings: Claude-only key
        self.key_var = tk.StringVar(value=keys.get(prov, ""))
        ttk.Entry(st, textvariable=self.key_var, show="•", width=26).pack(side="left", padx=4)
        ttk.Label(st, text="Model").pack(side="left", padx=(6, 0))
        models = self.settings.setdefault("models", {})
        if self.settings.get("model") and "anthropic" not in models:
            models["anthropic"] = self.settings["model"]
        self.model_var = tk.StringVar(value=models.get(prov) or brainlib.PROVIDERS[prov]["model"])
        self.model_box = ttk.Combobox(st, textvariable=self.model_var, width=24)
        self.model_box.pack(side="left", padx=4)
        ttk.Button(st, text="List models", command=self.brain_list_models).pack(side="left", padx=2)
        self.base_lbl = ttk.Label(st, text="URL")
        self.base_var = tk.StringVar(value=self.settings.get("base_url", ""))
        self.base_box = ttk.Combobox(st, textvariable=self.base_var, width=26,
                                     values=list(brainlib.PRESETS.values()))
        ttk.Button(st, text="Test", command=self.brain_test).pack(side="right", padx=2)
        ttk.Button(st, text="Save", command=self._save_settings).pack(side="right", padx=2)
        self._provider_picked(first=True)
        self.nb.bind("<<NotebookTabChanged>>", lambda e: self._refresh_hit_sources(), add="+")
        self._refresh_hit_sources()

    # ---- settings ----
    def _load_settings(self):
        try:
            with open(SETTINGS_FILE, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}

    def _provider_key(self):
        return next((k for k, p in brainlib.PROVIDERS.items() if p["label"] == self.provider_var.get()), "anthropic")

    def _provider_picked(self, *_, first=False):
        prov = self._provider_key()
        if not first:
            old = self.settings.get("provider", "anthropic")
            self.settings.setdefault("keys", {})[old] = self.key_var.get().strip()
            self.settings.setdefault("models", {})[old] = self.model_var.get().strip()
            self.key_var.set(self.settings["keys"].get(prov, ""))
            self.model_var.set(self.settings["models"].get(prov) or brainlib.PROVIDERS[prov]["model"])
            self.settings["provider"] = prov
        if prov == "openai":
            self.base_lbl.pack(side="left", padx=(6, 0))
            self.base_box.pack(side="left", padx=4)
            if not self.base_var.get():
                self.base_var.set(brainlib.PROVIDERS["openai"]["base"])
        else:
            self.base_lbl.pack_forget()
            self.base_box.pack_forget()

    def brain(self):
        prov = self._provider_key()
        return brainlib.Brain(prov, self.key_var.get(), self.model_var.get(),
                              self.base_var.get() if prov == "openai" else "")

    def brain_list_models(self):
        b = self.brain()
        if not b.usable:
            messagebox.showinfo(APP_TITLE, "Paste your API key first.")
            return
        self.say(f"Asking {brainlib.PROVIDERS[b.provider]['label']} which models you can use...")

        def work():
            try:
                names = b.list_models()
                self.ui(self.model_box.configure, {"values": names})
                self.ui(self.say, f"{len(names)} models - pick one in the Model box." if names else "No models listed.")
            except Exception as e:
                self.ui(self.say, f"Couldn't list models: {e}")
        threading.Thread(target=work, daemon=True).start()

    def brain_test(self):
        b = self.brain()
        if not b.usable:
            messagebox.showinfo(APP_TITLE, "Paste your API key first.")
            return
        self.say(f"Testing {b.name} ({b.model})...")

        def work():
            try:
                t0 = time.time()
                reply = b.chat("Reply with exactly: OK", "Say OK", max_tokens=20, timeout=30)
                self.ui(self.say, f"{b.name} works ({time.time() - t0:.1f}s): {reply.strip()[:40]}")
                self.ui(self._save_settings, True)
            except Exception as e:
                self.ui(self.say, f"{b.name} didn't work: {str(e)[:200]}")
        threading.Thread(target=work, daemon=True).start()

    def _save_settings(self, quiet=False):
        prov = self._provider_key()
        self.settings["provider"] = prov
        self.settings.setdefault("keys", {})[prov] = self.key_var.get().strip()
        self.settings.setdefault("models", {})[prov] = self.model_var.get().strip() or brainlib.PROVIDERS[prov]["model"]
        self.settings["base_url"] = self.base_var.get().strip()
        self.settings.pop("api_key", None)
        self.settings.pop("model", None)
        if self.overlay is not None and self.overlay.winfo_exists():
            self.settings["overlay_pos"] = [self.overlay.winfo_x(), self.overlay.winfo_y()]
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, indent=2)
            if not quiet:
                self.say("Settings saved.")
        except OSError as e:
            messagebox.showerror(APP_TITLE, f"Could not save settings: {e}")

    def _refresh_hit_sources(self):
        names = ["(none - I'll press ])"] + [e["name"] for e in self.library
                                             if e["kind"] == "value" and e["type"] == "float"]
        cur = self.hit_source.get()
        self.hit_source.configure(values=names)
        self.hit_source.set(cur if cur in names else names[0])

    # ---- planning ----
    def make_plan(self):
        text = self.ask_var.get().strip()
        if not text:
            return
        b = self.brain()
        self.coach_status.configure(text=f"{b.name} is thinking..." if b.usable else "")
        force = MODE_KEYS.get(self.mode_var.get())
        hint = ""
        if self.game:
            hint = f"{self.game['title']} ({core.PROFILES.get(getattr(self.ps2, 'profile', 'ps2'), {}).get('label', '')}, " \
                   f"{gameinfo.GENRES[self.genre]['label']})"
        if not b.usable:
            self._show_plan(*coachlib.make_plan(text, force_mode=force))
            return

        def work():
            plan, source, note = coachlib.make_plan(text, force_mode=force, brain=b, game_hint=hint)
            self.ui(self._show_plan, plan, source, note)

        threading.Thread(target=work, daemon=True).start()

    def _show_plan(self, plan, source, note):
        self.plan = plan
        lines = [f"I UNDERSTOOD: {plan.get('understood') or plan['title']}",
                 f"PLAN: {plan['title']}   (brain: {source})   - not right? change 'I want to:' and "
                 "click Make a plan again"]
        if note:
            lines.append(note)
        if plan["mode"] == "predict":
            lines += ["", "How it works:",
                      "  1. " + plan["event"]["say"],
                      "  2. First it finds the ball in flight (a value that flies straight at the plate "
                      "right after every release).",
                      "  3. Then it records where each pitch ends up and what memory looked like during "
                      "the wind-up, and finds the value the CPU set BEFORE throwing.",
                      "  4. The overlay turns into a strike zone and shows where the next pitch is going "
                      "the moment the CPU decides. Press ; after a called strike and ' after a ball to "
                      "teach it your strike zone."]
        elif plan["mode"] == "event":
            lines += ["", "Fully automatic ball finder:", "  " + plan["event"]["say"],
                      "  The tool watches all of memory, throws out whatever doesn't react to the "
                      f"ball being {plan['event']['action']}, then records and scores what's left."]
        else:
            lines.append(f"Will try value types: {', '.join(plan['types'])}. "
                         f"Stops when {plan['target']} or fewer are left.")
            lines.append("")
            for s in plan["steps"]:
                lines.append("  • " + self._step_line(s))
            lines.append("  Then repeat until found:")
            for s in plan["loop"]:
                lines.append("    ↻ " + self._step_line(s))
        lines.append("")
        lines.append("Click Start. Instructions appear in a small window on top of the game.")
        self.plan_text.configure(state="normal")
        self.plan_text.delete("1.0", "end")
        self.plan_text.insert("1.0", "\n".join(lines))
        self.plan_text.configure(state="disabled")
        self.coach_status.configure(text="")

    @staticmethod
    def _step_line(s):
        how = ("type the number" if s.get("value") == "ask" else
               "press ] when done" if s["until"] == "key" else f"{s['secs']:g}s")
        return f"{s['say']}  [{how}]"

    # ---- running ----
    def coach_start(self, fresh=False):
        if not self.need_attach():
            return
        co = self.coach
        if not fresh and co is not None and self.plan is not None and co.r is self.plan and co.done \
                and not co.failed and co.total > co.r["target"]:
            return self.coach_more()
        if not self.plan:
            if self.brain().usable and self.ask_var.get().strip():
                messagebox.showinfo(APP_TITLE, "Click 'Make a plan' first and wait for the AI's plan.")
                return
            self.make_plan()
            if not self.plan:
                messagebox.showinfo(APP_TITLE, "Type what you're looking for first.")
                return
        self.coach_stop(quiet=True)
        self.coach_tree.delete(*self.coach_tree.get_children())
        self.coach_rows.clear()
        self._show_overlay()
        if self.plan["mode"] == "predict":
            self.predict_start()
            return
        if self.plan["mode"] == "event":
            self.hunt_start()
            return
        if self.plan["mode"] == "pulse":
            self.pulse_start()
            return
        self.coach = coachlib.Coach(self.plan)
        self.coach_token += 1
        self._coach_next()

    def coach_stop(self, quiet=False):
        self.coach_token += 1
        self.coach_wait = None
        self.hunting = False
        self.pulsing = False
        self.group_stop()
        self.testing = False
        self.ball_test = None
        self.deep = None
        self.predicting = False
        if self.overlay is not None and self.overlay.winfo_exists():
            self.overlay.show_plate(False)
        if self.overlay is not None and self.overlay.winfo_exists() and not quiet:
            self.overlay.set("Stopped.", "", done=False)
        if not quiet:
            self.coach_status.configure(text="Stopped.")

    def _coach_next(self):
        co = self.coach
        if co is None:
            return
        if co.done:
            self._coach_finish()
            return
        s = co.current()
        k = co.pos + 1
        progress = f"Step {k}  ·  {co.summary()}"
        self.coach_status.configure(text=progress)
        tok = self.coach_token
        if s.get("value") == "ask":
            self.coach_wait = "number"
            self.overlay.set(s["say"], progress, ask=True)
        elif s["until"] == "key":
            self.coach_wait = "key"
            self.overlay.set(s["say"], progress + "   ·   press ] when done", done=True)
        else:
            self.coach_wait = "timer"
            end = time.time() + s["secs"]

            def tick():
                if tok != self.coach_token:
                    return
                left = end - time.time()
                if left <= 0:
                    self._coach_apply(None)
                else:
                    self.overlay.set(s["say"], f"{progress}   ·   {left:0.0f}s", done=False)
                    self.root.after(200, tick)
            tick()

    def coach_key_done(self):
        if self.pulsing:
            return self.pulse_mark()
        if self.coach_wait == "key":
            self._coach_apply(None)

    def coach_number(self, text):
        try:
            v = float(text.replace(",", "").strip())
            v = int(v) if v == int(v) else v
        except ValueError:
            self.overlay.flash("Type just the number, e.g. 37")
            return
        self._coach_apply(v)

    def coach_skip(self):
        if self.coach and not self.coach.done:
            self.coach_token += 1
            self.coach._advance()
            self._coach_next()

    def _coach_apply(self, typed):
        co = self.coach
        if co is None or not self.ps2.attached:
            return
        self.coach_wait = None
        self.coach_token += 1
        self.overlay.set("Scanning...", co.summary(), done=False)
        self.root.update_idletasks()
        try:
            co.apply(self.snap(), typed)
        except ValueError as e:
            self.overlay.flash(str(e))
            self._coach_next()
            return
        if co.started and co.total <= 200:
            self._show_coach_results(co.results(self.snap()))
        self._coach_next()

    def _coach_finish(self):
        co = self.coach
        self.coach_wait = None
        res = co.results(self.snap()) if not co.failed else []
        self._show_coach_results(res)
        if co.failed:
            msg = ("Lost it - nothing matched every step. It may be stored differently "
                   "(e.g. as a percentage). Try rewording, or add a Claude key for a smarter plan.")
        elif len(res) <= co.r["target"]:
            msg = f"Found it! {len(res)} result(s) - see the tool window."
        elif co.stalled and len(res) <= 40:
            msg = (f"Down to {co.total:,} that all change together (the real one + copies). More rounds won't "
                   "split them - testing them myself now, don't touch anything.")
        else:
            msg = f"Narrowed down to {co.total:,} - not done yet. What next?"
            self.coach_status.configure(text=msg)
            self._offer_next(msg, co.total)
            return
        self.overlay.set(msg, "", done=False, close=True)
        self.coach_status.configure(text=msg)
        try:
            import winsound
            winsound.MessageBeep()
        except Exception:
            pass
        if not co.failed and 1 <= len(res) <= 40:
            self.root.after(1500, self.auto_test_scan)

    def _speedish(self):
        p = self.plan or {}
        return p.get("category") in ("Running", "Vehicle", "Jumping") or p.get("mode") == "pulse" or \
            any(w in (p.get("title") or "").lower() for w in ("speed", "jump", "velocity"))

    def _offer_next(self, msg, n):
        """Too many left: let the player choose how to finish."""
        btns = [("Keep narrowing", self.coach_more, "#22c55e"),
                ("Test with me (freeze)", lambda: self.group_test_start("hold"), "#60a5fa")]
        if self._speedish():
            btns.append(("Speed hack test", lambda: self.group_test_start("boost"), "#f59e0b"))
        btns.append(("Stop", self.coach_stop, "#9ca3af"))
        sub = ("Keep narrowing = a few more rounds of the same steps (keeps what's left).  Test with me = I hold "
               "half of them still and you tell me if the game reacted - about "
               f"{max(1, n - 1).bit_length()} questions.")
        self._show_overlay()
        self.overlay.choices(msg, sub, btns)

    def coach_more(self):
        co = self.coach
        if co is None or not co.started:
            messagebox.showinfo(APP_TITLE, "Start a search first.")
            return
        if co.failed:
            messagebox.showinfo(APP_TITLE, "That search lost the value - use 'Start over'.")
            return
        co.extend(3)
        self.coach_token += 1
        self._show_overlay()
        self.coach_status.configure(text=f"Keep narrowing from {co.total:,}...")
        self._coach_next()

    def _show_coach_results(self, rows, notes=None):
        self.coach_tree.delete(*self.coach_tree.get_children())
        self.coach_rows.clear()
        for i, (vt, addr, val) in enumerate(rows):
            iid = str(i)
            note = (notes or {}).get(addr, "")
            self.coach_tree.insert("", "end", iid=iid,
                                   values=(vt, f"{core.fa(addr, vt)}", core.fmt_value(vt, val), note))
            self.coach_rows[iid] = (vt, addr)

    def refresh_coach_values(self):
        if not self.ps2.attached:
            return
        for iid, (vt, addr) in list(self.coach_rows.items()):
            v = self.ps2.read(addr, vt)
            try:
                self.coach_tree.set(iid, "value", "?" if v is None else core.fmt_value(vt, v))
            except tk.TclError:
                pass

    # ---- pulse mode: jump / run / drive once, it rises and comes back ----
    def pulse_start(self):
        p = self.plan["pulse"]
        self.pulser = core.PulseHunter(p["mid"], p["post"], max(3, self.plan.get("target", 6)))
        self.pulsing = True
        self.pulse_busy = False
        self._pulse_prompt()

    def _pulse_prompt(self, extra=""):
        p, ph = self.plan["pulse"], self.pulser
        sub = (f"Try {ph.pulses + 1}  ·  {ph.count:,} candidates left" if ph.pulses else
               "Do it 4-6 times. Stand completely still between tries.")
        self.overlay.set(p["say"], (extra + "   " + sub).strip(), done=True)
        self.coach_status.configure(text=sub)

    def pulse_mark(self):
        if not self.pulsing or getattr(self, "pulse_busy", False) or not self.ps2.attached:
            return
        self.pulse_busy = True
        p, tok = self.plan["pulse"], self.coach_token
        pre = self.snap()
        t0 = time.perf_counter()
        verb = {"jump": "JUMP!", "run": "RUN!", "drive": "FLOOR IT!", "swim": "SWIM!", "fly": "GO!"}[p["kind"]]
        self.overlay.set(verb, "keep going...", done=False)

        def work():
            time.sleep(max(0.0, p["mid"] - (time.perf_counter() - t0)))
            mid = self.snap()
            if tok != self.coach_token:
                return
            stop = "Land and stand still..." if p["kind"] == "jump" else "STOP now and stand still..."
            self.ui(self.overlay.set, stop, "", False)
            time.sleep(max(0.0, p["post"] - (time.perf_counter() - t0)))
            post = self.snap()
            if tok != self.coach_token:
                return
            self.pulser.add(pre, mid, post)
            self.ui(self._pulse_after)
        threading.Thread(target=work, daemon=True).start()

    def _pulse_after(self):
        self.pulse_busy = False
        ph = self.pulser
        n = ph.count
        if n == 0:
            self.pulsing = False
            msg = ("Lost it - nothing rose and came back every time. Stand completely still before pressing ], "
                   "do the full action, and stop fully. Click 'Start over' to try again.")
            self.overlay.set(msg, "", close=True)
            self.coach_status.configure(text=msg)
            return
        if n <= 300:
            self._show_pulse_results()
        if ph.done or (ph.pulses >= 6 and n <= 2000):
            self.pulsing = False
            self._show_pulse_results()
            msg = f"Down to {n:,} after {ph.pulses} tries."
            btns = [("Test with me (freeze)", lambda: self.group_test_start("hold"), "#60a5fa"),
                    ("Speed hack test", lambda: self.group_test_start("boost"), "#f59e0b"),
                    ("Do more tries", self._pulse_resume, "#22c55e")]
            if n <= 12:
                btns.insert(0, ("Auto-test", self.auto_test_scan, "#22c55e"))
            self.coach_status.configure(text=msg)
            self.overlay.choices(msg, "Test with me: I hold them still - try to move and tell me if you're stuck. "
                                      "Speed hack test: I multiply them x3 - tell me if you're super fast.", btns)
            return
        self._pulse_prompt(f"Got it ({n:,} left).")

    def _pulse_resume(self):
        self.pulsing = True
        self._pulse_prompt()

    def _show_pulse_results(self):
        rows = [(vt, a, self.ps2.read(a, vt) or 0) for a, vt in self.pulser.candidates(60)]
        self._show_coach_results(rows, {a: "rose and came back every try" for _, a, _ in rows})

    # ---- test with me: hold / boost big groups, you judge ----
    def _group_candidates(self):
        if self.plan and self.plan.get("mode") == "pulse" and self.pulser and self.pulser.count:
            return self.pulser.candidates(6000)
        co = self.coach
        if co and co.started and co.total and all(sc.idx is not None for sc in co.scanners.values() if sc.active):
            return co.candidates(self.snap(), 6000)
        return [(a, vt) for vt, a in self.coach_rows.values()]

    def _group_action(self):
        """(what to do, what to look for) in plain words for the freeze test."""
        import re as _re
        p = self.plan or {}
        moving = "Are you STUCK or much SLOWER?"
        if p.get("mode") == "pulse":
            return ({"jump": "Try to JUMP.", "run": "Try to RUN.", "drive": "Floor it.", "swim": "Try to swim.",
                     "fly": "Try to fly forward."}[p["pulse"]["kind"]], moving if p["pulse"]["kind"] != "jump"
                    else "Can you NOT jump / only a tiny hop?")
        if p.get("category") == "Vehicle":
            return "Floor it.", moving
        if p.get("category") == "Running":
            return "Try to run.", moving
        thing = (p.get("title") or "it").lower()
        say = next((st["say"] for st in p.get("loop", [])
                    if st.get("scan") in ("decreased", "increased", "changed", "exact")), "")
        # keep just the action: drop "then type...", "press ]..." and the like
        say = _re.split(r"(?i)[.,;]?\s*(then )?(stop and )?(press \]|type|and press|click)", say)[0].strip(" .,")
        act = (say[:1].upper() + say[1:] + ".") if say else f"Make the {thing} change."
        return act, f"Did the {thing} on screen STAY THE SAME?"

    def group_test_start(self, effect):
        if not self.need_attach():
            return
        cands = self._group_candidates()
        if not cands:
            messagebox.showinfo(APP_TITLE, "Nothing to test yet - run a search first.")
            return
        self.pulsing = False
        self.gt = core.HumanGroupTest(cands)
        self.gt_effect = effect
        self._show_overlay()
        self._group_next()

    def _group_next(self):
        gt = self.gt
        if gt is None:
            return
        if gt.done:
            return self._group_finish()
        group = gt.next_group()
        self._gt_write_start(group)
        act, check = self._group_action()
        last = "  (Last one - is this it?)" if gt.confirming else ""
        if self.gt_effect == "hold":
            q = f"Holding {len(group):,} values still.{last}  {act}  -  {check}"
        else:
            q = f"Multiplying {len(group):,} values x3.{last}  {act}  -  Are you SUPER fast / way stronger?"
        self.pending_answer = (lambda: self._group_answer(True), lambda: self._group_answer(False))
        self.overlay.choices(q, f"Keys: ] = YES   ' = NO.   {gt.status()}. The next group starts as soon as you "
                                "answer. If the game glitches, answer NO - everything goes back.",
                             [("YES  ]", lambda: self._group_answer(True), "#22c55e"),
                              ("NO  '", lambda: self._group_answer(False), "#f97316"),
                              ("Not sure - again", lambda: self._group_answer(None), "#9ca3af"),
                              ("Stop", self.group_stop_ui, "#6b7280")])
        self.coach_status.configure(text=f"Test with me: {gt.status()}")

    def _gt_write_start(self, group):
        self.gt_token += 1
        tok = self.gt_token
        effect = self.gt_effect
        held = {}
        if effect == "hold":
            for a, vt in group:
                v = self.ps2.read(a, vt)
                if v is not None and v == v:
                    held[(a, vt)] = v

        def work():
            last, peak = {}, {}
            while tok == self.gt_token and self.ps2.attached:
                if effect == "hold":
                    for (a, vt), v in held.items():
                        self.ps2.write(a, vt, v)
                else:
                    for a, vt in group:
                        cur = self.ps2.read(a, vt)
                        if cur is None or cur != cur:
                            continue
                        lw = last.get((a, vt))
                        if lw is not None and abs(cur - lw) <= 1e-5 * max(1.0, abs(lw)):
                            continue
                        peak[(a, vt)] = max(peak.get((a, vt), 0.0), abs(cur))
                        cap = max(1.0, peak[(a, vt)]) * 4.5
                        w = max(-cap, min(cap, cur * 3.0))
                        if vt != "float":
                            w = int(round(w))
                            if w < 0 or w >= 1 << (8 * core.TYPES[vt][2]):
                                continue
                        self.ps2.write(a, vt, w)
                        last[(a, vt)] = self.ps2.read(a, vt)
                time.sleep(0.002 if len(group) <= 200 else 1 / 60)   # small groups: hold them hard
        threading.Thread(target=work, daemon=True).start()

    def group_stop(self):
        self.gt_token += 1

    def group_stop_ui(self):
        self.pending_answer = None
        self.group_stop()
        self.gt = None
        self.overlay.set("Stopped the test - everything is back to normal.", "", close=True)

    def _group_answer(self, yes):
        self.pending_answer = None
        self.group_stop()
        if self.gt is None:
            return
        self.gt.answer(yes)
        self.overlay.set("OK..." if yes is not None else "Again...", "", close=True)
        self.root.after(600, self._group_next)

    def _group_finish(self):
        gt = self.gt
        self.group_stop()
        if gt.found:
            a, vt = gt.found
            how = "holding it stopped you" if self.gt_effect == "hold" else "multiplying it made you super fast"
            self._show_coach_results([(vt, a, self.ps2.read(a, vt) or 0)],
                                     {a: f"CONFIRMED BY YOU - {how} ({gt.asked} questions)"})
            self.coach_tree.selection_set("0")
            msg = f"FOUND IT: {core.fa(a, vt)} ({vt}) - {how}."
            btns = [("Save to library", self.coach_save, "#22c55e")]
            if self._speedish():
                btns.append(("Speed hack ON/OFF", self.speed_hack_toggle, "#f59e0b"))
            self.overlay.choices(msg, "", btns)
        else:
            msg = ("None of them did it - the value isn't in this set. Try 'Keep narrowing' with different "
                   "steps, or 'Start over'.")
            self.overlay.set(msg, "", close=True)
        self.coach_status.configure(text=msg)
        self.gt = None

    def speed_hack_toggle(self):
        sel = self.coach_tree.selection()
        if not sel or sel[0] not in self.coach_rows:
            messagebox.showinfo(APP_TITLE, "Select the speed value in the results first.")
            return
        vt, a = self.coach_rows[sel[0]]
        ent = next((e for e in self.library if e.get("kind") == "value" and e["addr"] == a and e["type"] == vt), None)
        if ent is None:
            name = (self.plan or {}).get("title") or "Speed"
            base, n = name, 2
            while any(e["name"] == name for e in self.library):
                name, n = f"{base} {n}", n + 1
            ent = core.new_value_entry(name, (self.plan or {}).get("category") or "Running", a, vt)
            self.library.append(ent)
            self.library_changed()
        c = next((c for c in self.cheats if c.get("entry") == ent["name"] and c.get("mode") == "scale"), None)
        if c is None:
            c = {"name": f"Speed hack x3 ({ent['name']})", "entry": ent["name"], "mode": "scale", "value": 3.0,
                 "hotkey": [], "group": "Cheats", "activator": None}
            self.cheats.append(c)
            self.save_library(self.lib_path, quiet=True)
            self.refresh_cheat_tree()
        c["on"] = not c.get("on")
        c["_manual"] = c["on"]
        c.pop("_last", None)
        ph = self.pulser
        if ph is not None and getattr(ph, "last_mid", None) is not None:    # top speed seen while you ran
            v = core.decode(vt, ph.last_mid[a:a + core.TYPES[vt][2]].tobytes())
            if v == v and abs(v) > 0:
                c.setdefault("_nat", {})[a] = max(c.get("_nat", {}).get(a, 0.0), abs(v))
        msg = (f"Speed hack x3 is ON for {ent['name']} - run / drive! (It's also in Cheats & mod menu: give it a "
               "hotkey or change x3 there.)" if c["on"] else "Speed hack OFF.")
        self.say(msg)
        if self.overlay is not None and self.overlay.winfo_exists():
            self.overlay.flash(msg[:70])

    # ---- event mode: Auto hunt ----
    def hunt_start(self):
        self.hunter = core.AutoHunter()
        src = self.hit_source.get()
        ent = next((e for e in self.library if e["name"] == src), None)
        self.hunt_detector = (core.HitDetector(), ent) if ent else None
        self.hunting = True
        self.hunt_t0 = time.perf_counter()
        say = self.plan["event"]["say"]
        if ent:
            say = (f"Play normally - hits are detected automatically from '{ent['name']}'. "
                   "You can also press ] at contact.")
        self.overlay.set(say, "Watching all of memory...", done=False)
        threading.Thread(target=self._hunt_thread, daemon=True).start()
        self._hunt_tick()

    def _hunt_thread(self):
        period = 1 / 15
        nxt = time.perf_counter()
        while self.hunting and self.ps2.attached:
            snap = self.snap()
            t = time.perf_counter() - self.hunt_t0
            with self.hunt_lock:
                if self.hunt_detector:
                    det, ent = self.hunt_detector
                    v = core.decode(ent["type"], snap[ent["addr"]:ent["addr"] + core.TYPES[ent["type"]][2]].tobytes())
                    if det.step(t, v) and self.hunter.mark(t):
                        self.ui(self._on_ball_hit)
                self.hunter.feed(t, snap)
            nxt += period
            d = nxt - time.perf_counter()
            if d > 0:
                time.sleep(d)
            else:
                nxt = time.perf_counter()

    def hunt_mark(self):
        if self.hunting and self.hunter:
            with self.hunt_lock:
                ok = self.hunter.mark(time.perf_counter() - self.hunt_t0)
            if ok:
                self.overlay.flash(f"Hit #{len(self.hunter.marks)} marked")
                self._on_ball_hit()

    def _hunt_tick(self):
        h = self.hunter
        if not self.hunting or h is None:
            return
        with self.hunt_lock:
            last = h.log[-1] if h.log else "Watching all of memory... hit the ball and press ]."
            results = list(h.results[:25])
        best = results[0] if results and results[0]["score"] >= 0.25 else None
        bt = self.ball_test
        vel = [r for r in results if r["kind"] in ("speed", "vspeed") and r["score"] >= 0.25]
        if bt is None and vel and h.hits >= 4:
            cands = [r["addr"] for r in vel[:6]]
            self.ball_test = bt = {"queue": list(cands), "cands": cands,
                                   "results": [], "busy": False, "done": False}
        dp = self.deep
        if dp and dp["done"]:
            head, last = dp["message"], "Deep test finished."
        elif dp:
            gt = dp["gt"]
            head = (f"DEEP TEST: {gt.remaining():,} values still in play, {len(gt.queue)} group(s) "
                    "to check - keep hitting! (save a state with F1 first, in case the game glitches)")
            last = gt.log[-1] if gt.log else "Changing hundreds of values at once on the next hit..."
        elif bt and bt["done"]:
            head, last = bt["message"], "Testing finished."
        elif bt:
            left = len(bt["queue"])
            head = (f"Found {len(bt['cands'])} possible ball speeds. Now testing which one really "
                    "moves the ball - keep hitting!")
            last = f"{left} test(s) left - one per hit. " + last
        elif best:
            head = (f"Got it: {core.fa(best['addr'])} = {core.KIND_LABELS[best['kind']].split(' (')[0].lower()}. "
                    "Keep hitting - I'll test it for real next.")
        else:
            head = self.plan["event"]["say"]
        self.coach_status.configure(text=last)
        self.overlay.set(head, last, done=False)
        if results:
            tests = {r["addr"]: r for r in core.rank_tests(bt["results"])} if bt else {}
            order = sorted(results, key=lambda r: (-(tests[r["addr"]]["score"] if r["addr"] in tests else -1),
                                                   -r["score"]))
            rows = [("float", r["addr"], self.ps2.read(r["addr"], "float") or 0.0) for r in order]
            notes = {}
            for r in order:
                t = tests.get(r["addr"])
                tag = (f"TEST: {core.TEST_VERDICTS[t['verdict']]}  {t.get('note', '')}  |  " if t else "")
                notes[r["addr"]] = (tag + f"{core.KIND_LABELS[r['kind']]}  score {r['score']:.2f}  "
                                    f"reversed at {r['flips']}/{r['hits']} hits")
            self._show_coach_results(rows, notes)
        self.root.after(400, self._hunt_tick)

    def _on_ball_hit(self):
        """Each hit, test up to two candidates while the ball is in the air: triple one,
        watch whether the ball reacts, then the next."""
        if self.deep is not None:
            self._deep_on_hit()
            return
        bt = self.ball_test
        if not bt or bt["busy"] or bt["done"] or not bt["queue"]:
            return
        batch = bt["queue"][:2]
        del bt["queue"][:2]
        bt["busy"] = True

        def work():
            time.sleep(0.2)          # let the ball leave the bat
            out = []
            for addr in batch:
                others = [(a, "float") for a in bt["cands"] if a != addr]
                near = [(addr + d, "float") for d in range(-24, 28, 4)
                        if d and addr + d not in bt["cands"]]
                try:
                    r = core.effect_test(self.ps2.read, self.ps2.write, (addr, "float"), others, near,
                                         mode="scale", factor=3.0, base_secs=0.15, test_secs=0.45)
                except Exception as e:  # never kill the hunt over one test
                    r = {"addr": addr, "type": "float", "verdict": "skipped", "score": 0, "note": str(e)}
                out.append(r)
            self.ui(self._ball_test_done, out)
        threading.Thread(target=work, daemon=True).start()

    # ---- deep test: many values at once, halve until found ----
    def deep_start(self):
        h = self.hunter
        if not self.hunting or h is None:
            if self.overlay is not None:
                self.overlay.flash("Deep test runs during a ball hunt - start one first")
            return
        with self.hunt_lock:
            res = list(h.results)
        top = [r["addr"] for r in res if r["kind"] in ("height", "speed", "vspeed")
               and r["score"] >= 0.2][:4]
        # the ball's position usually sits right next to its speed values
        watch = list(dict.fromkeys(top + [a + d for a in top for d in (-16, -12, -8, -4, 4, 8, 12, 16)]))
        if not watch:
            self.overlay.flash("Need the ball's position first - keep hitting")
            self.root.after(3000, self.deep_start)
            return
        with self.hunt_lock:
            pool = h.deep_pool(limit=4096, exclude=[a // 4 for a in watch])
        if not pool:
            self.overlay.flash("Nothing left to test")
            return
        self.deep = {"gt": core.GroupTester([i * 4 for i in pool], group_size=512, max_tests=70),
                     "watchers": watch, "busy": False, "done": False, "message": ""}
        self.coach_status.configure(text=f"Deep test: {len(pool):,} values, watching the ball through "
                                         f"{len(watch)} value(s).")

    def _deep_on_hit(self):
        d = self.deep
        if not d or d["busy"] or d["done"]:
            return
        d["busy"] = True
        gt = d["gt"]

        def work():
            time.sleep(0.2)
            for _ in range(2):                   # two tests per flight
                g = gt.next_group()
                if g is None:
                    break
                try:
                    r = core.group_effect_test(self.ps2.read, self.ps2.write, g, d["watchers"], factor=3.0)
                except Exception as e:
                    r = {"result": "inconclusive", "ratio": 0, "written": 0, "error": str(e)}
                self.ui(self._deep_record, g, r)
                if r["result"] == "inconclusive":
                    break                          # ball probably landed; wait for the next hit
            self.ui(self._deep_hit_done)
        threading.Thread(target=work, daemon=True).start()

    def _deep_record(self, g, r):
        d = self.deep
        if d:
            d["gt"].record(g, r)

    def _deep_hit_done(self):
        d = self.deep
        if not d:
            return
        d["busy"] = False
        gt = d["gt"]
        if gt.log:
            self.overlay.flash(gt.log[-1][:70])
        if not gt.done:
            return
        d["done"] = True
        if gt.found:
            # skip timers / counters (they keep changing while the ball flies) for the boost
            steady = []
            for a, _ in sorted(gt.found, key=lambda x: -x[1]):
                v1 = self.ps2.read(a, "float"); time.sleep(0.12); v2 = self.ps2.read(a, "float")
                if v1 is not None and v2 is not None and abs(v2 - v1) <= 1e-4 * max(1.0, abs(v1)):
                    steady.append(a)
            addrs = (steady or [a for a, _ in gt.found])[:3]
            for cb in self.boost_axes:
                cb.set("")
            for cb, a in zip(self.boost_axes, addrs):
                cb.set(f"{core.fa(a)}")
            flips = {r["addr"]: r["flips"] for r in (self.hunter.results if self.hunter else [])}
            vel_like = any(flips.get(a, 0) > 0 for a in addrs)
            self.boost_trigger.set(BOOST_TRIGGERS[0] if vel_like else BOOST_TRIGGERS[1])
            d["message"] = (f"FOUND what really drives the ball: {', '.join(f'{core.fa(a)}' for a in addrs)}. "
                            "Filled into Power boost - open it and click Start boost.")
            rows = [("float", a, self.ps2.read(a, "float") or 0.0) for a in addrs]
            self._show_coach_results(rows, {a: f"DEEP TEST: changing this moved the ball "
                                               f"({r:.1f}x off its path)" for a, r in gt.found})
        else:
            d["message"] = ("Deep test: nothing in memory changes the ball after contact. The game "
                            "keeps the real value somewhere the tool can't reach while the ball flies - "
                            "see 'CODE PATCH' in the How to use tab for the next step.")

    def _ball_test_done(self, rs):
        bt = self.ball_test
        if not bt:
            return
        bt["busy"] = False
        for r in rs:
            bt["results"].append(r)
            if r["verdict"] == "skipped" and \
                    sum(1 for x in bt["results"] if x["addr"] == r["addr"]) < 3:
                bt["queue"].append(r["addr"])    # try again on a later hit
        self.overlay.flash("Tested " + ", ".join(f"{core.fa(r['addr'])}: {r['verdict'].upper()}" for r in rs))
        if bt["queue"]:
            return
        ranked = core.rank_tests(bt["results"])
        real = [x for x in ranked if x["verdict"] == "controls"]
        kinds = {x["addr"]: x["kind"] for x in (self.hunter.results if self.hunter else [])}
        if real:
            # box 1 = forward (fastest at contact), box 2 = vertical, box 3 = sideways
            vert = [x for x in real if kinds.get(x["addr"]) == "vspeed"]
            rest = sorted([x for x in real if x not in vert], key=lambda x: -abs(x.get("orig") or 0))
            real = rest[:1] + vert[:1] + rest[1:] + vert[1:]
            for cb in self.boost_axes:
                cb.set("")
            for cb, x in zip(self.boost_axes, real[:3]):
                cb.set(f"{core.fa(x['addr'])}")
            bt["message"] = (f"REAL ball speed found: {core.fa(real[0]['addr'], real[0].get('type'))}"
                             + (f" (+{len(real) - 1} more)" if len(real) > 1 else "")
                             + ". Filled into Power boost - open that tab and click Start boost.")
        else:
            bt["message"] = ("Those were copies. Starting the DEEP TEST: changing hundreds of values "
                             "at once and narrowing down - keep hitting.")
            self.root.after(500, self.deep_start)
        bt["done"] = True

    # ---- predict mode: where will the CPU throw? ----
    def predict_start(self):
        self.predictor = core.LaunchPredictor()
        self.zone_labels = []
        self.predicting = True
        self.pred_t0 = time.perf_counter()
        self.pred_lock = threading.Lock()
        self.overlay.set(self.plan["event"]["say"], "Watching memory...", done=False)
        threading.Thread(target=self._predict_thread, daemon=True).start()
        self._predict_tick()

    def _predict_thread(self):
        period = 1 / 15
        nxt = time.perf_counter()
        while self.predicting and self.ps2.attached:
            snap = self.snap()
            with self.pred_lock:
                self.predictor.feed(time.perf_counter() - self.pred_t0, snap)
                burst = self.predictor.wants_burst()
            if burst:                      # ball just released: grab snapshots back to back
                nxt = time.perf_counter()
                continue
            nxt += period
            d = nxt - time.perf_counter()
            if d > 0:
                time.sleep(d)
            else:
                nxt = time.perf_counter()

    def predict_mark(self):
        if not self.predicting:
            return
        with self.pred_lock:
            ok = self.predictor.mark(time.perf_counter() - self.pred_t0)
        if ok:
            self.overlay.flash(f"Release #{len(self.predictor.pitches)} marked")

    def predict_export(self):
        lp = getattr(self, "predictor", None)
        if not lp or not lp.pitches:
            messagebox.showinfo(APP_TITLE, "Run the pitch predictor first (AI Coach -> I want to: predict).")
            return
        with self.pred_lock:
            data = lp.export()
        path = os.path.abspath(f"predictor_findings_{time.strftime('%Y%m%d_%H%M%S')}.json")
        with open(path, "w") as f:
            json.dump(data, f, indent=1, default=str)
        messagebox.showinfo(APP_TITLE, f"Saved {path}\n\nIt holds every pitch's plate location, the values "
                            "that were set before each wind-up, and what the predictor decided. You can send "
                            "this file to Claude to dig through it.")
        return path

    def zone_label(self, strike):
        """; / ' after a pitch: label the pitch you just watched (even if it's still landing)."""
        lp = self.predictor
        if not lp or not lp.pitches:
            self.overlay.flash("No pitch to label yet - press ] at release first")
            return
        with self.pred_lock:
            lp.pitches[-1]["label"] = bool(strike)
        self.overlay.flash(f"That pitch = {'STRIKE' if strike else 'BALL'} - teaching the zone")

    def _labeled(self):
        lp = self.predictor
        cols = getattr(lp, "axis_cols", None) if lp else None
        if not cols:
            return []
        return [({"h": float(p["outcome"][cols[0]]), "v": float(p["outcome"][cols[1]])}, p["label"])
                for p in lp.pitches if p.get("label") is not None and p["outcome"] is not None]

    def strike_zone(self):
        """(h0, h1, v0, v1, how) in the game's own units."""
        lp = self.predictor
        outs = lp.outcomes() if lp else []
        if len(outs) < 3:
            return None
        hs = np.array([o["h"] for o in outs]); vs = np.array([o["v"] for o in outs])
        k = self.zone_scale.get() / 100.0
        ch, cv = float(np.median(hs)), float(np.median(vs))
        wh = (float(np.percentile(hs, 85)) - float(np.percentile(hs, 15))) / 2 * k
        wv = (float(np.percentile(vs, 85)) - float(np.percentile(vs, 15))) / 2 * k
        est = (ch - wh, ch + wh, cv - wv, cv + wv, "estimated")
        lab = self._labeled()
        strikes = [o for o, s in lab if s]
        if len(strikes) < 3:
            return est
        sh, sv = [o["h"] for o in strikes], [o["v"] for o in strikes]
        if max(sh) - min(sh) < 0.2 * wh or max(sv) - min(sv) < 0.2 * wv:
            return est                         # strikes all in one spot - not enough to shape the box
        ph, pv = (max(sh) - min(sh)) * 0.08, (max(sv) - min(sv)) * 0.08
        box = [min(sh) - ph, max(sh) + ph, min(sv) - pv, max(sv) + pv]
        # shrink away from balls that landed inside it
        for o, s in lab:
            if not s and box[0] < o["h"] < box[1] and box[2] < o["v"] < box[3]:
                dl, dr = o["h"] - box[0], box[1] - o["h"]
                db, dt = o["v"] - box[2], box[3] - o["v"]
                m = min(dl, dr, db, dt)
                if m == dl: box[0] = o["h"]
                elif m == dr: box[1] = o["h"]
                elif m == db: box[2] = o["v"]
                else: box[3] = o["v"]
        return (*box, f"learned from {len(lab)} calls")

    def _predict_tick(self):
        lp = self.predictor
        if not self.predicting or lp is None:
            return
        with self.pred_lock:
            log = list(lp.log[-3:])
            phase = lp.phase
            n = len(lp.pitches)
        last = log[-1] if log else "Press ] the moment the ball leaves the pitcher's hand."
        if phase != "ready":
            head = {"ball": f"Step 1/2 - finding the ball. Press ] at every release ({n} so far).",
                    "learn": f"Step 2/2 - ball found! Keep pressing ] at release - swing or take, "
                             f"every pitch counts. Searching memory for the target the CPU picks "
                             f"before it throws ({n} so far)."}[phase]
            self.overlay.show_plate(False)
            self.overlay.set(head, last, done=False)
            self.coach_status.configure(text=last)
        else:
            with self.pred_lock:
                pred = lp.predict(self.ps2.read)
                acc = lp.accuracy_report()
                outs = lp.outcomes()[-12:]
            zone = self.strike_zone()
            label = ""
            extra = ""
            if pred and pred.get("new"):
                extra = f"Zone #{pred['zone']} - never seen it yet, learning it this pitch.   "
                pred = None
            elif pred and "zone" in pred:
                extra = f"CPU picked zone #{pred['zone']}.   "
            if pred and zone:
                inside = zone[0] <= pred["h"] <= zone[1] and zone[2] <= pred["v"] <= zone[3]
                label = "STRIKE" if inside else "BALL"
            fresh = pred is not None and (self.last_pred is None or
                                          abs(pred["h"] - self.last_pred["h"]) > 1e-4 or
                                          abs(pred["v"] - self.last_pred["v"]) > 1e-4)
            if fresh:
                self.pred_fresh_t = time.time()
            self.last_pred = pred
            info = extra + (f"zone {zone[4]} (; = strike  ' = ball to calibrate)" if zone else "")
            if acc:
                info = f"right on {acc['n']} checked pitches (avg miss {acc['avg_err']:.2f})   " + info
            new = time.time() - getattr(self, "pred_fresh_t", 0) < 1.5
            self.overlay.show_plate(True)
            self.overlay.draw_plate(pred, zone, outs, label, info,
                                    flip_h=self.flip_h.get(), flip_v=self.flip_v.get(), new=new)
            self.coach_status.configure(text="PREDICTOR READY - " + last)
            if lp.zone:
                z = lp.zone
                vt = "u32" if z["part"] == "u32" else "byte"
                addr = z["addr"] + (0 if z["part"] == "u32" else int(z["part"][1]))
                rows = [(vt, addr, self.ps2.read(addr, vt) or 0)]
                notes = {addr: f"CPU's chosen ZONE number - set before the wind-up; {len(z['table'])} "
                               f"zones learned, explains {z['score'] * 100:.0f}% of where pitches go"}
            else:
                rows = [("float", p["idx"] * 4, self.ps2.read(p["idx"] * 4, "float") or 0.0)
                        for p in lp.predictors.values()]
                notes = {p["idx"] * 4: f"CPU's chosen target ({'left/right' if k == 'h' else 'up/down'}) - "
                                       f"match {abs(p['r']):.2f} over {p['n']} pitches"
                                       f"{', set 1.2s+ before release' if p['early'] else ''}"
                         for k, p in lp.predictors.items()}
            if set(self.coach_rows.values()) != {(vt, a) for vt, a, _ in rows}:
                self._show_coach_results(rows, notes)
        self.root.after(50, self._predict_tick)

    # ---- scan-mode auto-test ----
    def auto_test_scan(self):
        if self.testing or not self.coach_rows or not self.need_attach():
            return
        if self.hunting:
            messagebox.showinfo(APP_TITLE, "Ball hunts test themselves between hits.")
            return
        plan = self.plan or {}
        physics = plan.get("category") in ("Vehicle", "Running") and not any(
            s.get("scan") == "exact" for s in plan.get("steps", []) + plan.get("loop", []))
        rows = list(self.coach_rows.values())[:12 if physics else 40]
        # copies tend to sit in a cluster (render / HUD buffers); the real one is usually off on its own:
        # test the loners first so we can stop early
        rows.sort(key=lambda r: sum(1 for x in rows if x is not r and abs(x[1] - r[1]) < 0x2000))
        mode = "scale" if physics else "offset"
        self._at_physics = physics
        self._cf_busy = False
        self._show_overlay()
        say = ("Testing which value is REAL. Keep moving at a steady speed - don't stop - for about "
               f"{len(rows) * 1.2:.0f} seconds." if physics else
               f"Testing which value is REAL. Don't touch anything for about {len(rows) * 1.1:.0f} seconds.")
        self.overlay.set(say, "", done=False)
        self.testing = True
        self.test_results = []

        def work():
            for i, (vt, addr) in enumerate(rows):
                if not self.testing:
                    break
                others = [(a, t) for t, a in rows if a != addr]
                o = self.ps2.read(addr, vt) or 0
                delta = -7 if abs(o) >= 8 else 3
                try:
                    r = core.effect_test(self.ps2.read, self.ps2.write, (addr, vt), others, [],
                                         mode=mode, factor=2.0, delta=delta,
                                         base_secs=0.25, test_secs=0.6)
                except Exception as e:
                    r = {"addr": addr, "type": vt, "verdict": "skipped", "score": 0, "note": str(e)}
                self.test_results.append(r)
                self.ui(self.overlay.flash, f"{i + 1}/{len(rows)}: {core.fa(addr, vt)} {r['verdict'].upper()}")
                if r["verdict"] == "controls" and not physics:
                    break                   # found the real one - the rest just follow it
                time.sleep(0.3)
            self.ui(self._auto_test_done)
        threading.Thread(target=work, daemon=True).start()

    def _auto_test_done(self):
        self.testing = False
        ranked = core.rank_tests(self.test_results)
        rows = [(r["type"], r["addr"], self.ps2.read(r["addr"], r["type"]) or 0) for r in ranked]
        notes = {r["addr"]: f"TEST: {core.TEST_VERDICTS[r['verdict']]}  {r.get('note', '')}" for r in ranked}
        self._show_coach_results(rows, notes)
        real = [r for r in ranked if r["verdict"] == "controls"]
        kept = [r for r in ranked if r["verdict"] == "kept"]
        if real:
            msg = f"The REAL one is {core.fa(real[0]['addr'], real[0].get('type'))}" + (
                f" (and {len(real) - 1} more)" if len(real) > 1 else "") + ". Use that one for cheats."
        elif all(r["verdict"] == "skipped" for r in ranked):
            msg = "Couldn't test (values were 0). Try again while it's moving / not empty."
        elif not getattr(self, "_at_physics", False) and not getattr(self, "_cf_busy", False):
            # not sure yet: ask the player to look, then test the neighbours
            self._cf_busy = True
            self.coach_status.configure(text="Not sure yet - checking on screen, then testing neighbours...")
            self._confirm_start(kept, ranked)
            return
        elif kept:
            msg = (f"Best guess: {core.fa(kept[0]['addr'], kept[0].get('type'))} - the game kept the change, "
                   "but nothing visibly followed. Check the game screen.")
        else:
            msg = ("All of these are COPIES the game recalculates. The real value is stored somewhere "
                   "else or in another form - try the plan again with different types, or use the "
                   "Scanner with 'float'.")
        if self.coach_rows:
            self.coach_tree.selection_set("0")
        self.overlay.set(msg, "", done=False, close=True)
        self.coach_status.configure(text=msg)

    # ---- "not sure" -> look at the screen, then try the neighbours ----
    def _confirm_start(self, kept, ranked, round2=False):
        self._cf = {"queue": [r for r in kept if r["verdict"] == "kept"][:3], "ranked": ranked,
                    "round2": round2, "tested": {(r["addr"], r["type"]) for r in self.test_results}}
        self._confirm_next()

    def _confirm_next(self):
        cf = self._cf
        if not cf["queue"]:
            return self._neighbour_round() if not cf["round2"] else self._confirm_give_up()
        r = cf["queue"].pop(0)
        addr, vt = r["addr"], r["type"]
        orig = self.ps2.read(addr, vt)
        if orig is None:
            return self._confirm_next()
        show = 77 if abs(orig - 77) > 2 else 55
        if vt == "byte" and orig > 200:
            show = 199
        self.ps2.write(addr, vt, float(show) if vt == "float" else show)
        self._holds.append((addr, vt, float(show) if vt == "float" else show, time.time() + 30))
        cf["cur"] = (addr, vt, orig)
        self._show_overlay()
        self.pending_answer = (lambda: self._confirm_answer(True), lambda: self._confirm_answer(False))
        self.overlay.ask_yes_no(f"Look at the game: does it show {show} now?   (] = YES   ' = NO)",
                                f"(testing {core.fa(addr, vt)} - it was {core.fmt_value(vt, orig)}; "
                                "the menu or HUD may need a moment to redraw)",
                                lambda: self._confirm_answer(True), lambda: self._confirm_answer(False))

    def _confirm_answer(self, yes):
        self.pending_answer = None
        addr, vt, orig = self._cf["cur"]
        self._holds = [h for h in self._holds if (h[0], h[1]) != (addr, vt)]
        self.ps2.write(addr, vt, orig)
        if yes:
            for r in self.test_results:
                if (r["addr"], r["type"]) == (addr, vt):
                    r["verdict"], r["note"] = "controls", "CONFIRMED on screen by you"
            if not any((r["addr"], r["type"]) == (addr, vt) for r in self.test_results):
                self.test_results.append({"addr": addr, "type": vt, "verdict": "controls", "score": 1.0,
                                          "note": "CONFIRMED on screen by you"})
            self._cf_busy = False
            self._auto_test_done()
            return
        self._confirm_next()

    def _neighbour_round(self):
        """The real value often sits right next to what we found (a copy, the max, a float twin)."""
        cf = self._cf
        seeds = [r for r in cf["ranked"] if r["verdict"] in ("kept", "copy")][:4]
        cands = []
        for r in seeds:
            v0 = self.ps2.read(r["addr"], r["type"])
            if v0 is None:
                continue
            base = r["addr"] & ~3
            for off in range(-0x40, 0x44, 1):
                a = base + off
                for vt in core.TYPES:
                    size = core.TYPES[vt][2]
                    if a % size or (a, vt) in cf["tested"] or any(c == (a, vt) for c in cands):
                        continue
                    # skip anything overlapping a value already tested (writing it would drag that one along)
                    if any(a < ta + core.TYPES[tt][2] and ta < a + size for ta, tt in cf["tested"]):
                        continue
                    v = self.ps2.read(a, vt)
                    if v is None or v != v:
                        continue
                    same = abs(v - v0) <= max(0.5, 0.01 * abs(v0))
                    scaled = v0 and any(abs(v - v0 * k) <= 0.01 * abs(v0 * k) for k in (100, 0.01, 10, 0.1))
                    if (same or scaled) and abs(v) > 0:
                        cands.append((a, vt))
        cands = cands[:20]
        if not cands:
            return self._confirm_give_up()
        self.overlay.set(f"Not sure yet - testing {len(cands)} neighbouring values. Don't touch anything "
                         f"for about {len(cands)} seconds.", "", close=False)
        self.testing = True
        rows = list(self.coach_rows.values())[:12]

        def work():
            for i, (a, vt) in enumerate(cands):
                if not self.testing:
                    break
                o = self.ps2.read(a, vt) or 0
                try:
                    r = core.effect_test(self.ps2.read, self.ps2.write, (a, vt), [(x, t) for t, x in rows], [],
                                         mode="offset", delta=-7 if abs(o) >= 8 else 3, base_secs=0.25,
                                         test_secs=0.6)
                except Exception as e:
                    r = {"addr": a, "type": vt, "verdict": "skipped", "score": 0, "note": str(e)}
                r["note"] = ("NEIGHBOUR " + r.get("note", "")).strip()
                self.test_results.append(r)
                self.ui(self.overlay.flash, f"neighbour {i + 1}/{len(cands)}: {core.fa(a, vt)} {r['verdict'].upper()}")
                if r["verdict"] == "controls":
                    break
                time.sleep(0.2)
            self.ui(self._neighbours_done)
        threading.Thread(target=work, daemon=True).start()

    def _neighbours_done(self):
        self.testing = False
        ranked = core.rank_tests(self.test_results)
        if any(r["verdict"] == "controls" for r in ranked):
            self._cf_busy = False
            return self._auto_test_done()
        kept = [r for r in ranked if r["verdict"] == "kept" and "NEIGHBOUR" in r.get("note", "")]
        self._cf = {"queue": kept[:3], "ranked": ranked, "round2": True,
                    "tested": {(r["addr"], r["type"]) for r in self.test_results}}
        self._confirm_next()

    def _confirm_give_up(self):
        self._cf_busy = False
        ranked = core.rank_tests(self.test_results)
        rows = [(r["type"], r["addr"], self.ps2.read(r["addr"], r["type"]) or 0) for r in ranked]
        self._show_coach_results(rows, {r["addr"]: f"TEST: {core.TEST_VERDICTS[r['verdict']]}  {r.get('note', '')}"
                                        for r in ranked})
        msg = ("Couldn't pin it down: none of these or their neighbours changed what's on screen. The game "
               "probably keeps the real value in another form - run the plan again with 'any type', or use "
               "the Recorder with an event that fits.")
        self.overlay.set(msg, "", close=True)
        self.coach_status.configure(text=msg)

    # ---- result actions ----
    def _coach_selected(self):
        sel = self.coach_tree.selection()
        if not sel:
            messagebox.showinfo(APP_TITLE, "Select a result first.")
            return None
        return self.coach_rows.get(sel[0])

    def _coach_selected_all(self):
        out = [self.coach_rows[i] for i in self.coach_tree.selection() if i in self.coach_rows]
        if not out:
            messagebox.showinfo(APP_TITLE, "Select one or more results first (Ctrl/Shift-click for several).")
        return [(a, vt) for vt, a in out]

    def coach_toggle_freeze(self):
        sel = self._coach_selected_all()
        if not sel or not self.need_attach():
            return
        on = any(k not in self.sc_frozen for k in sel)
        for a, vt in sel:
            if on:
                v = self.ps2.read(a, vt)
                if v is not None:
                    self.sc_frozen[(a, vt)] = v
            else:
                self.sc_frozen.pop((a, vt), None)
        for iid, (vt, a) in self.coach_rows.items():
            note = self.coach_tree.set(iid, "note").replace("[FROZEN] ", "")
            self.coach_tree.set(iid, "note", ("[FROZEN] " if (a, vt) in self.sc_frozen else "") + note)
        self.say(f"{'Froze' if on else 'Unfroze'} {len(sel)} value(s).")

    def coach_quick_add(self):
        sel = self._coach_selected_all()
        if not sel:
            return
        title = (self.plan or {}).get("title") or "Unnamed"
        have = {e["name"] for e in self.library}
        added = 0
        for a, vt in sel:
            if any(e.get("kind") == "value" and e["addr"] == a and e["type"] == vt for e in self.library):
                continue
            n = 1
            while f"{title}? {n} ({vt})" in have:
                n += 1
            name = f"{title}? {n} ({vt})"
            have.add(name)
            e = core.new_value_entry(name, "Unsorted", a, vt)
            if (a, vt) in self.sc_frozen:
                e["freeze"], e["freeze_value"] = True, self.sc_frozen.pop((a, vt))
            self.library.append(e)
            added += 1
        self.library_changed()
        self._refresh_hit_sources()
        self.say(f"Added {added} to the library under 'Unsorted' - rename the right one when you're sure.")

    def coach_save(self):
        item = self._coach_selected()
        if not item:
            return
        vt, addr = item
        title = self.plan["title"] if self.plan else "Value"
        note = self.coach_tree.set(self.coach_tree.selection()[0], "note")
        if "FORWARD" in note:
            title = "Ball launch speed"
        elif "VERTICAL" in note:
            title = "Ball vertical speed"
        elif "HEIGHT" in note:
            title = "Ball height"
        r = ask_form(self.root, "Save to library", [
            ("name", "Name", "entry", title, None),
            ("category", "Category", "combo", self.plan["category"] if self.plan else "Other",
             self.categories())])
        if not r or not r["name"]:
            return
        self.library.append(core.new_value_entry(r["name"], r["category"] or "Other", addr, vt))
        self.library_changed()
        self._refresh_hit_sources()
        self.say(f"Saved {core.fa(addr)} as '{r['name']}'.")

    def coach_test(self):
        item = self._coach_selected()
        if not item or not self.need_attach():
            return
        vt, addr = item
        cur = self.ps2.read(addr, vt)
        r = ask_form(self.root, "Test value", [("value", f"Write a value to {core.fa(addr)} and watch "
                                                         "the game", "entry", cur, None)])
        if not r:
            return
        try:
            self.ps2.write(addr, vt, core.parse_number(r["value"], vt))
        except ValueError:
            messagebox.showerror(APP_TITLE, "Not a number.")

    def coach_to_boost(self):
        item = self._coach_selected()
        if not item:
            return
        vt, addr = item
        if vt != "float":
            messagebox.showinfo(APP_TITLE, "Power boost needs a float (speed) value.")
            return
        for cb in self.boost_axes:
            if not cb.get().strip():
                cb.set(f"{core.fa(addr)}")
                break
        else:
            self.boost_axes[0].set(f"{core.fa(addr)}")
        self.nb.select(self.boost_tab)

    def coach_to_recorder(self):
        item = self._coach_selected()
        if not item:
            return
        vt, addr = item
        self._add_watch(addr, vt, f"coach {core.fa(addr)}")
        self._refresh_watch_tree()
        self.say("Added to the Recorder watch list.")

    def _show_overlay(self):
        if self.overlay is None or not self.overlay.winfo_exists():
            self.overlay = Overlay(self)
        self.overlay.deiconify()
        self.overlay.lift()

    # ---------------- recorder tab -------------------------------------------
    def _build_recorder_tab(self):
        tab = ttk.Frame(self.nb, padding=8)
        self.nb.add(tab, text="Recorder (auto-pinpoint)")

        ttk.Label(tab, foreground="#335", wraplength=1000, justify="left", text=(
            "Put your last few candidates here, pick what you'll do in the game, record yourself doing it and "
            "tap ] each time you do it. The tool samples every value ~120 times a second and picks the one that "
            "follows what you did. Keys while in game:  [ = start/stop recording   ] = I did it")).pack(anchor="w")
        er = ttk.Frame(tab)
        er.pack(fill="x", pady=(4, 0))
        ttk.Label(er, text="What you'll do:", font=("Segoe UI", 10, "bold")).pack(side="left")
        self.rec_event = tk.StringVar()
        self.rec_event_box = ttk.Combobox(er, textvariable=self.rec_event, state="readonly", width=52)
        self.rec_event_box.pack(side="left", padx=6)
        self.rec_step_lbl = ttk.Label(er, text="", foreground="#1d4ed8", font=("Segoe UI", 10, "bold"))
        self.rec_step_lbl.pack(side="left", padx=8)
        self.rec_event.trace_add("write", lambda *a: self._rec_show_step())

        top = ttk.Frame(tab)
        top.pack(fill="x", pady=6)
        left = ttk.Frame(top)
        left.pack(side="left", fill="y")
        self.w_tree = ttk.Treeview(left, columns=("addr", "type"), show="tree headings", height=8)
        self.w_tree.heading("#0", text="Watching")
        self.w_tree.column("#0", width=160)
        self.w_tree.heading("addr", text="Address")
        self.w_tree.column("addr", width=90)
        self.w_tree.heading("type", text="Type")
        self.w_tree.column("type", width=60)
        self.w_tree.pack(side="left")
        wb = ttk.Frame(left)
        wb.pack(side="left", fill="y", padx=6)
        for text, cmd in (("+ Scanner results", self.watch_from_scanner),
                          ("+ Library value", self.watch_from_library),
                          ("+ Neighbours of selected", self.watch_neighbours),
                          ("Remove", self.watch_remove), ("Clear", self.watch_clear)):
            ttk.Button(wb, text=text, command=cmd).pack(fill="x", pady=1)

        ctl = ttk.Frame(top)
        ctl.pack(side="left", fill="y", padx=16)
        self.rec_btn = ttk.Button(ctl, text="Start recording  [", command=self.rec_toggle)
        self.rec_btn.pack(fill="x", pady=2)
        self.rec_mark_btn = ttk.Button(ctl, text="I did it  ]", command=self.rec_mark)
        self.rec_mark_btn.pack(fill="x", pady=2)
        self.rec_info = ttk.Label(ctl, text="Not recording", font=("Segoe UI", 10, "bold"))
        self.rec_info.pack(anchor="w", pady=6)
        ttk.Button(ctl, text="Analyze again", command=self.rec_analyze).pack(fill="x", pady=2)
        ttk.Button(ctl, text="Save selected to library...", command=self.rec_save).pack(fill="x", pady=2)
        ttk.Label(ctl, foreground="#666", wraplength=230, justify="left", text=(
            "Tip: do it 4-6 times in one recording, with a second or two of nothing in between. Stop "
            "recording and the verdict appears below.")).pack(anchor="w", pady=6)

        self.r_tree = ttk.Treeview(tab, columns=("addr", "verdict", "score"), show="headings", height=6)
        for col, text, w in (("addr", "Address", 110), ("verdict", "Verdict", 620), ("score", "Score", 70)):
            self.r_tree.heading(col, text=text)
            self.r_tree.column(col, width=w, anchor="w")
        self.r_tree.pack(fill="x")

        cf = ttk.Frame(tab)
        cf.pack(fill="both", expand=True, pady=(6, 0))
        self.plot = tk.Canvas(cf, background="white", highlightthickness=0)
        psb = ttk.Scrollbar(cf, command=self.plot.yview)
        self.plot.configure(yscrollcommand=psb.set)
        self.plot.pack(side="left", fill="both", expand=True)
        psb.pack(side="right", fill="y")

    # ---- what the player does while recording ----
    def _rec_recipe_key(self):
        return next((k for k, r in core.EVENT_RECIPES.items() if r["label"] == self.rec_event.get()), "ball")

    def _rec_step(self, n):
        steps = core.EVENT_RECIPES[self._rec_recipe_key()]["steps"]
        return steps[n % len(steps)]

    def _rec_show_step(self):
        n = len(self.rec_data["marks"]) if self.recording and self.rec_data else 0
        what, _ = self._rec_step(n)
        self.rec_step_lbl.configure(text=f"Next: {what}, then press ]")
        if self.recording and self.overlay is not None and self.overlay.winfo_exists():
            self.overlay.set(f"Recording. Next: {what} - then press ]",
                             f"{n} done so far. Press [ to stop when you've done it 4-6 times.", done=False,
                             close=True)

    # ---- watch list ----
    def _add_watch(self, addr, vtype, name):
        if any(w["addr"] == addr and w["type"] == vtype for w in self.watch):
            return
        if len(self.watch) >= 40:
            self.say("Watch list is full (40).")
            return
        self.watch.append({"addr": addr, "type": vtype, "name": name})

    def _refresh_watch_tree(self):
        self.w_tree.delete(*self.w_tree.get_children())
        for i, w in enumerate(self.watch):
            self.w_tree.insert("", "end", iid=str(i), text=w["name"], values=(f"{core.fa(w['addr'], w['type'])}", w["type"]))

    def watch_from_scanner(self):
        if not self.scanner.active or self.scanner.idx is None:
            messagebox.showinfo(APP_TITLE, "Narrow down with the Scanner first.")
            return
        sel = [self._sc_iid(i) for i in self.sc_tree.selection()]
        sel = [x for x in sel if x]
        rows = sel or [(a, vt) for a, vt, _, _ in self._scan_rows(40)]
        for a, vt in rows:
            self._add_watch(a, vt, f"cand {core.fa(a, vt)}")
        self._refresh_watch_tree()
        self.say(f"Watching {len(self.watch)} value(s).")

    def watch_from_library(self):
        vals = [e for e in self.library if e["kind"] == "value"]
        if not vals:
            messagebox.showinfo(APP_TITLE, "No single values in the library yet.")
            return
        r = ask_form(self.root, "Watch library value", [
            ("name", "Value", "combo", vals[0]["name"], [e["name"] for e in vals])])
        if not r:
            return
        e = next((e for e in vals if e["name"] == r["name"]), None)
        if e:
            self._add_watch(e["addr"], e["type"], e["name"])
            self._refresh_watch_tree()

    def watch_neighbours(self):
        sel = self.w_tree.selection()
        if not sel:
            messagebox.showinfo(APP_TITLE, "Select a watched value first (e.g. the ball height).")
            return
        w = self.watch[int(sel[0])]
        base = w["addr"] - (w["addr"] % 4)
        types = ("float",) if w["type"] == "float" else (w["type"], "float")
        for off in range(-0x18, 0x1C, 4):
            for vt in types:
                if off or vt != w["type"]:
                    self._add_watch(base + off, vt, f"{w['name']} {off:+#x} {vt}")
        self._refresh_watch_tree()
        self.say("Added the values around it - related values usually sit side by side.")

    def watch_remove(self):
        for iid in sorted((int(i) for i in self.w_tree.selection()), reverse=True):
            del self.watch[iid]
        self._refresh_watch_tree()

    def watch_clear(self):
        self.watch.clear()
        self._refresh_watch_tree()

    # ---- recording ----
    def rec_toggle(self):
        if self.recording:
            self.recording = False
            return
        if not self.need_attach():
            return
        if not self.watch:
            messagebox.showinfo(APP_TITLE, "Add some values to watch first.")
            return
        self.rec_data = {"t": [], "vals": [[] for _ in self.watch], "marks": [], "expect": [],
                         "watch": [dict(w) for w in self.watch], "recipe": self._rec_recipe_key()}
        self.recording = True
        self.rec_btn.configure(text="Stop recording  [")
        if self.rec_data["recipe"] != "ball":
            self._show_overlay()
        self._rec_show_step()
        threading.Thread(target=self._rec_thread, daemon=True).start()
        self._rec_tick()

    def _rec_thread(self):
        data = self.rec_data
        watch = data["watch"]
        start = time.perf_counter()
        period = 1 / 120
        nxt = start
        while self.recording and self.ps2.attached:
            now = time.perf_counter()
            data["t"].append(now - start)
            for i, w in enumerate(watch):
                v = self.ps2.read(w["addr"], w["type"])
                data["vals"][i].append(float("nan") if v is None else float(v))
            nxt += period
            delay = nxt - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            else:
                nxt = time.perf_counter()
            if now - start > 600:   # 10 minute safety limit
                self.recording = False
        self.recording = False

    def _rec_tick(self):
        d = self.rec_data
        if self.recording:
            secs = d["t"][-1] if d["t"] else 0
            self.rec_info.configure(text=f"REC {secs:5.1f}s   marked: {len(d['marks'])}")
            self.root.after(200, self._rec_tick)
        else:
            self.rec_btn.configure(text="Start recording  [")
            self.rec_info.configure(text=f"Recorded {d['t'][-1] if d['t'] else 0:.1f}s, "
                                         f"{len(d['marks'])} mark(s)")
            self.rec_step_lbl.configure(text="")
            self.rec_analyze()

    def rec_mark(self):
        if not self.recording or not self.rec_data["t"]:
            return
        d = self.rec_data
        _, exp = self._rec_step(len(d["marks"]))
        d["marks"].append(d["t"][-1])
        d.setdefault("expect", []).append(exp)
        self._rec_show_step()

    def rec_analyze(self):
        d = self.rec_data
        if not d or len(d["t"]) < 20:
            return
        if not d["marks"]:
            messagebox.showinfo(APP_TITLE, "Nothing was marked. Press ] (or 'I did it') each time you do "
                                           "the thing, then record again.")
        n = min(len(d["t"]), *(len(v) for v in d["vals"]))
        t = np.array(d["t"][:n])
        traces = {i: np.array(v[:n]) for i, v in enumerate(d["vals"])}
        ball = d.get("recipe", "ball") == "ball"
        if ball:
            self.rec_results = core.analyze_traces(t, traces, d["marks"])
        else:
            self.rec_results = core.analyze_events(t, traces, list(zip(d["marks"], d["expect"])))
        self.r_tree.delete(*self.r_tree.get_children())
        for rank, r in enumerate(self.rec_results):
            w = d["watch"][r["key"]]
            tag = "best" if rank == 0 and r["score"] >= 0.25 else ""
            self.r_tree.insert("", "end", iid=str(r["key"]), tags=(tag,),
                               values=(f"{core.fa(w['addr'], w['type'])}",
                                       f"{w['name']}: {self._kind_label(r['kind'])}  ({r.get('details', '')})",
                                       f"{r['score']:.2f}"))
        self.r_tree.tag_configure("best", background="#d8f5d0")
        self._draw_plots(t, traces, d["marks"])
        if self.rec_results and self.rec_results[0]["score"] >= 0.25:
            best = d["watch"][self.rec_results[0]["key"]]
            self.say(f"Best guess: {core.fa(best['addr'], best['type'])} - "
                     f"{self._kind_label(self.rec_results[0]['kind'])}")
            if not ball and self.overlay is not None and self.overlay.winfo_exists():
                self.overlay.set(f"Best guess: {best['name']} ({core.fa(best['addr'], best['type'])})",
                                 self._kind_label(self.rec_results[0]["kind"]), close=True)
        else:
            self.say("Nothing followed what you did. Add neighbours or new candidates and record again.")

    @staticmethod
    def _kind_label(kind):
        return core.KIND_LABELS.get(kind) or core.EVENT_LABELS.get(kind, kind)

    def _draw_plots(self, t, traces, marks):
        c = self.plot
        c.delete("all")
        c.update_idletasks()
        width = max(600, c.winfo_width() - 20)
        row_h, left = 80, 150
        order = [r["key"] for r in self.rec_results] or list(traces)
        dur = float(t[-1]) if len(t) else 1.0
        for row, key in enumerate(order):
            y0 = 10 + row * row_h
            w = self.rec_data["watch"][key]
            res = next((r for r in self.rec_results if r["key"] == key), None)
            c.create_text(8, y0 + 18, anchor="w", text=f"{core.fa(w['addr'])}", font=("Consolas", 10, "bold"))
            c.create_text(8, y0 + 36, anchor="w", fill="#555",
                          text=(res["kind"] if res else ""), font=("Segoe UI", 9))
            c.create_rectangle(left, y0, width, y0 + row_h - 12, outline="#ddd")
            y = traces[key]
            ok = np.isfinite(y)
            for m in marks:
                x = left + (m / dur) * (width - left)
                c.create_line(x, y0, x, y0 + row_h - 12, fill="#e33")
            if ok.sum() < 2:
                continue
            lo, hi = float(np.nanmin(y)), float(np.nanmax(y))
            span = (hi - lo) or 1.0
            step = max(1, len(y) // (width - left))
            pts = []
            for i in range(0, len(y), step):
                if ok[i]:
                    pts += [left + (t[i] / dur) * (width - left),
                            y0 + (row_h - 14) - (y[i] - lo) / span * (row_h - 16)]
            if len(pts) >= 4:
                c.create_line(*pts, fill="#2563eb" if row else "#16a34a", width=2 if row == 0 else 1)
            c.create_text(width - 4, y0 + 2, anchor="ne", fill="#888", font=("Segoe UI", 8),
                          text=f"{lo:.3g} .. {hi:.3g}")
        c.configure(scrollregion=(0, 0, width, 20 + len(order) * row_h))

    def rec_save(self):
        sel = self.r_tree.selection()
        if not sel:
            messagebox.showinfo(APP_TITLE, "Select a row in the verdict list.")
            return
        w = self.rec_data["watch"][int(sel[0])]
        kind = next((r["kind"] for r in self.rec_results if r["key"] == int(sel[0])), "")
        default = {"height": "Ball height", "vspeed": "Ball vertical speed",
                   "speed": "Ball launch speed"}.get(kind) or {
            "shoot": "Ammo", "damage": "Health", "die": "Lives", "money": "Money", "item": "Items",
            "jump": "Height", "run": "Speed", "drive": "Car speed", "lower": "Elevation", "score": "Score",
            "stamina": "Stamina", "switch": "ID", "timer": "Clock"}.get(self.rec_data.get("recipe"), w["name"])
        r = ask_form(self.root, "Save to library", [
            ("name", "Name", "entry", default, None),
            ("category", "Category", "combo", "Game State", self.categories())])
        if not r or not r["name"]:
            return
        self.library.append(core.new_value_entry(r["name"], r["category"] or "Other", w["addr"], w["type"]))
        self.library_changed()
        self.say(f"Saved {core.fa(w['addr'])} as '{r['name']}'.")

    # ---------------- power boost tab ------------------------------------------
    def _build_boost_tab(self):
        tab = ttk.Frame(self.nb, padding=10)
        self.boost_tab = tab
        self.nb.add(tab, text="Power boost")
        ttk.Label(tab, foreground="#335", wraplength=1000, justify="left", text=(
            "Multiplies the ball's velocity the instant the bat hits it, so every hit flies faster and "
            "farther. Pick the ball's velocity values (X / Y / Z, any you have - forward speed matters "
            "most). The boost fires when the ball suddenly reverses direction (contact), not on pitches "
            "or bounces. The tool must stay open while you play. Toggle in game with the \\ key.")
                  ).pack(anchor="w")

        form = ttk.Frame(tab)
        form.pack(anchor="w", pady=10)
        self.boost_axes = []
        for row, axis in enumerate(("Velocity 1 (forward)", "Velocity 2 (up)", "Velocity 3 (side)")):
            ttk.Label(form, text=axis).grid(row=row, column=0, sticky="w", pady=2)
            cb = ttk.Combobox(form, width=40)
            cb.grid(row=row, column=1, sticky="w", padx=6)
            self.boost_axes.append(cb)
        ttk.Label(form, text="(pick from the library or type a hex address, e.g. 00B76A20)",
                  foreground="#666").grid(row=3, column=1, sticky="w", padx=6)
        ttk.Label(form, text="Multiply by").grid(row=4, column=0, sticky="w", pady=(10, 2))
        self.boost_factor = tk.DoubleVar(value=3.0)
        ttk.Spinbox(form, from_=1.1, to=50, increment=0.5, textvariable=self.boost_factor,
                    width=8).grid(row=4, column=1, sticky="w", padx=6, pady=(10, 2))
        ttk.Label(form, text="Boost when").grid(row=5, column=0, sticky="w")
        self.boost_trigger = ttk.Combobox(form, state="readonly", width=48, values=BOOST_TRIGGERS)
        self.boost_trigger.set(BOOST_TRIGGERS[0])
        self.boost_trigger.grid(row=5, column=1, sticky="w", padx=6)
        ttk.Label(form, text="Cooldown (s)").grid(row=6, column=0, sticky="w")
        self.boost_cooldown = tk.DoubleVar(value=1.5)
        ttk.Spinbox(form, from_=0.2, to=10, increment=0.1, textvariable=self.boost_cooldown,
                    width=8).grid(row=6, column=1, sticky="w", padx=6)

        btns = ttk.Frame(tab)
        btns.pack(anchor="w", pady=6)
        self.boost_btn = ttk.Button(btns, text="Start boost  \\", command=self.boost_toggle)
        self.boost_btn.pack(side="left", padx=2)
        ttk.Button(btns, text="Boost now (test)", command=self.boost_now).pack(side="left", padx=2)
        ttk.Button(btns, text="Refresh value lists", command=self._boost_refresh_lists).pack(side="left", padx=2)
        self.boost_info = ttk.Label(tab, text="Off", font=("Segoe UI", 10, "bold"))
        self.boost_info.pack(anchor="w", pady=6)

        ttk.Label(tab, foreground="#444", wraplength=1000, justify="left", text=(
            "NOT SURE WHICH ADDRESS IS THE SPEED?  Hit a fly ball and pause the emulator while it's in the air. "
            "Put one candidate in 'Velocity 1', click 'Boost now (test)' with Multiply by = 3, then "
            "unpause. If the ball suddenly shoots off 3x faster in some direction, that's a velocity. "
            "If it teleports instead, that one is a position - the velocity is usually 0x0C or 0x10 "
            "bytes after it.")).pack(anchor="w", pady=(10, 0))
        self.nb.bind("<<NotebookTabChanged>>", lambda e: self._boost_refresh_lists(), add="+")

    def _boost_refresh_lists(self):
        names = [""] + [e["name"] for e in self.library if e["kind"] == "value"]
        for cb in self.boost_axes:
            cb.configure(values=names)

    def _boost_addrs(self):
        out = []
        for cb in self.boost_axes:
            text = cb.get().strip()
            if not text:
                continue
            e = next((e for e in self.library if e["kind"] == "value" and e["name"] == text), None)
            if e:
                out.append((e["addr"], e["type"]))
                continue
            try:
                a = core.pa(text, "float")
            except ValueError:
                raise ValueError(f"'{text}' is not a library value or an address in the game")
            if a % 4:
                raise ValueError(f"{core.fa(a)}: floats sit on addresses that are a multiple of 4")
            out.append((a, "float"))
        if not out:
            raise ValueError("Pick at least one velocity value.")
        return out

    def boost_now(self):
        if not self.need_attach():
            return
        try:
            addrs = self._boost_addrs()
            factor = float(self.boost_factor.get())
        except (ValueError, tk.TclError) as e:
            messagebox.showerror(APP_TITLE, str(e))
            return
        parts = []
        for a, vt in addrs:
            v = self.ps2.read(a, vt)
            if v is None:
                continue
            self.ps2.write(a, vt, v * factor)
            parts.append(f"{core.fa(a)}: {v:.3g} → {v * factor:.3g}")
        self.boost_info.configure(text="Test boost: " + "   ".join(parts))

    def boost_toggle(self):
        if self.boosting:
            self.boosting = False
            return
        if not self.need_attach():
            return
        try:
            addrs = self._boost_addrs()
            factor = float(self.boost_factor.get())
            cooldown = float(self.boost_cooldown.get())
        except (ValueError, tk.TclError) as e:
            messagebox.showerror(APP_TITLE, str(e))
            return
        self.booster = core.Booster(factor, cooldown=cooldown,
                                    trigger=BOOST_TRIGGER_KEYS[self.boost_trigger.get()])
        self.boost_addr_list = addrs
        self.boost_last = ""
        self.boosting = True
        self.boost_btn.configure(text="Stop boost  \\")
        threading.Thread(target=self._boost_thread, daemon=True).start()
        self._boost_tick()

    def _boost_thread(self):
        winmm = None
        if core.IS_WIN:
            try:
                import ctypes
                winmm = ctypes.windll.winmm
                winmm.timeBeginPeriod(1)   # 1 ms sleeps so we catch the hit within a frame
            except Exception:
                winmm = None
        start = time.perf_counter()
        try:
            while self.boosting and self.ps2.attached:
                vals = [self.ps2.read(a, vt) for a, vt in self.boost_addr_list]
                if None not in vals:
                    t = time.perf_counter() - start
                    new = self.booster.step(t, vals)
                    if new is not None:
                        for (a, vt), v in zip(self.boost_addr_list, new):
                            self.ps2.write(a, vt, v)
                        self.boost_last = ", ".join(f"{o:.3g}→{n:.3g}" for o, n in zip(vals, new))
                        time.sleep(0.05)
                        a0, vt0 = self.boost_addr_list[0]
                        now = self.ps2.read(a0, vt0)
                        if now is not None and abs(now - new[0]) > abs(now - vals[0]):
                            self.boost_warn = (f"The game overwrote the boost on {core.fa(a0)} - it's a copy. "
                                               "Run the AI Coach ball hunt: it tests and finds the real one.")
                        else:
                            self.boost_warn = ""
                time.sleep(0.001)
        finally:
            self.boosting = False
            if winmm:
                winmm.timeEndPeriod(1)

    def _boost_tick(self):
        if self.boosting:
            last = f"   last: {self.boost_last}" if self.boost_last else ""
            warn = f"\nWARNING: {self.boost_warn}" if self.boost_warn else ""
            self.boost_info.configure(text=f"BOOST ON  x{self.booster.factor:g}   hits boosted: "
                                           f"{self.booster.count}{last}{warn}",
                                      foreground="#b45309" if warn else "#070")
            self.root.after(150, self._boost_tick)
        else:
            self.boost_btn.configure(text="Start boost  \\")
            n = self.booster.count if self.booster else 0
            self.boost_info.configure(text=f"Off  ({n} hits boosted)", foreground="#000")

    # ---------------- ratings tab ------------------------------------------
    def _build_ratings_tab(self):
        tab = ttk.Frame(self.nb, padding=8)
        self.ratings_tab = tab
        self.nb.add(tab, text="Ratings finder")

        step1 = ttk.LabelFrame(tab, text="Step 1 - Pin a player (Edit Player screen, exact method)",
                               padding=8)
        step1.pack(fill="x")
        r = ttk.Frame(step1)
        r.pack(fill="x")
        ttk.Label(r, text="Rating name").pack(side="left")
        self.ed_label = ttk.Entry(r, width=6)
        self.ed_label.insert(0, "SPD")
        self.ed_label.pack(side="left", padx=4)
        ttk.Label(r, text="Value now").pack(side="left", padx=(10, 0))
        self.ed_old = ttk.Entry(r, width=6)
        self.ed_old.pack(side="left", padx=4)
        ttk.Button(r, text="1. Snapshot before", command=self.edit_snapshot).pack(side="left", padx=6)
        ttk.Label(r, text="→ change it in-game →  New value").pack(side="left", padx=(6, 0))
        self.ed_new = ttk.Entry(r, width=6)
        self.ed_new.pack(side="left", padx=4)
        ttk.Button(r, text="2. Find it", command=self.edit_find).pack(side="left", padx=6)

        r2 = ttk.Frame(step1)
        r2.pack(fill="x", pady=(6, 0))
        self.ed_hits = tk.Listbox(r2, height=4, width=40, exportselection=False)
        self.ed_hits.pack(side="left")
        b = ttk.Frame(r2)
        b.pack(side="left", padx=8)
        ttk.Button(b, text="Use as Player 1", command=lambda: self.set_anchor(1)).pack(fill="x", pady=1)
        ttk.Button(b, text="Use as Player 2", command=lambda: self.set_anchor(2)).pack(fill="x", pady=1)
        self.anchor_label = ttk.Label(r2, text="Player 1: -\nPlayer 2: -", justify="left")
        self.anchor_label.pack(side="left", padx=12)

        step2 = ttk.LabelFrame(tab, text="Step 2 - Enter each player's ratings as they are NOW "
                                         "(one per line, e.g. SPD=93)", padding=8)
        step2.pack(fill="x", pady=8)
        self.p1_text = tk.Text(step2, width=28, height=7)
        self.p2_text = tk.Text(step2, width=28, height=7)
        ttk.Label(step2, text="Player 1").grid(row=0, column=0, sticky="w")
        ttk.Label(step2, text="Player 2 (different player)").grid(row=0, column=1, sticky="w", padx=8)
        self.p1_text.grid(row=1, column=0, sticky="nsew")
        self.p2_text.grid(row=1, column=1, sticky="nsew", padx=8)
        self.p1_text.insert("1.0", "SPD=\nACC=\nSTR=\nAGI=\nKPW=\nKAC=\nAWR=")
        self.p2_text.insert("1.0", "SPD=\nACC=\nSTR=\nAGI=\nKPW=\nKAC=\nAWR=")
        bb = ttk.Frame(step2)
        bb.grid(row=1, column=2, sticky="n", padx=8)
        ttk.Label(bb, text="Search window (bytes)").pack(anchor="w")
        self.window = tk.IntVar(value=256)
        ttk.Spinbox(bb, from_=32, to=4096, increment=32, textvariable=self.window, width=8).pack(anchor="w")
        ttk.Button(bb, text="Find roster table\n(uses Step 1 pins)",
                   command=self.find_table_exact).pack(fill="x", pady=(10, 2))
        ttk.Button(bb, text="Quick auto search\n(no edits, may fail)",
                   command=self.find_table_auto).pack(fill="x", pady=2)
        ttk.Button(bb, text="Save table to library...", command=self.save_found_table).pack(
            fill="x", pady=(10, 2))

        self.rt_out = tk.Text(tab, height=12, wrap="word", state="disabled", background="#f7f7f7")
        self.rt_out.pack(fill="both", expand=True)

    # ---------------- library tab -------------------------------------------
    def _build_library_tab(self):
        tab = ttk.Frame(self.nb, padding=8)
        self.lib_tab = tab
        self.nb.add(tab, text="Library (live)")

        bar = ttk.Frame(tab)
        bar.pack(fill="x")
        for text, cmd in (("Edit value...", self.lib_edit_value), ("Freeze / unfreeze", self.lib_toggle_freeze),
                          ("Set field for ALL players...", self.lib_set_all),
                          ("Rename / category...", self.lib_rename), ("Delete", self.lib_delete),
                          ("Add address...", self.lib_add_manual),
                          ("Moves around: track it", self.lib_toggle_moving),
                          ("Re-find moved values", lambda: self.relocate_all(report=True))):
            ttk.Button(bar, text=text, command=cmd).pack(side="left", padx=2)
        ttk.Label(bar, text="   Show player #").pack(side="left")
        ttk.Spinbox(bar, from_=0, to=9999, textvariable=self.show_record, width=6,
                    command=self.rebuild_library_tree).pack(side="left")

        bar2 = ttk.Frame(tab)
        bar2.pack(fill="x", pady=4)
        ttk.Button(bar2, text="Save list", command=lambda: self.save_library(self.lib_path)).pack(side="left", padx=2)
        ttk.Button(bar2, text="Save list as...", command=self.save_library_as).pack(side="left", padx=2)
        ttk.Button(bar2, text="Load...", command=self.load_library_dialog).pack(side="left", padx=2)
        ttk.Button(bar2, text="Find copies of this player", command=self.lib_find_copies).pack(
            side="left", padx=(16, 2))
        ttk.Button(bar2, text="Unlink copies", command=self.lib_clear_copies).pack(side="left", padx=2)
        ttk.Label(bar2, text="(saves your labels only)", foreground="#666").pack(side="left", padx=10)

        frame = ttk.Frame(tab)
        frame.pack(fill="both", expand=True)
        self.lib_tree = ttk.Treeview(frame, columns=("addr", "type", "value", "frozen", "moves"), show="tree headings")
        self.lib_tree.heading("#0", text="Name")
        self.lib_tree.column("#0", width=280)
        for col, text, w in (("addr", "Address", 120), ("type", "Type", 70),
                             ("value", "Live value", 200), ("frozen", "Frozen", 120), ("moves", "Moves around?", 190)):
            self.lib_tree.heading(col, text=text)
            self.lib_tree.column(col, width=w, anchor="w")
        sb = ttk.Scrollbar(frame, command=self.lib_tree.yview)
        self.lib_tree.configure(yscrollcommand=sb.set)
        self.lib_tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.lib_tree.bind("<Double-1>", lambda e: self.lib_edit_value())

    # ---------------- cheat / mod menu tab -----------------------------------------
    def _build_cheat_tab(self):
        tab = ttk.Frame(self.nb, padding=8)
        self.cheat_tab = tab
        self.nb.add(tab, text="Cheats & mod menu")

        d = ttk.Frame(tab)
        d.pack(fill="x")
        ttk.Label(d, text="Describe a cheat:", font=("Segoe UI", 10, "bold")).pack(side="left")
        self.describe_var = tk.StringVar()
        de = ttk.Entry(d, textvariable=self.describe_var, font=("Segoe UI", 11), width=50)
        de.pack(side="left", padx=4, fill="x", expand=True)
        de.bind("<Return>", lambda e: self.describe_add())
        ttk.Button(d, text="Add", command=self.describe_add).pack(side="left")
        ttk.Label(tab, foreground="#666", text='e.g.  "infinite ammo on L1+R1"   "money +10000 on L2+R2"   '
                  '"double car speed on F3"   "health 999"   "set wanted level to 0 with R3"').pack(anchor="w")

        top = ttk.Frame(tab)
        top.pack(fill="x", pady=(6, 0))
        ttk.Label(top, text="Game").pack(side="left")
        ttk.Entry(top, textvariable=self.game_title, width=34).pack(side="left", padx=4)
        for text, cmd in (("Add cheat...", self.add_cheat), ("Set hotkey...", self.set_cheat_hotkey),
                          ("Remove", self.remove_cheat), ("Add code patch...", self.add_code_patch),
                          ("Preview codes", self.preview_pnach), ("Export cheats...", self.export_pnach)):
            ttk.Button(top, text=text, command=cmd).pack(side="left", padx=3)

        self.ch_tree = ttk.Treeview(tab, columns=("does", "hotkey", "group", "act"), show="tree headings", height=9)
        self.ch_tree.heading("#0", text="Cheat")
        self.ch_tree.column("#0", width=230)
        for col, text, w in (("does", "What it does", 330), ("hotkey", "Hotkey", 130),
                             ("group", "Menu group", 140), ("act", "Code activator (exports)", 170)):
            self.ch_tree.heading(col, text=text)
            self.ch_tree.column(col, width=w, anchor="w")
        self.ch_tree.pack(fill="x", pady=(6, 0))
        self.ch_tree.bind("<Double-1>", lambda e: self.set_cheat_hotkey())

        mf = ttk.LabelFrame(tab, text="In-game mod menu (runs while this tool is open - works on every system)",
                            padding=8)
        mf.pack(fill="x", pady=8)
        r1 = ttk.Frame(mf)
        r1.pack(fill="x")
        self.menu_btn = ttk.Button(r1, text="Start mod menu", command=self.menu_toggle)
        self.menu_btn.pack(side="left")
        ttk.Label(r1, text="   Open menu with:").pack(side="left")
        self.menu_open_lbl = ttk.Label(r1, text="", font=("Segoe UI", 10, "bold"))
        self.menu_open_lbl.pack(side="left", padx=4)
        ttk.Button(r1, text="Change...", command=self.set_menu_combo).pack(side="left")
        ttk.Label(r1, text="   Controller:").pack(side="left")
        self.pad_src = tk.StringVar(value=self.settings.get("pad_src", PAD_SOURCES[0]))
        ttk.Combobox(r1, textvariable=self.pad_src, values=PAD_SOURCES, state="readonly", width=40).pack(
            side="left", padx=4)
        ttk.Button(r1, text="Learn game pad...", command=self.learn_mem_pad).pack(side="left")
        self.pad_lbl = ttk.Label(mf, text="", foreground="#335")
        self.pad_lbl.pack(anchor="w", pady=(6, 0))
        ttk.Label(mf, foreground="#666", wraplength=1000, justify="left", text=(
            "In the menu: D-pad up/down to move, Cross (A) to switch a cheat on/off or spawn, Circle (B) to go back "
            "/ close. Keyboard works too: Insert opens it, Numpad 8/2 move, Numpad 5 selects, Numpad 0 goes back. "
            "Hotkeys work any time, menu open or not. 'keep it at' cheats stay on until you switch them off.")).pack(
            anchor="w")
        self._update_menu_labels()

        self.pnach_text = tk.Text(tab, height=8, wrap="none", font=("Consolas", 9))
        self.pnach_text.pack(fill="both", expand=True)

    # ---------------- spawn tab -------------------------------------------------------
    def _build_spawn_tab(self):
        tab = ttk.Frame(self.nb, padding=8)
        self.spawn_tab = tab
        self.nb.add(tab, text="Spawn menu")
        ttk.Label(tab, foreground="#335", wraplength=1050, justify="left", text=(
            "Games keep the ID of the car you're in, the weapon in your hand, the item in a slot. Find that ID "
            "value once, and writing another ID into it swaps in a different car / weapon / item. Names come "
            "from the game's own files (scan the game folder or disc image), or you name them as you go with "
            "the ID browser.")).pack(anchor="w")

        r1 = ttk.LabelFrame(tab, text="1. The ID value", padding=6)
        r1.pack(fill="x", pady=4)
        ttk.Label(r1, text="Spawn:").pack(side="left")
        self.spawn_kind = tk.StringVar(value="Vehicles")
        ttk.Combobox(r1, textvariable=self.spawn_kind, values=list(spawner.KIND_WORDS), width=12,
                     state="readonly").pack(side="left", padx=4)
        ttk.Label(r1, text="  ID value:").pack(side="left")
        self.spawn_id = ttk.Combobox(r1, width=30, state="readonly", postcommand=self._spawn_id_choices)
        self.spawn_id.pack(side="left", padx=4)
        ttk.Button(r1, text="Find it with the AI Coach", command=self.spawn_find_id).pack(side="left", padx=4)
        self.spawn_now_lbl = ttk.Label(r1, text="", font=("Segoe UI", 10, "bold"))
        self.spawn_now_lbl.pack(side="left", padx=10)

        r2 = ttk.LabelFrame(tab, text="2. Name lists (from the game's files)", padding=6)
        r2.pack(fill="x", pady=4)
        rb = ttk.Frame(r2)
        rb.pack(fill="x")
        ttk.Button(rb, text="Scan game folder...", command=lambda: self.spawn_scan(True)).pack(side="left")
        ttk.Button(rb, text="Scan disc image / file...", command=lambda: self.spawn_scan(False)).pack(side="left", padx=4)
        ttk.Button(rb, text="Stop", command=lambda: setattr(self, "scan_stop", True)).pack(side="left")
        ttk.Button(rb, text="Use this list", command=self.spawn_use_table).pack(side="left", padx=12)
        self.scan_lbl = ttk.Label(rb, text="", foreground="#335")
        self.scan_lbl.pack(side="left", padx=8)
        self.tables_tree = ttk.Treeview(r2, columns=("kind", "n", "seen", "first", "src"), show="headings", height=5)
        for col, text, w in (("kind", "Looks like", 90), ("n", "Names", 60), ("seen", "IDs you've used", 110),
                             ("first", "First few", 380), ("src", "Found in", 330)):
            self.tables_tree.heading(col, text=text)
            self.tables_tree.column(col, width=w, anchor="w")
        self.tables_tree.pack(fill="x", pady=(4, 0))

        r3 = ttk.LabelFrame(tab, text="3. Spawn list", padding=6)
        r3.pack(fill="both", expand=True, pady=4)
        bb = ttk.Frame(r3)
        bb.pack(fill="x")
        ttk.Button(bb, text="Spawn selected now", command=self.spawn_selected).pack(side="left")
        ttk.Label(bb, text=" keep it for").pack(side="left")
        self.spawn_hold = tk.DoubleVar(value=float(self.settings.get("spawn_hold", 1.5)))
        ttk.Spinbox(bb, from_=0, to=30, increment=0.5, textvariable=self.spawn_hold, width=5).pack(side="left")
        ttk.Label(bb, text="s").pack(side="left")
        ttk.Button(bb, text="Add selected to mod menu", command=lambda: self.spawn_to_menu(False)).pack(side="left", padx=(12, 2))
        ttk.Button(bb, text="Add whole list to menu", command=lambda: self.spawn_to_menu(True)).pack(side="left", padx=2)
        ttk.Label(bb, text="   ID browser:").pack(side="left")
        ttk.Button(bb, text="< Prev ID", command=lambda: self.spawn_step(-1)).pack(side="left", padx=2)
        ttk.Button(bb, text="Next ID >", command=lambda: self.spawn_step(1)).pack(side="left", padx=2)
        ttk.Button(bb, text="Name this ID...", command=self.spawn_name_id).pack(side="left", padx=2)
        self.spawn_tree = ttk.Treeview(r3, columns=("id", "name", "src"), show="headings", height=8)
        for col, text, w in (("id", "ID", 80), ("name", "Name", 300), ("src", "From", 400)):
            self.spawn_tree.heading(col, text=text)
            self.spawn_tree.column(col, width=w, anchor="w")
        sb = ttk.Scrollbar(r3, command=self.spawn_tree.yview)
        self.spawn_tree.configure(yscrollcommand=sb.set)
        self.spawn_tree.pack(side="left", fill="both", expand=True, pady=(4, 0))
        sb.pack(side="left", fill="y")
        self.spawn_tree.bind("<Double-1>", lambda e: self.spawn_selected())
        self.spawn_kind.trace_add("write", lambda *a: self.refresh_spawn_list())
        self.scan_tables = []

    # ---------------- help tab ------------------------------------------------
    def _build_help_tab(self):
        tab = ttk.Frame(self.nb, padding=8)
        self.nb.add(tab, text="How to use")
        txt = tk.Text(tab, wrap="word", font=("Segoe UI", 10))
        txt.pack(fill="both", expand=True)
        txt.insert("1.0", HELP_TEXT)
        txt.configure(state="disabled")

    # ======================= helpers =========================================
    def need_attach(self):
        if not self.ps2.attached:
            messagebox.showwarning(APP_TITLE, "Pick your game or emulator at the top and click Attach first.")
            return False
        return True

    def say(self, msg):
        self.status.set(msg)
        self.root.update_idletasks()

    def rt_print(self, text, clear=False):
        self.rt_out.configure(state="normal")
        if clear:
            self.rt_out.delete("1.0", "end")
        self.rt_out.insert("end", text + "\n")
        self.rt_out.see("end")
        self.rt_out.configure(state="disabled")

    def snap(self):
        return self.ps2.snapshot()

    # ======================= attach ===========================================
    def refresh_processes(self):
        try:
            self.procs = core.list_processes()
        except Exception:
            self.procs = []
        labels = []
        for pid, exe, title in self.procs:
            kind = core.profile_for_exe(exe)
            tag = "" if kind == "pc" else f"[{core.PROFILES[kind]['label'].split(' (')[0]}] "
            labels.append(f"{tag}{title[:40]}  -  {exe}  ({pid})")
        self.proc_box.configure(values=labels)
        if self.procs and not self.proc_var.get():
            self.proc_var.set(labels[0])
            self._proc_picked()

    def _picked_pid(self):
        txt = self.proc_var.get()
        if not txt.endswith(")"):
            return None
        try:
            return int(txt.rsplit("(", 1)[1][:-1])
        except ValueError:
            return None

    def _proc_picked(self, *_):
        pid = self._picked_pid()
        exe = next((e for p, e, _ in self.procs if p == pid), "")
        self.sys_var.set(core.PROFILES[core.profile_for_exe(exe)]["label"] if exe else
                         core.PROFILES["auto"]["label"])

    def attach(self):
        manual = None
        if self.base_override.get().strip():
            try:
                manual = int(self.base_override.get().strip(), 16)
            except ValueError:
                messagebox.showerror(APP_TITLE, "Base must be hex, e.g. 7FF6A0000000")
                return
        prof = next((k for k, p in core.PROFILES.items() if p["label"] == self.sys_var.get()), "auto")
        try:
            self.ps2.attach(manual, pid=self._picked_pid(), profile=prof)
        except Exception as e:
            self.conn_label.configure(text="Not attached", foreground="#b00")
            messagebox.showerror(APP_TITLE, str(e))
            return
        self.conn_label.configure(text="Attached: " + self.ps2.describe(), foreground="#070")
        moved = 0
        for e in self.library:                    # saved addresses -> this session's memory layout
            if e.get("kind") == "value" and e.get("where"):
                try:
                    a = core.pa(e["where"], e.get("type"))
                    moved += a != e["addr"]
                    e["addr"] = a
                except ValueError:
                    pass
        if moved:
            self.save_library(self.lib_path, quiet=True)
        self.game = None
        self.apply_game(self.detect_game())
        self.relocate_all()
        self.preview_pnach()
        self.rebuild_library_tree()

    # ======================= scanner ===========================================
    def _scan_value(self, vtype):
        return core.parse_number(self.sc_value.get(), "float" if vtype in (ANY_TYPE, "all") else vtype)

    def _sc_iid(self, iid):
        """tree row id -> (addr, type) or None"""
        if ":" in iid:
            vt, a = iid.split(":", 1)
            return (int(a), vt) if a.isdigit() and vt in core.TYPES else None
        return (int(iid), self.scanner.vtype) if iid.isdigit() and self.scanner.vtype in core.TYPES else None

    def _scan_rows(self, limit):
        """[(addr, type, current, previous)] for single- or any-type scans."""
        snap = self.snap()
        if isinstance(self.scanner, core.MultiScanner):
            return self.scanner.results_typed(snap, limit)
        return [(a, self.scanner.vtype, c, p) for a, c, p in self.scanner.results(snap, limit)]

    def first_scan(self, mode=None):
        if not self.need_attach():
            return
        vtype = self.sc_type.get()
        mode = mode or self.sc_first_mode.get()
        try:
            value = None if mode == "unknown" else self._scan_value(vtype)
        except ValueError:
            messagebox.showerror(APP_TITLE, "Enter a number to scan for (or pick 'unknown').")
            return
        self.say("Scanning...")
        if vtype == ANY_TYPE:
            if not isinstance(self.scanner, core.MultiScanner):
                self.scanner = core.MultiScanner()
        elif isinstance(self.scanner, core.MultiScanner):
            self.scanner = core.Scanner()
        n = self.scanner.first(self.snap(), vtype, mode, value)
        self.after_scan(f"First scan ({mode}): {n:,} results")

    def next_scan(self, mode=None):
        if not self.need_attach():
            return
        if not self.scanner.active:
            messagebox.showinfo(APP_TITLE, "Do a First scan first.")
            return
        mode = mode or self.sc_next_mode.get()
        value = None
        if mode in core.VALUE_MODES:
            try:
                value = self._scan_value(self.scanner.vtype)
            except ValueError:
                messagebox.showerror(APP_TITLE, "Enter a number for this scan type.")
                return
        self.say("Scanning...")
        n = self.scanner.next(self.snap(), mode, value)
        self.after_scan(f"Scan #{self.scanner.scans} ({mode}): {n:,} results left")

    def after_scan(self, msg):
        self.sc_count.configure(text=msg)
        self.say(msg)
        self.show_scan_results()

    def reset_scan(self):
        self.scanner.reset()
        self.sc_tree.delete(*self.sc_tree.get_children())
        self.sc_count.configure(text="No scan yet")

    def show_scan_results(self):
        self.sc_tree.delete(*self.sc_tree.get_children())
        if not self.scanner.active or not self.ps2.attached:
            return
        if self.scanner.idx is None:
            self.sc_tree.insert("", "end", values=("(all memory)", "Do a next scan to narrow down", ""))
            return
        multi = isinstance(self.scanner, core.MultiScanner)
        for addr, vt, cur, prev in self._scan_rows(500):
            fz = self.sc_frozen.get((addr, vt))
            self.sc_tree.insert("", "end", iid=f"{vt}:{addr}" if multi else f"{addr}",
                                values=(f"{core.fa(addr, vt)}" + (f"  ({vt})" if multi else ""),
                                        core.fmt_value(vt, cur), core.fmt_value(vt, prev),
                                        "" if fz is None else f"FROZEN = {core.fmt_value(vt, fz).split('  ')[0]}"))
        if self.scanner.count > 500:
            extra = ("  - " + ", ".join(f"{vt}: {n:,}" for vt, n in self.scanner.counts().items())) if multi else ""
            self.sc_tree.insert("", "end", values=("...", f"showing 500 of {self.scanner.count:,}{extra}", ""))

    def _sc_selected(self):
        sel = [x for x in (self._sc_iid(i) for i in self.sc_tree.selection()) if x]
        if not sel:
            messagebox.showinfo(APP_TITLE, "Select one or more results first (Ctrl/Shift-click for several).")
        return sel

    def _sc_refresh_rows(self, sel):
        for a, vt in sel:
            for iid in (f"{vt}:{a}", f"{a}"):
                if self.sc_tree.exists(iid):
                    fz = self.sc_frozen.get((a, vt))
                    self.sc_tree.set(iid, "frozen", "" if fz is None else
                                     f"FROZEN = {core.fmt_value(vt, fz).split('  ')[0]}")

    def scan_toggle_freeze(self):
        sel = self._sc_selected()
        if not sel or not self.need_attach():
            return
        turn_on = any((a, vt) not in self.sc_frozen for a, vt in sel)
        for a, vt in sel:
            if turn_on:
                v = self.ps2.read(a, vt)
                if v is not None:
                    self.sc_frozen[(a, vt)] = v
            else:
                self.sc_frozen.pop((a, vt), None)
        self._sc_refresh_rows(sel)
        self.say(f"{'Froze' if turn_on else 'Unfroze'} {len(sel)} value(s)." +
                 (" Play a bit: if the number on screen stops changing, one of these is it." if turn_on else ""))

    def scan_set_value(self):
        sel = self._sc_selected()
        if not sel or not self.need_attach():
            return
        a0, vt0 = sel[0]
        cur = self.ps2.read(a0, vt0)
        r = ask_form(self.root, "Set value", [
            ("value", f"New value for {len(sel)} selected (now {core.fmt_value(vt0, cur) if cur is not None else '?'})",
             "entry", "", None)])
        if not r or not r.get("value"):
            return
        for a, vt in sel:
            try:
                v = core.parse_number(r["value"], vt)
            except ValueError:
                messagebox.showerror(APP_TITLE, "That's not a number.")
                return
            self.ps2.write(a, vt, v)
            if (a, vt) in self.sc_frozen:
                self.sc_frozen[(a, vt)] = v
        self._sc_refresh_rows(sel)
        self.show_scan_results()

    def scan_unfreeze_all(self):
        n = len(self.sc_frozen)
        self.sc_frozen.clear()
        self.show_scan_results()
        self.say(f"Unfroze {n} value(s).")

    def scan_quick_add(self):
        """Straight into the library as 'Unnamed 3 (float)' - rename it once you know what it is."""
        sel = self._sc_selected()
        if not sel:
            return
        have = {e["name"] for e in self.library}
        n, added = 1, []
        for a, vt in sel:
            if any(e.get("kind") == "value" and e["addr"] == a and e["type"] == vt for e in self.library):
                continue
            while f"Unnamed {n} ({vt})" in have:
                n += 1
            name = f"Unnamed {n} ({vt})"
            have.add(name)
            e = core.new_value_entry(name, "Unsorted", a, vt)
            if (a, vt) in self.sc_frozen:
                e["freeze"], e["freeze_value"] = True, self.sc_frozen.pop((a, vt))
            self.library.append(e)
            added.append(name)
        self.library_changed()
        self.say(f"Added {len(added)} to the library under 'Unsorted'. Rename them (Library -> Rename) once you "
                 "know which is the right one." if added else "Those are already in the library.")

    def add_scan_to_library(self):
        sel = [x for x in (self._sc_iid(i) for i in self.sc_tree.selection()) if x]
        if not sel:
            messagebox.showinfo(APP_TITLE, "Select one or more results first.")
            return
        r = ask_form(self.root, "Add to library", [
            ("name", "Name", "entry", "Kick power", None),
            ("category", "Category", "combo", "Kicking", self.categories()),
        ])
        if not r or not r["name"]:
            return
        for n, (addr, vt) in enumerate(sel):
            name = r["name"] if len(sel) == 1 else f"{r['name']} #{n + 1}"
            self.library.append(core.new_value_entry(name, r["category"] or "Other", addr, vt))
        self.library_changed()
        self.say(f"Added {len(sel)} value(s) to the library.")

    # ======================= ratings finder =====================================
    def edit_snapshot(self):
        if not self.need_attach():
            return
        try:
            int(self.ed_old.get(), 0)
        except ValueError:
            messagebox.showerror(APP_TITLE, "Type the rating's current value first.")
            return
        self.edit_before = self.snap()
        self.say("Snapshot taken. Now change that rating in the game's Edit Player screen, "
                 "type the new value, and click 'Find it'.")

    def edit_find(self):
        if not self.need_attach():
            return
        if self.edit_before is None:
            messagebox.showinfo(APP_TITLE, "Click '1. Snapshot before' first.")
            return
        try:
            old, new = int(self.ed_old.get(), 0), int(self.ed_new.get(), 0)
        except ValueError:
            messagebox.showerror(APP_TITLE, "Enter both the old and the new value.")
            return
        after = self.snap()
        hits = core.find_changed_bytes(self.edit_before, after, old, new)
        self.ed_hits.delete(0, "end")
        for a in hits[:200]:
            self.ed_hits.insert("end", f"{core.fa(a, 'byte')}")
        if len(hits) == 1:
            self.ed_hits.selection_set(0)
            msg = "Found exactly one match. Click 'Use as Player 1' (or 2)."
        elif not hits:
            msg = ("No match. The game may not have saved the change yet (leave the edit screen "
                   "or confirm the edit), or ratings are stored differently. Try the Scanner tab.")
        else:
            msg = (f"{len(hits)} matches. Change the rating again (old = {new}), "
                   "snapshot, and find again to narrow it down.")
        # make the next round easy
        self.ed_old.delete(0, "end")
        self.ed_old.insert(0, str(new))
        self.ed_new.delete(0, "end")
        self.edit_before = after
        self.say(msg)

    def set_anchor(self, which):
        sel = self.ed_hits.curselection()
        if not sel:
            messagebox.showinfo(APP_TITLE, "Pick an address from the list.")
            return
        addr = core.pa(self.ed_hits.get(sel[0]), "byte")
        label = self.ed_label.get().strip().upper() or "ANCHOR"
        if which == 1:
            self.p1_anchor = (addr, label)
        else:
            self.p2_anchor = (addr, label)
        fmt = lambda a: f"{a[1]} @ {core.fa(a[0])}" if a else "-"
        self.anchor_label.configure(text=f"Player 1: {fmt(self.p1_anchor)}\nPlayer 2: {fmt(self.p2_anchor)}")

    def _fields(self, widget, who):
        lines = [l for l in widget.get("1.0", "end").splitlines() if l.strip() and not l.strip().endswith("=")]
        return core.parse_fields("\n".join(lines))

    def find_table_exact(self):
        if not self.need_attach():
            return
        if not self.p1_anchor or not self.p2_anchor:
            messagebox.showinfo(APP_TITLE, "Pin Player 1 and Player 2 in Step 1 first "
                                           "(same rating, two different players).")
            return
        if self.p1_anchor[1] != self.p2_anchor[1]:
            messagebox.showwarning(APP_TITLE, "Pin the SAME rating (e.g. SPD) for both players.")
            return
        try:
            f1 = self._fields(self.p1_text, "Player 1")
            f2 = self._fields(self.p2_text, "Player 2")
        except ValueError as e:
            messagebox.showerror(APP_TITLE, str(e))
            return
        label = self.p1_anchor[1]
        a1, a2 = self.p1_anchor[0], self.p2_anchor[0]
        mem = self.snap()
        f1 = [(l, v) for l, v in f1 if l != label]
        f2 = [(l, v) for l, v in f2 if l != label]
        opts = core.locate_fields(mem, a1, f1, self.window.get())
        opts[label] = [0]
        res = core.resolve_with_second(mem, a2, f2, opts)
        self.rt_print("Field offsets from the pinned rating:", clear=True)
        offsets, problems = {}, []
        for l, offs in res.items():
            if not offs:
                problems.append(l)
                self.rt_print(f"  {l}: not found near the pinned rating")
            else:
                offsets[l] = offs[0]
                extra = f"   (other possibilities: {offs[1:4]})" if len(offs) > 1 else ""
                self.rt_print(f"  {l}: {offs[0]:+d}{extra}")
        if problems:
            self.rt_print("Check those values match the game screen exactly, or raise the search window.")
        if len(offsets) < 2:
            return
        self._finish_table(mem, a1, a2, offsets)

    def find_table_auto(self):
        if not self.need_attach():
            return
        try:
            f1 = self._fields(self.p1_text, "Player 1")
            f2 = self._fields(self.p2_text, "Player 2")
        except ValueError as e:
            messagebox.showerror(APP_TITLE, str(e))
            return
        self.say("Searching all 32 MB for both players... (can take a few seconds)")
        self.root.config(cursor="watch")
        self.root.update()
        try:
            res = core.auto_match(self.snap(), f1, f2, self.window.get())
        except ValueError as e:
            messagebox.showerror(APP_TITLE, str(e))
            return
        finally:
            self.root.config(cursor="")
        if not res or not res[0].get("table"):
            self.rt_print("Auto search found no believable roster table. Use Step 1 (edit method).",
                          clear=True)
            self.say("Auto search found nothing.")
            return
        best = res[0]
        self.rt_print(f"Best match (anchored on {best['anchor_label']}):", clear=True)
        for l, o in best["offsets"].items():
            self.rt_print(f"  {l}: {o:+d}")
        self._finish_table(self.snap(), best["anchor_a"], best["anchor_b"], best["offsets"])

    def _finish_table(self, mem, a1, a2, offsets):
        t = core.detect_table(mem, a1, a2, offsets)
        if not t:
            self.rt_print("\nCould not work out the record size. Pin two players that are on the "
                          "same team / roster screen and try again.")
            self.found = None
            return
        self.found = {"offsets": offsets, **t}
        self.rt_print(f"\nRoster table: {t['count']} players, each record is {t['stride']} bytes "
                      f"(0x{t['stride']:X}). First player's pinned rating at {core.fa(t['first_anchor'])}.")
        names = list(offsets)
        self.rt_print("\nFirst 5 players:  " + "  ".join(f"{n:>4}" for n in names))
        for i in range(min(5, t["count"])):
            base = t["first_anchor"] + i * t["stride"]
            row = "  ".join(f"{int(mem[base + offsets[n]]):>4}" for n in names)
            self.rt_print(f"  #{i:<4}           {row}")
        self.rt_print("\nIf those look like real ratings, click 'Save table to library'.")
        self.say(f"Found a roster table with {t['count']} players.")

    def save_found_table(self):
        if not self.found:
            messagebox.showinfo(APP_TITLE, "Find a roster table first.")
            return
        r = ask_form(self.root, "Save roster table", [
            ("name", "Name", "entry", "Player ratings", None),
            ("category", "Category", "combo", "Ratings", self.categories()),
        ])
        if not r or not r["name"]:
            return
        f = self.found
        self.library.append(core.new_table_entry(r["name"], r["category"] or "Ratings",
                                                 f["first_anchor"], f["stride"], f["count"], f["offsets"]))
        self.library_changed()
        self.nb.select(self.lib_tab)
        self.say("Roster table saved. Its fields are now editable in the Library tab.")

    # ======================= library ===========================================
    def categories(self):
        cats = list(core.DEFAULT_CATEGORIES)
        for e in self.library:
            if e["category"] not in cats:
                cats.append(e["category"])
        return cats

    def library_changed(self):
        self.save_library(self.lib_path, quiet=True)
        self.rebuild_library_tree()
        self._remember_shapes()

    def rebuild_library_tree(self):
        t = self.lib_tree
        t.delete(*t.get_children())
        self.lib_items.clear()
        cats = {}
        for cat in self.categories():
            if any(e["category"] == cat for e in self.library):
                cats[cat] = t.insert("", "end", text=cat, open=True)
        rec = max(0, self.show_record.get())
        for e in self.library:
            parent = cats[e["category"]]
            if e["kind"] == "value":
                iid = t.insert(parent, "end", text=e["name"],
                               values=(f"{core.fa(e['addr'], e['type'])}", e["type"], "", self._frozen_text(e),
                                       self._moves_text(e)))
                self.lib_items[iid] = (e, None)
            else:
                node = t.insert(parent, "end", open=True,
                                text=f"{e['name']}  ({e['count']} players, {e['stride']} bytes each"
                                     f"{', ' + str(len(e['mirrors'])) + ' linked copies' if e.get('mirrors') else ''})",
                                values=("", "table", f"showing player #{rec}", ""))
                self.lib_items[node] = (e, None)
                for field in e["fields"]:
                    addr = core.table_field_addr(e, min(rec, e["count"] - 1), field)
                    iid = t.insert(node, "end", text=field, values=(f"{core.fa(addr, 'byte')}", "byte", "", ""))
                    self.lib_items[iid] = (e, field)
        self.refresh_library_values()

    @staticmethod
    def _moves_text(e):
        if e.get("lost"):
            return "LOST - re-find it"
        if e.get("moving"):
            n = len(e.get("paths") or [])
            return f"tracked live ({n} pointer path{'s' if n != 1 else ''})" if n else "tracked live"
        if e.get("moved"):
            return f"moved {e['moved']}x - followed it"
        return "auto-checked" if e.get("fp") else ""

    # ---- values that move around ----
    def _remember_shapes(self):
        """Fingerprint new library values in the background (what surrounds them in memory)."""
        todo = [e for e in self.library if e.get("kind") == "value" and not e.get("fp")]
        if not todo or not self.ps2.attached:
            return

        def work():
            try:
                first = [core.read_window(self.ps2, None, e["addr"], e["type"]) if hasattr(self.ps2, "read_block")
                         else None for e in todo]
                snap1 = None if hasattr(self.ps2, "read_block") else self.snap()
                time.sleep(0.5)
                snap2 = None if hasattr(self.ps2, "read_block") else self.snap()
                for i, e in enumerate(todo):
                    if snap1 is not None:
                        e["fp"] = core.fingerprint([snap1, snap2], e["addr"], e["type"])
                    elif first[i] is not None and first[i][1] is not None:
                        second = core.read_window(self.ps2, None, e["addr"], e["type"])
                        if second[1] is not None:
                            e["fp"] = core.fingerprint(None, e["addr"], e["type"], blocks=[first[i], second])
                self.ui(self.library_changed_quiet)
            except Exception as ex:
                self.ui(self.say, f"Couldn't fingerprint values: {ex}")
        threading.Thread(target=work, daemon=True).start()

    def library_changed_quiet(self):
        self.save_library(self.lib_path, quiet=True)
        self.rebuild_library_tree()

    def lib_toggle_moving(self):
        item = self._selected_lib()
        if not item:
            return
        e, _ = item
        if e["kind"] != "value":
            messagebox.showinfo(APP_TITLE, "Pick a single value (not a roster table).")
            return
        if e.get("moving"):
            e["moving"] = False
            self.library_changed()
            return
        if not self.need_attach():
            return
        e["moving"] = True
        self.say(f"Tracking '{e['name']}': finding pointers to it (a few seconds)...")

        def work():
            snap = self.snap()
            try:
                if not e.get("fp"):
                    time.sleep(0.4)
                    e["fp"] = core.fingerprint([snap, self.snap()], e["addr"], e["type"])
                e["paths"] = core.pointer_scan(self.ps2, snap, e["addr"])
                e["ptr_size"] = getattr(self.ps2, "ptr_size", 4)
                msg = (f"'{e['name']}' is tracked: {len(e['paths'])} pointer paths + its fingerprint. Every time you "
                       "start the game it's found again by itself, and the paths that don't hold up get dropped.")
            except Exception as ex:
                msg = f"Pointer scan failed ({ex}) - it will still be found by its fingerprint."
            self.ui(self.library_changed_quiet)
            self.ui(self.say, msg)
        threading.Thread(target=work, daemon=True).start()

    def relocate_all(self, report=False):
        """Check every saved value is where we think it is; follow the ones that moved."""
        ents = [e for e in self.library if e.get("kind") == "value" and (e.get("fp") or e.get("paths"))]
        if not ents or not self.ps2.attached:
            if report:
                self.say("Nothing to check yet - values get a fingerprint when you save them while attached.")
            return

        def work():
            snap = self.snap()
            moved, lost = [], []
            for e in ents:
                try:
                    off, how = core.relocate(self.ps2, snap, e)
                except Exception as ex:
                    off, how = None, str(ex)
                if off is None:
                    e["lost"] = True
                    lost.append(e["name"])
                    continue
                e.pop("lost", None)
                if off != e["addr"]:
                    old = core.fa(e["addr"], e["type"])
                    e["addr"] = off
                    e["moved"] = int(e.get("moved", 0)) + 1
                    moved.append(f"{e['name']} {old} -> {core.fa(off, e['type'])} ({how})")
                if e.get("paths"):
                    core.prune_paths(self.ps2, e, off)
            self.ui(self._relocated, moved, lost, report)
        threading.Thread(target=work, daemon=True).start()

    def _relocated(self, moved, lost, report):
        self.library_changed_quiet()
        msg = ""
        if moved:
            msg += "Moved and followed: " + "; ".join(moved[:4]) + (" ..." if len(moved) > 4 else "") + ". "
        if lost:
            msg += "Couldn't find: " + ", ".join(lost[:5]) + " - re-find with the AI Coach (it's set to that game). "
        if msg or report:
            self.say(msg or "All saved values are where they were.")

    def _fp_live(self, e, off):
        if not e.get("fp") or not hasattr(self.ps2, "read_block"):
            return None
        return core.fp_score(None, e["fp"], off, self.ps2)

    def _move_watch(self):
        """While playing: values marked 'moves around' are re-checked every 2 s (levels reload, respawns)."""
        try:
            if self.ps2.attached:
                stale = False
                for e in self.library:
                    if e.get("kind") != "value" or not e.get("moving"):
                        continue
                    here = self._fp_live(e, e["addr"])
                    if e.get("paths") and (here is None or here < 0.9):
                        votes = {}
                        for b, p in e["paths"][:30]:
                            o = core.follow_path(self.ps2, b, p, e.get("ptr_size"))
                            if o is not None and o != e["addr"]:
                                votes[o] = votes.get(o, 0) + 1
                        scored = [(self._fp_live(e, o) or 0, n, o) for o, n in votes.items()]
                        scored = [x for x in scored if x[0] >= 0.7 or (here is None and e.get("paths_ok"))]
                        if scored:
                            best = max(scored)[2]
                            e["addr"] = best
                            e["moved"] = int(e.get("moved", 0)) + 1
                            self.rebuild_library_tree()
                            continue
                    if here is not None and here < 0.6:
                        stale = True
                if stale and time.time() - getattr(self, "_last_reloc", 0) > 10:
                    self._last_reloc = time.time()
                    self.relocate_all()
        finally:
            self.root.after(2000, self._move_watch)
        self.root.after(3000, lambda: self.update_check(quiet=True))

    @staticmethod
    def _frozen_text(e):
        return f"yes = {e['freeze_value']}" if e.get("freeze") else ""

    def refresh_library_values(self):
        if not self.ps2.attached:
            return
        rec = max(0, self.show_record.get())
        for iid, (e, field) in self.lib_items.items():
            try:
                if e["kind"] == "value":
                    v = self.ps2.read(e["addr"], e["type"])
                elif field:
                    v = self.ps2.read(core.table_field_addr(e, min(rec, e["count"] - 1), field), "byte")
                else:
                    continue
                self.lib_tree.set(iid, "value", "?" if v is None else core.fmt_value(
                    e["type"] if e["kind"] == "value" else "byte", v))
            except tk.TclError:
                pass

    def _selected_lib(self):
        sel = self.lib_tree.selection()
        return self.lib_items.get(sel[0]) if sel else None

    def lib_edit_value(self):
        item = self._selected_lib()
        if not item or not self.need_attach():
            return
        e, field = item
        if e["kind"] == "table" and not field:
            return
        vtype = e["type"] if e["kind"] == "value" else "byte"
        rec = min(max(0, self.show_record.get()), e.get("count", 1) - 1)
        addr = e["addr"] if e["kind"] == "value" else core.table_field_addr(e, rec, field)
        cur = self.ps2.read(addr, vtype)
        r = ask_form(self.root, "Edit value", [("value", f"New value for {field or e['name']}",
                                                 "entry", cur, None)])
        if not r:
            return
        try:
            value = core.parse_number(r["value"], vtype)
        except ValueError:
            messagebox.showerror(APP_TITLE, "Not a valid number.")
            return
        addrs = [addr] if e["kind"] == "value" else core.table_write_addrs(e, rec, field)
        failed = [a for a in addrs if not self.ps2.write(a, vtype, value)]
        if failed:
            messagebox.showerror(APP_TITLE,
                f"Windows refused the write to {', '.join(f'{core.fa(a)}' for a in failed)}.\n\n"
                "Close the tool, right-click run_tracker.bat → Run as administrator, attach, "
                "and try again.")
            return
        if e["kind"] == "value" and e.get("freeze"):
            e["freeze_value"] = value  # don't let an old freeze put it back
            self.library_changed()
        self.say(f"Written to {len(addrs)} location(s). Checking whether the game keeps it...")
        self.refresh_library_values()
        self.root.after(600, self._verify_write, e, field, addrs[0], vtype, value)

    def _verify_write(self, e, field, addr, vtype, value):
        """Read the value back a moment later to see if the game overwrote it."""
        now = self.ps2.read(addr, vtype) if self.ps2.attached else None
        same = now is not None and (abs(now - value) < 1e-3 if vtype == "float" else now == value)
        if same:
            self.say(f"Done. The game kept the new value ({core.fmt_value(vtype, value)}).")
            return
        name = field or e["name"]
        if e["kind"] == "value":
            if messagebox.askyesno(APP_TITLE,
                    f"The game changed '{name}' back to {now} within half a second.\n\n"
                    "That means the game recalculates or rewrites this value from somewhere "
                    "else, so a one-time edit can't stick.\n\n"
                    "Freeze it now? (The tool will keep writing your value about 10 times a "
                    "second. For a permanent fix, make it a cheat in the Cheat / menu maker tab, "
                    "or find the value the game copies it from.)"):
                e["freeze"] = True
                e["freeze_value"] = value
                self.library_changed()
                self.say(f"'{name}' frozen at {value}.")
        else:
            self.say(f"The game put '{name}' back to {now}. Open that player's Edit Player screen "
                     "and click 'Find copies of this player', then edit again.")

    def lib_find_copies(self):
        item = self._selected_lib()
        if not item or not self.need_attach():
            return
        e, _ = item
        if e["kind"] != "table":
            messagebox.showinfo(APP_TITLE,
                "'Find copies' works on roster tables made in the Ratings finder tab.\n\n"
                "For a single value from the Scanner, edit it and the tool will tell you if the "
                "game puts it back. If it does, Freeze it or make it a cheat.")
            return
        rec = min(max(0, self.show_record.get()), e["count"] - 1)
        self.say("Searching all 32 MB for other copies of this player...")
        copies = core.find_copies(self.snap(), e, rec)
        if not copies:
            messagebox.showinfo(APP_TITLE,
                "No other copies found right now.\n\nTry again while the game is on the Edit "
                "Player screen for this player (player # set in 'Show player #'), since the "
                "edit copy often only exists while that screen is open.")
            return
        mirrors = e.setdefault("mirrors", [])
        added = 0
        for c in copies:
            m = {"delta": c["delta"], "record": c["record"]}
            if m not in mirrors:
                mirrors.append(m)
                added += 1
        whole = sum(1 for c in copies if c["record"] is None)
        self.library_changed()
        messagebox.showinfo(APP_TITLE,
            f"Found {len(copies)} other copy(ies) of player #{rec}:\n"
            f"  {whole} full roster copy(ies)\n  {len(copies) - whole} one-player buffer(s)\n\n"
            f"{added} new location(s) linked. Edits, 'Set for ALL' and cheats now write every copy.")

    def lib_clear_copies(self):
        item = self._selected_lib()
        if not item or item[0]["kind"] != "table":
            return
        item[0]["mirrors"] = []
        self.library_changed()
        self.say("Unlinked all copies from this table.")

    def lib_toggle_freeze(self):
        item = self._selected_lib()
        if not item:
            return
        e, _ = item
        if e["kind"] != "value":
            messagebox.showinfo(APP_TITLE, "Freeze works on single values. For a whole roster, "
                                           "use 'Set field for ALL players' or a cheat.")
            return
        if e.get("freeze"):
            e["freeze"] = False
        else:
            cur = self.ps2.read(e["addr"], e["type"]) if self.ps2.attached else None
            r = ask_form(self.root, "Freeze", [("value", "Hold at value", "entry", cur, None)])
            if not r:
                return
            try:
                e["freeze_value"] = core.parse_number(r["value"], e["type"])
            except ValueError:
                messagebox.showerror(APP_TITLE, "Not a valid number.")
                return
            e["freeze"] = True
        self.library_changed()

    def lib_set_all(self):
        item = self._selected_lib()
        if not item or not self.need_attach():
            return
        e, field = item
        if e["kind"] != "table" or not field:
            messagebox.showinfo(APP_TITLE, "Select a rating field inside a roster table.")
            return
        r = ask_form(self.root, "Set for all players", [("value", f"Set {field} for all "
                                                                   f"{e['count']} players to", "entry", 99, None)])
        if not r:
            return
        try:
            v = int(r["value"], 0)
        except ValueError:
            return
        for i in range(e["count"]):
            for a in core.table_write_addrs(e, i, field):
                self.ps2.write(a, "byte", v)
        self.say(f"Set {field} = {v} for {e['count']} players (in memory only; make a cheat to keep it).")

    def lib_rename(self):
        item = self._selected_lib()
        if not item:
            return
        e, _ = item
        r = ask_form(self.root, "Rename / move", [
            ("name", "Name", "entry", e["name"], None),
            ("category", "Category", "combo", e["category"], self.categories()),
        ])
        if not r or not r["name"]:
            return
        for c in self.cheats:
            if c["entry"] == e["name"]:
                c["entry"] = r["name"]
        e["name"], e["category"] = r["name"], r["category"] or "Other"
        self.library_changed()
        self.refresh_cheat_tree()

    def lib_delete(self):
        item = self._selected_lib()
        if not item:
            return
        e, _ = item
        if messagebox.askyesno(APP_TITLE, f"Delete '{e['name']}' from the library?"):
            self.library.remove(e)
            self.library_changed()

    def lib_add_manual(self):
        r = ask_form(self.root, "Add address", [
            ("name", "Name", "entry", "", None),
            ("addr", "Address (hex, or game.exe+1234 for PC games)", "entry", "", None),
            ("type", "Type", "combo", "byte", list(core.TYPES)),
            ("category", "Category", "combo", "Other", self.categories()),
        ])
        if not r or not r["name"]:
            return
        vt = r["type"] if r["type"] in core.TYPES else "byte"
        try:
            addr = core.pa(r["addr"], vt)
        except ValueError as e:
            messagebox.showerror(APP_TITLE, f"Address must be hex, e.g. 0032A4C0 ({e})")
            return
        self.library.append(core.new_value_entry(r["name"], r["category"] or "Other", addr, vt))
        self.library_changed()

    # ---- save / load ----
    def save_library(self, path, quiet=False):
        if getattr(self.ps2, "attached", False):
            for e in self.library:
                if e.get("kind") == "value":
                    e["where"] = core.fa(e["addr"], e.get("type"))
        cheats = [{k: v for k, v in c.items() if not k.startswith("_") and k != "on"} for c in self.cheats]
        data = {"game_title": self.game_title.get(), "game": self.game, "genre": self.genre,
                "library": self.library, "cheats": cheats, "spawn": self.spawn,
                "pad": getattr(self, "mem_pad", None)}
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            if not quiet:
                self.say(f"Saved to {path}")
        except OSError as e:
            messagebox.showerror(APP_TITLE, f"Could not save: {e}")

    def save_library_as(self):
        p = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("Library", "*.json")])
        if p:
            self.save_library(p)

    def load_library(self, path, quiet=False):
        if not os.path.exists(path):
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            if not quiet:
                messagebox.showerror(APP_TITLE, f"Could not load: {e}")
            return
        self.library = data.get("library", [])
        self.cheats = data.get("cheats", [])
        self.spawn = data.get("spawn") or {"lists": [], "learned": {}, "observed": []}
        self.mem_pad = data.get("pad")
        self.game_title.set(data.get("game_title", self.game_title.get()))
        self.rebuild_library_tree()
        self.refresh_cheat_tree()
        self.refresh_spawn_list()

    def load_library_dialog(self):
        p = filedialog.askopenfilename(filetypes=[("Library", "*.json")])
        if p:
            self.load_library(p)
            self.save_library(self.lib_path, quiet=True)

    # ======================= game detection / tailoring ==========================
    def tailor_ui(self, genre):
        g = gameinfo.GENRES.get(genre) or gameinfo.GENRES["other"]
        self.genre = genre if genre in gameinfo.GENRES else "other"
        self.genre_var.set(g["label"])
        for key, tab in (("boost", self.boost_tab), ("ratings", self.ratings_tab), ("spawn", self.spawn_tab)):
            try:
                self.nb.tab(tab, state="normal" if key in g["tabs"] else "hidden")
            except tk.TclError:
                pass
        try:
            if self.nb.tab(self.nb.select(), "state") == "hidden":
                self.nb.select(self.coach_tab)
        except tk.TclError:
            pass
        if g["predict"]:
            self.pred_frame.pack(fill="x", pady=(8, 0), before=self.claude_frame)
        else:
            self.pred_frame.pack_forget()
        ball = "boost" in g["tabs"]
        if ball:
            self.hit_frame.pack(fill="x", before=self.coach_status)
        else:
            self.hit_frame.pack_forget()
        show = {"quick", "freeze", "save", "more", "group", "speed", "hack", "test", "rec", "auto"} | ({"boost", "deep"} if ball else set()) | \
               ({"spawn"} if "spawn" in g["tabs"] else set()) | ({"pexp"} if g["predict"] else set())
        for key, btn in self.coach_btns.items():
            btn.pack_forget()
        for key, btn in self.coach_btns.items():
            if key in show:
                btn.pack(fill="x", pady=2)
        evs = gameinfo.events_for(self.genre)
        labels = [core.EVENT_RECIPES[k]["label"] for k in evs]
        self.rec_event_box.configure(values=labels)
        if self.rec_event.get() not in labels[:len(gameinfo.EVENTS.get(self.genre, labels))]:
            self.rec_event.set(labels[0])
        ex = list(g["examples"])
        if "spawn" in g["tabs"] and g["spawn"]:
            ex.append(f'"which {g["spawn"][0][:-1].lower()} am I using" (for the spawn menu)')
        self.examples_lbl.configure(text="Examples:  " + "   ".join(ex))
        if g["spawn"] and self.spawn_kind.get() not in g["spawn"]:
            self.spawn_kind.set(g["spawn"][0])

    def _genre_picked(self, *_):
        key = next((k for k, g in gameinfo.GENRES.items() if g["label"] == self.genre_var.get()), "other")
        self.tailor_ui(key)
        if self.game:
            self.settings.setdefault("game_types", {})[self.game["key"]] = key
            self._save_settings(quiet=True)

    def detect_game(self):
        titles = core.window_titles(self.ps2.pid) if core.IS_WIN else []
        return gameinfo.detect(getattr(self.ps2, "profile", "ps2"), titles, getattr(self.ps2, "exe", "") or "")

    def apply_game(self, info, quiet=False):
        """A game was detected (on attach, or the emulator switched games)."""
        if not info.get("found"):
            if not quiet:
                self.say("Attached, but no game is running yet - boot a game and I'll pick it up by itself.")
            return
        if self.game and self.game.get("key") == info["key"]:
            return
        self.game = info
        self.switch_library(info)
        self.game_title.set(info["title"])
        genre = self.settings.get("game_types", {}).get(info["key"]) or gameinfo.classify(info["title"])
        self.tailor_ui(genre)
        tag = f" ({info['serial']})" if info.get("serial") else ""
        self.say(f"Game: {info['title']}{tag} - set up for {gameinfo.GENRES[self.genre]['label']}. "
                 "Wrong type? Change 'Game type' at the top.")
        b = self.brain()
        if genre == "other" and b.usable and info["key"] not in self.settings.get("game_types", {}):
            def ask():
                try:
                    gk = gameinfo.classify_with_brain(info["title"], b)
                except Exception:
                    gk = None
                if gk:
                    self.ui(self._claude_genre, info["key"], gk)
            threading.Thread(target=ask, daemon=True).start()

    def _claude_genre(self, key, genre):
        if self.game and self.game["key"] == key:
            self.settings.setdefault("game_types", {})[key] = genre
            self._save_settings(quiet=True)
            self.tailor_ui(genre)
            self.say(f"{self.brain().name} says {self.game['title']} is {gameinfo.GENRES[genre]['label']} - tabs set for that.")

    @staticmethod
    def _same_game(a, b):
        na, nb = ("".join(ch for ch in (x or "").lower() if ch.isalnum()) for x in (a, b))
        return bool(na and nb) and (na in nb or nb in na)

    def switch_library(self, info):
        """Every game gets its own library, cheats and spawn lists."""
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in info["key"])[:80]
        path = os.path.join(LIB_DIR, safe + ".json")
        if os.path.abspath(path) == os.path.abspath(self.lib_path):
            return
        had = bool(self.library or self.cheats)
        if had:
            self.save_library(self.lib_path, quiet=True)
        if os.path.exists(path):
            self.lib_path = path
            self.load_library(path, quiet=True)
        else:
            legacy = self.lib_path == SAVE_FILE and had and self._same_game(self.game_title.get(), info["title"])
            if not legacy:
                self.library, self.cheats = [], []
                self.spawn = {"lists": [], "learned": {}, "observed": []}
                self.mem_pad = None
            self.lib_path = path
            self.save_library(path, quiet=True)
            self.rebuild_library_tree()
            self.refresh_cheat_tree()
            self.refresh_spawn_list()
        self._refresh_hit_sources()

    def _game_watch(self):
        """Every few seconds: did the emulator boot / switch games?"""
        try:
            if self.ps2.attached and core.IS_WIN and getattr(self.ps2, "profile", "pc") not in ("pc", "pc_be"):
                info = self.detect_game()
                if info.get("found") and (not self.game or info["key"] != self.game["key"]):
                    try:                                   # memory can move when a new game boots
                        self.ps2.attach(None, pid=self.ps2.pid, profile=self.ps2.profile)
                    except Exception:
                        pass
                    self.apply_game(info)
                    self.relocate_all()
        finally:
            self.root.after(4000, self._game_watch)

    # ======================= cheats ===========================================
    def _targets(self):
        out = []
        for e in self.library:
            if e["kind"] == "value":
                out.append(e["name"])
            else:
                out.extend(f"{e['name']} › {f}" for f in e["fields"])
        return out

    MODE_LABELS = {"freeze": "keep it at (on/off)", "scale": "keep it multiplied by - speed hack (on/off)",
                   "set": "set to (one press)",
                   "add": "add (one press)", "multiply": "multiply by (one press)"}

    def describe_add(self):
        text = self.describe_var.get().strip()
        if not text:
            return
        names = [e["name"] for e in self.library if e["kind"] == "value"]
        try:
            c = modmenu.describe_cheat(text, names)
        except ValueError as e:
            messagebox.showinfo(APP_TITLE, str(e))
            return
        ent = next(e for e in self.library if e["name"] == c["entry"])
        if c["value"] is not None and ent["type"] != "float":
            c["value"] = int(round(c["value"]))
        self.cheats.append(c)
        self.describe_var.set("")
        self.save_library(self.lib_path, quiet=True)
        self.refresh_cheat_tree()
        self.preview_pnach()
        self.say(f"Added '{c['name']}': {self._does(c)}" + (f", hotkey {modmenu.combo_text(c['hotkey'])}"
                                                           if c.get("hotkey") else "") + ".")

    def add_cheat(self):
        targets = self._targets()
        if not targets:
            messagebox.showinfo(APP_TITLE, "Add some values to the library first.")
            return
        pads = [e["name"] for e in self.library if e["kind"] == "value" and e["type"] == "u16"]
        hk_var = tk.StringVar()

        def extra(frm, widgets, row):
            ttk.Label(frm, text="Hotkey (optional)").grid(row=row, column=0, sticky="w")
            hrow = ttk.Frame(frm)
            hrow.grid(row=row, column=1, sticky="ew")
            ttk.Entry(hrow, textvariable=hk_var, width=22).pack(side="left")
            ttk.Button(hrow, text="Capture...", command=lambda: self._capture_into(hk_var)).pack(side="left", padx=4)
            widgets["hotkey"] = (hk_var, None)
            ttk.Separator(frm).grid(row=row + 1, column=0, columnspan=3, sticky="ew", pady=8)
            ttk.Label(frm, text="Code activator - only for exported codes (.pnach / Gecko ...)\n"
                                "(a 2-byte Controller value from the library)",
                      foreground="#335").grid(row=row + 2, column=0, columnspan=2, sticky="w")
            var_e, var_v = tk.StringVar(), tk.StringVar()
            ttk.Label(frm, text="Controller value").grid(row=row + 3, column=0, sticky="w")
            ttk.Combobox(frm, textvariable=var_e, values=[""] + pads, width=34).grid(row=row + 3, column=1)
            ttk.Label(frm, text="Button combo (hex)").grid(row=row + 4, column=0, sticky="w")
            ttk.Entry(frm, textvariable=var_v, width=36).grid(row=row + 4, column=1)

            def capture():
                ent = next((e for e in self.library if e["name"] == var_e.get()), None)
                if not ent or not self.ps2.attached:
                    messagebox.showinfo(APP_TITLE, "Pick a controller value and attach first.")
                    return

                def tick(n):
                    if n > 0:
                        cap_btn.configure(text=f"Hold the combo in-game... {n}")
                        frm.after(1000, tick, n - 1)
                    else:
                        v = self.ps2.read(ent["addr"], "u16")
                        var_v.set(f"{v:04X}" if v is not None else "")
                        cap_btn.configure(text="Capture combo (3 s)")
                tick(3)

            cap_btn = ttk.Button(frm, text="Capture combo (3 s)", command=capture)
            cap_btn.grid(row=row + 5, column=1, sticky="w", pady=4)
            widgets["act_entry"] = (var_e, None)
            widgets["act_value"] = (var_v, None)
            return row + 6

        r = ask_form(self.root, "Add cheat", [
            ("name", "Cheat name", "entry", "", None),
            ("target", "Changes", "combo", targets[0], targets),
            ("record", "Which player (tables): all or #", "entry", "all", None),
            ("mode", "What it does", "combo", self.MODE_LABELS["freeze"], list(self.MODE_LABELS.values())),
            ("value", "Value (empty = keep the current value)", "entry", "", None),
            ("group", "Menu group", "entry", "Cheats", None),
        ], extra=extra)
        if not r or not r["name"]:
            return
        target = r["target"]
        entry_name, field = target.split(" › ", 1) if " › " in target else (target, None)
        entry = next((e for e in self.library if e["name"] == entry_name), None)
        if not entry:
            messagebox.showerror(APP_TITLE, "Pick a target from the list.")
            return
        mode = next((k for k, v in self.MODE_LABELS.items() if v == r.get("mode")), "freeze")
        vtype = entry["type"] if entry["kind"] == "value" else "byte"
        value = None
        if r.get("value"):
            try:
                value = float(r["value"]) if mode == "multiply" else core.parse_number(r["value"], vtype)
            except ValueError:
                messagebox.showerror(APP_TITLE, "Value must be a number.")
                return
        elif mode != "freeze":
            messagebox.showerror(APP_TITLE, "That kind of cheat needs a value.")
            return
        try:
            hotkey = modmenu.parse_combo(r.get("hotkey", ""))
        except ValueError as e:
            messagebox.showerror(APP_TITLE, str(e))
            return
        cheat = {"name": r["name"], "entry": entry_name, "value": value, "mode": mode, "hotkey": hotkey,
                 "group": r.get("group") or "Cheats", "activator": None}
        if field:
            cheat["field"] = field
            rec = (r.get("record") or "all").lower()
            cheat["record"] = "all" if rec in ("", "all") else int(rec)
        if r.get("act_entry"):
            try:
                cheat["activator"] = {"entry": r["act_entry"], "value": int(r["act_value"], 16)}
            except ValueError:
                messagebox.showerror(APP_TITLE, "Button combo must be hex (use Capture).")
                return
        try:
            core.cheat_writes(cheat, self.library)  # validate
        except ValueError as e:
            messagebox.showerror(APP_TITLE, str(e))
            return
        self.cheats.append(cheat)
        self.save_library(self.lib_path, quiet=True)
        self.refresh_cheat_tree()
        self.preview_pnach()

    def add_code_patch(self):
        if self._profile() != "ps2":
            messagebox.showinfo(APP_TITLE, "Code patches are made for PCSX2 (.pnach). For other emulators use "
                                "their own debugger / patch system; for PC games use Cheat Engine's "
                                "\"Replace with code that does nothing\" on the instruction.")
            return
        r = ask_form(self.root, "Add code patch", [
            ("name", "Patch name", "entry", "No ball slowdown", None),
            ("addr", "Instruction address (hex, from PCSX2 debugger)", "entry", "", None),
            ("value", "New instruction (hex) - 00000000 = NOP (skip it)", "entry", "00000000", None),
        ])
        if not r or not r["name"]:
            return
        try:
            cheat = {"name": r["name"], "code": True, "entry": "(code)",
                     "addr": int(r["addr"].replace("0x", ""), 16), "value": int(r["value"] or "0", 16),
                     "activator": None}
            core.cheat_lines(cheat, self.library)
        except ValueError as e:
            messagebox.showerror(APP_TITLE, str(e) if "Code patch" in str(e) else "Address and value must be hex.")
            return
        self.cheats.append(cheat)
        self.save_library(self.lib_path, quiet=True)
        self.refresh_cheat_tree()
        self.preview_pnach()

    def remove_cheat(self):
        sel = self.ch_tree.selection()
        if not sel:
            return
        del self.cheats[int(sel[0])]
        self.save_library(self.lib_path, quiet=True)
        self.refresh_cheat_tree()
        self.preview_pnach()

    def _does(self, c):
        if c.get("code"):
            return f"CODE at {c['addr']:08X} = {c['value']:08X}"
        target = c["entry"] + (f" › {c['field']} ({'all players' if c.get('record', 'all') == 'all' else '#' + str(c['record'])})"
                               if c.get("field") else "")
        mode = c.get("mode", "freeze")
        v = c.get("value")
        if mode == "freeze":
            return f"keep {target} at " + ("its current value" if v is None else f"{v:g}")
        return {"scale": f"keep {target} multiplied by {v:g} (speed hack)",
                "set": f"set {target} to {v:g}", "add": f"add {v:g} to {target}",
                "multiply": f"multiply {target} by {v:g}"}[mode]

    def refresh_cheat_tree(self):
        if not hasattr(self, "ch_tree"):
            return
        self.ch_tree.delete(*self.ch_tree.get_children())
        for i, c in enumerate(self.cheats):
            act = f"{c['activator']['entry']} = {c['activator']['value']:04X}" if c.get("activator") else "-"
            self.ch_tree.insert("", "end", iid=str(i), text=c["name"],
                                values=(self._does(c), modmenu.combo_text(c.get("hotkey")),
                                        "-" if c.get("code") else c.get("group") or "Cheats", act))

    def _exportable(self):
        """Codes can only hold a value - one-shot add/multiply and spawn items stay in the live menu."""
        out = []
        for c in self.cheats:
            if c.get("code"):
                out.append(c)
            elif c.get("mode", "freeze") in ("freeze", "set") and c.get("value") is not None \
                    and not str(c.get("group", "")).startswith("Spawn"):
                out.append(c)
        return out

    def preview_pnach(self):
        self.pnach_text.delete("1.0", "end")
        cheats = self._exportable()
        skipped = len(self.cheats) - len(cheats)
        note = (f"\n; {skipped} menu-only cheat(s) (add / multiply / keep-current / spawn) aren't codes - "
                "they run from the in-game mod menu.\n" if skipped else "")
        try:
            if self._profile() != "ps2":
                self.pnach_text.insert("1.0", core.export_codes(self.ps2, cheats, self.library,
                                                                self.game_title.get())[0] + note)
                return
            self.pnach_text.insert("1.0", core.build_pnach(self.game_title.get(), cheats, self.library) + note)
        except ValueError as e:
            self.pnach_text.insert("1.0", f"Error: {e}")

    def _profile(self):
        return getattr(self.ps2, "profile", "ps2") if getattr(self.ps2, "attached", False) else "ps2"

    def export_pnach(self):
        if not self._exportable():
            messagebox.showinfo(APP_TITLE, "No cheats that can become codes yet (add a 'keep it at' or 'set to' "
                                "cheat with a value). Everything works live in the mod menu though.")
            return
        if self._profile() != "ps2":
            return self.export_other()
        r = ask_form(self.root, "Game CRC", [("crc", "Game CRC (8 hex digits, shown in PCSX2 "
                                                     "Game Properties / log)", "entry", "", None)])
        if not r:
            return
        crc = r["crc"].upper().replace("0X", "")
        if len(crc) != 8 or any(ch not in "0123456789ABCDEF" for ch in crc):
            messagebox.showerror(APP_TITLE, "CRC must be 8 hex digits, e.g. 1A2B3C4D")
            return
        default_dir = os.path.join(os.path.expanduser("~"), "Documents", "PCSX2", "cheats")
        path = filedialog.asksaveasfilename(
            initialdir=default_dir if os.path.isdir(default_dir) else APP_DIR,
            initialfile=f"{crc}.pnach", defaultextension=".pnach", filetypes=[("PCSX2 cheats", "*.pnach")])
        if not path:
            return
        try:
            text = core.build_pnach(self.game_title.get(), self._exportable(), self.library)
        except ValueError as e:
            messagebox.showerror(APP_TITLE, str(e))
            return
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        self.say(f"Wrote {path}. In PCSX2: right-click the game → Properties → Cheats, tick them on.")

    def export_other(self):
        try:
            text, ext, how = core.export_codes(self.ps2, self._exportable(), self.library, self.game_title.get())
        except ValueError as e:
            messagebox.showerror(APP_TITLE, str(e))
            return
        if any(c.get("code") for c in self.cheats):
            how += "\n\n(Code patches are PS2-only and were left out.)"
        safe = "".join(ch for ch in self.game_title.get() if ch.isalnum() or ch in " -_").strip() or "cheats"
        path = filedialog.asksaveasfilename(initialdir=APP_DIR, initialfile=safe + ext, defaultextension=ext)
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        messagebox.showinfo(APP_TITLE, f"Wrote {path}\n\n{how}\n\nThe in-game mod menu in this tool works on "
                            "every system too.")
        return path

    # ======================= hotkeys & the in-game menu ===========================
    def _menu_keys(self):
        return dict(modmenu.DEFAULT_MENU, **self.settings.get("menu_keys", {}))

    def _update_menu_labels(self):
        k = self._menu_keys()
        self.menu_open_lbl.configure(text=f"{modmenu.combo_text(k['open'])}   (keyboard: {modmenu.combo_text(k['kb_open'])})")

    def _held(self, pad=None, kb=None):
        """Everything held right now: controller buttons + keyboard keys."""
        src = self.pad_src.get()
        held = set()
        if src == PAD_SOURCES[0] and pad is not None:
            held |= pad.pressed()
        if src == PAD_SOURCES[2] and self.mem_pad and self.ps2.attached:
            ent = next((e for e in self.library if e["name"] == self.mem_pad.get("entry")), None)
            if ent:
                raw = self.ps2.read(ent["addr"], ent["type"])
                if raw is not None:
                    mp = {k: tuple(v) for k, v in self.mem_pad.get("map", {}).items()}
                    held |= modmenu.mem_pad_pressed(int(raw), mp)
        if kb is not None:
            held |= kb.pressed()
        return held

    def _capture_combo(self, title):
        """Small window: hold the buttons / keys you want. Returns a list or None."""
        dlg = tk.Toplevel(self.root)
        dlg.title(title)
        dlg.transient(self.root)
        dlg.attributes("-topmost", True)
        ttk.Label(dlg, padding=12, font=("Segoe UI", 11), text="Hold the button combo on your controller\n"
                  "(or the keys on the keyboard) and keep holding...").pack()
        lbl = ttk.Label(dlg, font=("Segoe UI", 16, "bold"), text="-")
        lbl.pack(pady=6)
        typed = tk.StringVar()
        row = ttk.Frame(dlg, padding=8)
        row.pack()
        ttk.Label(row, text="or type it:").pack(side="left")
        ttk.Entry(row, textvariable=typed, width=18).pack(side="left", padx=4)
        result = {"combo": None, "best": []}
        pad, kb = modmenu.XInputPad(), modmenu.Keyboard()
        t0 = time.time()

        def poll():
            if not dlg.winfo_exists():
                return
            held = sorted(self._held(pad, kb) - {"Enter"}, key=lambda b: (b not in modmenu.BUTTONS, b))
            if len(held) >= len(result["best"]) and held:
                result["best"] = held
            lbl.configure(text=modmenu.combo_text(result["best"]))
            if result["best"] and not held and time.time() - t0 > 0.5:
                ok()
                return
            dlg.after(30, poll)

        def ok():
            if typed.get().strip():
                try:
                    result["combo"] = modmenu.parse_combo(typed.get())
                except ValueError as e:
                    messagebox.showerror(APP_TITLE, str(e), parent=dlg)
                    return
            else:
                result["combo"] = result["best"] or None
            dlg.destroy()

        bb = ttk.Frame(dlg, padding=8)
        bb.pack()
        ttk.Button(bb, text="OK", command=ok).pack(side="left", padx=4)
        ttk.Button(bb, text="Clear hotkey", command=lambda: (result.update(combo=[]), dlg.destroy())).pack(side="left")
        ttk.Button(bb, text="Cancel", command=dlg.destroy).pack(side="left", padx=4)
        dlg.after(300, poll)
        dlg.grab_set()
        self.root.wait_window(dlg)
        return result["combo"]

    def _capture_into(self, var):
        combo = self._capture_combo("Capture hotkey")
        if combo is not None:
            var.set(" + ".join(combo))

    def set_cheat_hotkey(self):
        sel = self.ch_tree.selection()
        if not sel:
            messagebox.showinfo(APP_TITLE, "Pick a cheat in the list first.")
            return
        c = self.cheats[int(sel[0])]
        combo = self._capture_combo(f"Hotkey for '{c['name']}'")
        if combo is None:
            return
        c["hotkey"] = combo
        self.save_library(self.lib_path, quiet=True)
        self.refresh_cheat_tree()

    def set_menu_combo(self):
        combo = self._capture_combo("Button combo that opens the mod menu")
        if not combo:
            return
        keys = self.settings.setdefault("menu_keys", {})
        if all(b in modmenu.BUTTONS for b in combo):
            keys["open"] = combo
        else:
            keys["kb_open"] = combo
        self._save_settings(quiet=True)
        self._update_menu_labels()

    def learn_mem_pad(self):
        """For games where XInput isn't an option: learn the controller value in the game's memory."""
        if not self.need_attach():
            return
        pads = [e["name"] for e in self.library if e["kind"] == "value" and e["type"] in ("u16", "u32")]
        if not pads:
            messagebox.showinfo(APP_TITLE, "First find the controller value: AI Coach -> type \"controller "
                                "buttons\" (or Scanner: u16, F5 holding nothing, F6 while holding a button, F6 "
                                "after letting go, F7 a few times). Save it to the library, then come back.")
            return
        r = ask_form(self.root, "Learn game pad", [("entry", "Controller value", "combo", pads[0], pads)])
        if not r:
            return
        ent = next(e for e in self.library if e["name"] == r["entry"])
        need = ["Up", "Down", "Cross", "Circle"] + [b for b in self._menu_keys()["open"]]
        for c in self.cheats:
            need += [b for b in (c.get("hotkey") or []) if b in modmenu.BUTTONS]
        need = list(dict.fromkeys(need))
        samples = {}
        messagebox.showinfo(APP_TITLE, "Let go of every button, then click OK.")
        idle = self.ps2.read(ent["addr"], ent["type"])
        for b in need:
            if not messagebox.askokcancel(APP_TITLE, f"Hold {b} on the controller (in the game window is fine), "
                                          "then press Enter / click OK while still holding it."):
                return
            samples[b] = self.ps2.read(ent["addr"], ent["type"])
        mapping = modmenu.learn_pad_mapping(int(idle), {k: int(v) for k, v in samples.items() if v is not None})
        missing = [b for b in need if b not in mapping]
        self.mem_pad = {"entry": ent["name"], "idle": int(idle), "map": {k: list(v) for k, v in mapping.items()}}
        self.pad_src.set(PAD_SOURCES[2])
        self.save_library(self.lib_path, quiet=True)
        messagebox.showinfo(APP_TITLE, f"Learned {len(mapping)} buttons." + (
            f" Couldn't learn: {', '.join(missing)} (more than one bit changed - try again holding only that "
            "button)." if missing else ""))

    def menu_toggle(self):
        if self.menu_on:
            self.menu_on = False
            self.menu_btn.configure(text="Start mod menu")
            if getattr(self, "menu_ov", None):
                self.menu_ov.hide()
            for c in self.cheats:
                if not c.get("_manual"):
                    c["on"] = False
            self.pad_lbl.configure(text="Mod menu stopped.")
            return
        if not self.need_attach():
            return
        live = [c for c in self.cheats if not c.get("code")]
        if not live:
            messagebox.showinfo(APP_TITLE, "Add some cheats (or spawn items) first.")
            return
        self.settings["pad_src"] = self.pad_src.get()
        self._save_settings(quiet=True)
        self.menu = modmenu.MenuEngine(live, self._menu_keys())
        if not getattr(self, "menu_ov", None):
            self.menu_ov = MenuOverlay(self)
        self.menu_on = True
        self.menu_btn.configure(text="Stop mod menu")
        pad = modmenu.XInputPad()
        if self.pad_src.get() == PAD_SOURCES[0] and not pad.available:
            note = "XInput isn't available on this PC - use the keyboard keys or 'Learn game pad'."
        else:
            note = "Controller: " + ("XInput" if self.pad_src.get() == PAD_SOURCES[0] else self.pad_src.get().split(" (")[0])
        k = self._menu_keys()
        self.pad_lbl.configure(text=f"Mod menu running. Open it with {modmenu.combo_text(k['open'])} or "
                                    f"{modmenu.combo_text(k['kb_open'])}. {note}")
        self.menu_ov.toast(f"Mod menu ready - {modmenu.combo_text(k['open'])} to open")
        threading.Thread(target=self._menu_thread, daemon=True).start()

    def _menu_thread(self):
        pad, kb = modmenu.XInputPad(), modmenu.Keyboard()
        last = 0.0
        while self.menu_on and self.ps2.attached:
            try:
                held = self._held(pad, kb)
                for ev in self.menu.tick(held):
                    self.ui(self._menu_event, ev)
            except Exception as e:
                self.ui(self.say, f"Mod menu: {e}")
            time.sleep(1 / 60)

    def _menu_event(self, ev):
        kind, obj = ev
        ov = self.menu_ov
        if kind == "menu":
            ov.show() if obj else ov.hide()
        elif kind == "toggle":
            c = obj
            if c.get("on") and c.get("value") is None:
                c["_hold"] = [self.ps2.read(o, vt) for o, vt, _ in core.cheat_writes(c, self.library)[0]]
            ov.toast(f"{c['name']}: {'ON' if c.get('on') else 'OFF'}")
        elif kind == "fire":
            self._apply_cheat(obj, one_shot=True)
            hold = float(obj.get("hold") or 0)
            if hold > 0:
                for o, vt, v in core.cheat_writes(obj, self.library)[0]:
                    self._holds.append((o, vt, v, time.time() + hold))
            ov.toast(("Spawned " if str(obj.get("group", "")).startswith("Spawn") else "") + obj["name"])
        if self.menu.open:
            ov.draw(self.menu)

    def _live_thread(self):
        """Applies every cheat that's switched ON (menu, hotkey or 'Speed hack' button) ~60x a second."""
        while True:
            try:
                if self.ps2.attached:
                    for c in list(self.cheats):
                        if c.get("on") and c.get("mode", "freeze") in modmenu.TOGGLE_MODES:
                            self._apply_cheat(c)
                        elif c.get("mode") == "scale" and self.cheats_learning:
                            self._learn_natural(c)        # how fast is normal? (caps the speed hack)
            except Exception:
                pass
            time.sleep(1 / 60)

    cheats_learning = True

    def _learn_natural(self, c):
        try:
            writes, _ = core.cheat_writes(c, self.library)
        except ValueError:
            return
        nat = c.setdefault("_nat", {})
        for o, vt, _ in writes:
            v = self.ps2.read(o, vt)
            if v is not None and v == v and abs(v) < 1e7:
                nat[o] = max(nat.get(o, 0.0), abs(v))

    def _apply_cheat(self, c, one_shot=False):
        writes, _ = core.cheat_writes(c, self.library)
        mode = c.get("mode", "freeze")
        for i, (o, vt, v) in enumerate(writes):
            if mode == "scale":
                # the game recalculates speed every frame: multiply each NEW value it writes, not our own
                cur = self.ps2.read(o, vt)
                if cur is None or cur != cur:
                    continue
                last = c.setdefault("_last", {}).get(o)
                if last is not None and abs(cur - last) <= 1e-5 * max(1.0, abs(last)):
                    continue
                # never let it run away: at most "normal top speed x factor"
                nat = c.setdefault("_nat", {})
                if not nat.get(o):
                    if abs(cur) < 1e-6:
                        continue
                    nat[o] = abs(cur)
                w = cur * float(v or 1)
                cap = nat[o] * abs(float(v or 1))
                w = max(-cap, min(cap, w))
                if vt != "float":
                    w = int(round(w))
                self.ps2.write(o, vt, w)
                c["_last"][o] = self.ps2.read(o, vt)
                continue
            if mode == "freeze":
                val = (c.get("_hold") or [None] * len(writes))[i] if v is None else v
                if val is None:
                    continue
            elif mode in ("add", "multiply"):
                cur = self.ps2.read(o, vt)
                if cur is None:
                    continue
                val = modmenu.apply_value(mode, cur, v)
            else:
                val = v
            if vt != "float":
                val = int(round(val))
            self.ps2.write(o, vt, val)

    # ======================= spawn menu =======================================
    def _spawn_id_choices(self):
        vals = [e["name"] for e in self.library if e["kind"] == "value" and e["type"] in ("u32", "u16", "byte")]
        spawnish = [n for n in vals if "id" in n.lower() or "spawn" in n.lower()]
        self.spawn_id.configure(values=spawnish + [n for n in vals if n not in spawnish])

    def _spawn_entry(self):
        return next((e for e in self.library if e["name"] == self.spawn_id.get()), None)

    def spawn_find_id(self):
        kind = self.spawn_kind.get()
        self.ask_var.set({"Vehicles": "which car am I in (id)", "Weapons": "which weapon am I holding (weapon id)",
                          "Characters": "which character skin id", "Items": "which item id"}.get(kind, "item id"))
        self.mode_var.set(MODE_CHOICES[1])
        self.nb.select(self.coach_tab)
        self.make_plan()

    def coach_to_spawn(self):
        item = self._coach_selected()
        if not item:
            return
        vt, addr = item
        kind = (self.plan or {}).get("spawn_kind") or self.spawn_kind.get()
        name = f"{kind[:-1]} ID"
        n = 2
        while any(e["name"] == name for e in self.library):
            name = f"{kind[:-1]} ID {n}"
            n += 1
        self.library.append(core.new_value_entry(name, "Spawn", addr, vt))
        self.library_changed()
        self.spawn_kind.set(kind)
        self.spawn_id.set(name)
        self.nb.tab(self.spawn_tab, state="normal")
        self.nb.select(self.spawn_tab)
        self.say(f"Saved {core.fa(addr, vt)} as '{name}'. Now scan the game's files for names, or use the ID browser.")

    def spawn_scan(self, folder):
        path = filedialog.askdirectory(title="Game folder") if folder else filedialog.askopenfilename(
            title="Disc image or game file",
            filetypes=[("Disc images / game files", "*.iso *.bin *.img *.gcm *.ide *.dat *.ini *.txt *.xml *.csv"),
                       ("All files", "*.*")])
        if not path:
            return
        self.scan_stop = False
        self.scan_lbl.configure(text="Scanning...")

        def work():
            def prog(frac, name):
                self.ui(self.scan_lbl.configure, {"text": f"Scanning {frac * 100:.0f}%  {name[-50:]}"})
            try:
                tables = spawner.scan_path(path, progress=prog, stop=lambda: self.scan_stop)
            except Exception as e:
                tables = []
                self.ui(self.say, f"Scan failed: {e}")
            self.ui(self._scan_done, tables)
        threading.Thread(target=work, daemon=True).start()

    def _scan_done(self, tables):
        self.scan_tables = tables
        self.scan_lbl.configure(text=f"Found {len(tables)} name lists." + (
            "" if tables else " Nothing readable - the files may be packed. Use the ID browser instead."))
        self._refresh_tables()

    def _refresh_tables(self):
        self.tables_tree.delete(*self.tables_tree.get_children())
        kind = self.spawn_kind.get()
        ranked = spawner.match_tables(self.scan_tables, self.spawn.get("observed", []))
        ranked.sort(key=lambda x: (x[1], x[0]["kind"] == kind), reverse=True)
        self._table_rows = {}
        for i, (t, seen) in enumerate(ranked[:200]):
            first = ", ".join(f"{a}={b}" for a, b in t["entries"][:5])
            self.tables_tree.insert("", "end", iid=str(i), values=(t["kind"], len(t["entries"]), seen or "",
                                                                  first, t["source"]))
            self._table_rows[str(i)] = t

    def spawn_use_table(self):
        sel = self.tables_tree.selection()
        if not sel:
            messagebox.showinfo(APP_TITLE, "Pick a list from the scan results.")
            return
        t = self._table_rows[sel[0]]
        if t["kind"] in spawner.KIND_WORDS and t["kind"] != self.spawn_kind.get():
            self.spawn_kind.set(t["kind"])
        kind = self.spawn_kind.get()
        self.spawn["lists"] = [x for x in self.spawn["lists"] if x.get("source") != t["source"]]
        self.spawn["lists"].append({"kind": kind, "source": t["source"], "entries": t["entries"]})
        self.save_library(self.lib_path, quiet=True)
        self.refresh_spawn_list()

    def _spawn_names(self):
        kind = self.spawn_kind.get() if hasattr(self, "spawn_kind") else "Vehicles"
        names = {}
        for lst in self.spawn.get("lists", []):
            if lst.get("kind") == kind:
                for i, n in lst["entries"]:
                    names.setdefault(int(i), (n, lst["source"]))
        for i, n in self.spawn.get("learned", {}).get(kind, {}).items():
            names[int(i)] = (n, "named by you")
        return names

    def refresh_spawn_list(self):
        if not hasattr(self, "spawn_tree"):
            return
        self.spawn_tree.delete(*self.spawn_tree.get_children())
        for i, (n, src) in sorted(self._spawn_names().items()):
            self.spawn_tree.insert("", "end", iid=str(i), values=(i, n, src))

    def _spawn_write(self, ident):
        ent = self._spawn_entry()
        if not ent:
            messagebox.showinfo(APP_TITLE, "Pick the ID value first (step 1).")
            return False
        if not self.need_attach():
            return False
        self.ps2.write(ent["addr"], ent["type"], int(ident))
        hold = float(self.spawn_hold.get() or 0)
        if hold > 0:
            self._holds.append((ent["addr"], ent["type"], int(ident), time.time() + hold))
        return True

    def spawn_selected(self):
        sel = self.spawn_tree.selection()
        if not sel:
            messagebox.showinfo(APP_TITLE, "Pick something in the spawn list.")
            return
        ident = int(sel[0])
        if self._spawn_write(ident):
            self.say(f"Spawned {self._spawn_names().get(ident, ('ID ' + str(ident),))[0]} (ID {ident}).")

    def spawn_step(self, d):
        ent = self._spawn_entry()
        if not ent or not self.need_attach():
            if not ent:
                messagebox.showinfo(APP_TITLE, "Pick the ID value first (step 1).")
            return
        cur = self.ps2.read(ent["addr"], ent["type"]) or 0
        nxt = max(0, int(cur) + d)
        if self._spawn_write(nxt):
            name = self._spawn_names().get(nxt, ("(no name yet - 'Name this ID...')",))[0]
            self.say(f"ID {nxt}: {name}. If the game shows something new, name it.")

    def spawn_name_id(self):
        ent = self._spawn_entry()
        if not ent or not self.need_attach():
            return
        cur = self.ps2.read(ent["addr"], ent["type"])
        r = ask_form(self.root, "Name this ID", [("name", f"What is ID {cur}?", "entry",
                                                  self._spawn_names().get(int(cur or 0), ("",))[0], None)])
        if not r or not r["name"]:
            return
        self.spawn.setdefault("learned", {}).setdefault(self.spawn_kind.get(), {})[str(int(cur))] = r["name"]
        self.save_library(self.lib_path, quiet=True)
        self.refresh_spawn_list()

    def spawn_to_menu(self, whole):
        ent = self._spawn_entry()
        if not ent:
            messagebox.showinfo(APP_TITLE, "Pick the ID value first (step 1).")
            return
        names = self._spawn_names()
        ids = list(names) if whole else [int(i) for i in self.spawn_tree.selection()]
        if not ids:
            messagebox.showinfo(APP_TITLE, "Pick something in the spawn list.")
            return
        group = f"Spawn: {self.spawn_kind.get()}"
        have = {(c.get("group"), c.get("value")) for c in self.cheats}
        added = 0
        for i in sorted(ids)[:300]:
            if (group, i) in have:
                continue
            self.cheats.append({"name": names.get(i, (f"ID {i}",))[0], "entry": ent["name"], "mode": "set",
                                "value": i, "hotkey": [], "group": group, "activator": None,
                                "hold": float(self.spawn_hold.get() or 0)})
            added += 1
        self.save_library(self.lib_path, quiet=True)
        self.refresh_cheat_tree()
        self.say(f"Added {added} items to the mod menu under '{group}'. Start the mod menu on the Cheats tab.")

    def _spawn_watch(self):
        """Note every ID the game uses - it tells us which name list is the right one."""
        try:
            ent = self._spawn_entry() if self.ps2.attached else None
            if ent:
                v = self.ps2.read(ent["addr"], ent["type"])
                if v is not None:
                    obs = self.spawn.setdefault("observed", [])
                    if v not in obs:
                        obs.append(int(v))
                        del obs[:-200]
                        if self.scan_tables:
                            self._refresh_tables()
                    name = self._spawn_names().get(int(v), ("?",))[0]
                    self.spawn_now_lbl.configure(text=f"now: {v} = {name}")
        finally:
            self.root.after(500, self._spawn_watch)
        self.root.after(2000, self._move_watch)

    # ======================= updates ===========================================
    def _updater(self):
        return updater.Updater(self.settings.get("update_repo", "Predatuh/GameValueTracker"),
                               self.settings.get("update_token", ""), app_dir=APP_DIR)

    def update_dialog(self):
        r = ask_form(self.root, "Updates", [
            ("repo", "GitHub repo (owner/name)", "entry", self.settings.get("update_repo", "Predatuh/GameValueTracker"), None),
            ("token", "GitHub token (only for a private repo)", "entry", self.settings.get("update_token", ""), None),
            ("auto", "Check when the tracker starts", "combo", "yes" if self.settings.get("update_auto", True) else "no",
             ["yes", "no"]),
        ])
        if not r:
            return
        self.settings["update_repo"] = r.get("repo", "").strip()
        self.settings["update_token"] = r.get("token", "").strip()
        self.settings["update_auto"] = r.get("auto", "yes") != "no"
        self._save_settings(quiet=True)
        self.update_check(quiet=False)

    def update_check(self, quiet=True):
        if quiet and not self.settings.get("update_auto", True):
            return
        if getattr(sys, "frozen", False):
            if not quiet:
                messagebox.showinfo(APP_TITLE, "The .exe can't update itself. Run GameValueTracker.pyw instead "
                                    "(same app) and it updates over the air.")
            return
        up = self._updater()
        if not up.ready:
            if not quiet:
                messagebox.showinfo(APP_TITLE, "Set the GitHub repo first (Updates...).")
            return

        def work():
            try:
                avail, remote, local = up.check()
            except Exception as e:
                if not quiet:
                    self.ui(messagebox.showwarning, APP_TITLE, f"Couldn't check for updates: {e}")
                return
            if avail:
                self.ui(self._update_available, remote, local)
            elif not quiet:
                self.ui(self.say, f"You're up to date (v{local}).")
        threading.Thread(target=work, daemon=True).start()

    def _update_available(self, remote, local):
        self._update_remote = remote
        self.update_lbl.configure(text=f"Update ready: v{remote}  (you have v{local})")
        self.update_bar.pack(fill="x", after=self.conn_label)

    def update_whats_new(self):
        up = self._updater()

        def work():
            text = up.changelog() or "No change list in the repo."
            self.ui(messagebox.showinfo, APP_TITLE, text[:1500])
        threading.Thread(target=work, daemon=True).start()

    def update_now(self):
        up = self._updater()
        self.update_lbl.configure(text="Downloading the update...")
        if self.library or self.cheats:
            self.save_library(self.lib_path, quiet=True)
        self._save_settings(quiet=True)

        def work():
            try:
                changed, remote = up.update()
            except Exception as e:
                self.ui(self.update_lbl.configure, {"text": f"Update failed: {str(e)[:120]}"})
                return
            self.ui(self._update_done, changed, remote)
        threading.Thread(target=work, daemon=True).start()

    def _update_done(self, changed, remote):
        self.update_lbl.configure(text=f"Updated to v{remote} ({len(changed)} files). Restarting...")
        self.root.update_idletasks()
        if getattr(self, "_no_restart", False):
            return
        self.root.after(800, updater.restart)

    # ======================= background loops ===================================
    def ui(self, fn, *args):
        """Run fn(*args) on the window's thread. Safe to call from any thread."""
        self._ui_queue.put((fn, args))

    def _ui_pump(self):
        try:
            while True:
                fn, args = self._ui_queue.get_nowait()
                try:
                    fn(*args)
                except Exception as e:  # keep the app alive
                    self.status.set(f"Error: {e}")
        except queue.Empty:
            pass
        self.root.after(50, self._ui_pump)

    def _start_loops(self):
        self.root.after(50, self._ui_pump)
        self.root.after(400, self._refresh_loop)
        self.root.after(100, self._freeze_loop)
        self.root.after(4000, self._game_watch)
        self.root.after(500, self._spawn_watch)
        threading.Thread(target=self._live_thread, daemon=True).start()
        if core.IS_WIN:
            threading.Thread(target=self._hotkey_thread, daemon=True).start()

    def _refresh_loop(self):
        try:
            if self.nb.select() == str(self.lib_tab):
                self.refresh_library_values()
            elif self.nb.select() == str(self.coach_tab):
                self.refresh_coach_values()
        finally:
            self.root.after(400, self._refresh_loop)

    def _freeze_loop(self):
        try:
            if self.ps2.attached:
                for e in self.library:
                    if e.get("kind") == "value" and e.get("freeze") and e.get("freeze_value") is not None:
                        self.ps2.write(e["addr"], e["type"], e["freeze_value"])
                for (a, vt), v in list(self.sc_frozen.items()):
                    self.ps2.write(a, vt, v)
                now = time.time()
                self._holds = [h for h in self._holds if h[3] > now]
                for o, vt, v, _ in self._holds:
                    self.ps2.write(o, vt, v)
        finally:
            self.root.after(100, self._freeze_loop)

    def _hotkey_thread(self):
        import ctypes
        user32 = ctypes.windll.user32
        down = {vk: False for vk in HOTKEYS}
        while True:
            for vk, (_, action) in HOTKEYS.items():
                pressed = bool(user32.GetAsyncKeyState(vk) & 0x8000)
                if pressed and not down[vk]:
                    self.ui(self._hotkey, action)
                down[vk] = pressed
            time.sleep(0.03)

    def _hotkey(self, action):
        if not self.ps2.attached:
            return
        if action == "boost_toggle":
            self.boost_toggle()
        elif action == "rec_toggle":
            self.rec_toggle()
        elif action in ("zone_strike", "zone_ball"):
            if self.predicting:
                self.zone_label(action == "zone_strike")
            else:
                return
        elif action in ("rec_mark", "zone_ball") and getattr(self, "pending_answer", None):
            yes_cb, no_cb = self.pending_answer
            self.pending_answer = None
            (yes_cb if action == "rec_mark" else no_cb)()
        elif action == "rec_mark":
            if self.pulsing:
                self.pulse_mark()
            elif self.predicting:
                self.predict_mark()
            elif self.hunting:
                self.hunt_mark()
            elif self.coach_wait == "key":
                self.coach_key_done()
            elif self.recording:
                self.rec_mark()
            else:
                return
        elif action == "unknown":
            self.first_scan("unknown")
        else:
            if not self.scanner.active:
                return
            self.next_scan(action)
        try:
            import winsound
            winsound.MessageBeep()
        except Exception:
            pass


class MenuOverlay(tk.Toplevel):
    """The in-game mod menu drawn on top of the game."""

    BG, FG, SEL, ON = "#0b1220", "#e5e7eb", "#2563eb", "#22c55e"

    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        try:
            self.attributes("-alpha", 0.92)
        except tk.TclError:
            pass
        self.configure(background=self.BG, padx=10, pady=8)
        pos = app.settings.get("menu_pos") or [40, 260]
        self.geometry(f"+{pos[0]}+{pos[1]}")
        self.title_lbl = tk.Label(self, text="MOD MENU", fg="#93c5fd", bg=self.BG, font=("Segoe UI", 12, "bold"))
        self.title_lbl.pack(anchor="w")
        self.body = tk.Frame(self, background=self.BG)
        self.body.pack(fill="x")
        self.hint = tk.Label(self, text="", fg="#6b7280", bg=self.BG, font=("Segoe UI", 8))
        self.hint.pack(anchor="w", pady=(4, 0))
        self.toast_win = None
        for w in (self, self.title_lbl):
            w.bind("<ButtonPress-1>", self._start_drag)
            w.bind("<B1-Motion>", self._drag)
        self.withdraw()

    def show(self):
        self.deiconify()
        self.lift()
        self.attributes("-topmost", True)
        self.draw(self.app.menu)

    def hide(self):
        self.withdraw()

    def draw(self, engine):
        for w in self.body.winfo_children():
            w.destroy()
        self.title_lbl.configure(text=engine.title())
        rows = engine.rows()
        top = max(0, min(engine.cursor - 7, len(rows) - 15))
        for i, (label, c) in enumerate(rows[top:top + 15], start=top):
            on = c is not None and c.get("mode", "freeze") == "freeze" and c.get("on")
            text = ("> " if i == engine.cursor else "  ") + label + ("   [ON]" if on else "")
            tk.Label(self.body, text=text, anchor="w", width=34, font=("Segoe UI", 11),
                     fg="white" if i == engine.cursor else (self.ON if on else self.FG),
                     bg=self.SEL if i == engine.cursor else self.BG).pack(fill="x")
        if not rows:
            tk.Label(self.body, text="(empty)", fg=self.FG, bg=self.BG).pack()
        k = engine.keys
        self.hint.configure(text=f"{modmenu.combo_text(k['up'])}/{modmenu.combo_text(k['down'])} move   "
                                 f"{modmenu.combo_text(k['select'])} select   {modmenu.combo_text(k['back'])} back   "
                                 f"{modmenu.combo_text(k['open'])} close")

    def toast(self, text):
        if self.toast_win is None or not self.toast_win.winfo_exists():
            self.toast_win = tk.Toplevel(self.app.root)
            self.toast_win.overrideredirect(True)
            self.toast_win.attributes("-topmost", True)
            self.toast_lbl = tk.Label(self.toast_win, text="", fg="black", bg=self.ON, padx=12, pady=6,
                                      font=("Segoe UI", 11, "bold"))
            self.toast_lbl.pack()
        x, y = self.winfo_x(), max(0, self.winfo_y() - 50)
        self.toast_win.geometry(f"+{x}+{y}")
        self.toast_lbl.configure(text=text)
        self.toast_win.deiconify()
        self.toast_win.lift()
        tid = object()
        self._toast_id = tid
        self.after(1800, lambda: self._toast_id is tid and self.toast_win.withdraw())

    def _start_drag(self, e):
        self._dx, self._dy = e.x_root - self.winfo_x(), e.y_root - self.winfo_y()

    def _drag(self, e):
        self.geometry(f"+{e.x_root - self._dx}+{e.y_root - self._dy}")
        self.app.settings["menu_pos"] = [self.winfo_x(), self.winfo_y()]


class Overlay(tk.Toplevel):
    """Small always-on-top instruction box that sits over the game."""

    BG, FG, ACC = "#111827", "#f9fafb", "#22c55e"

    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        try:
            self.attributes("-alpha", 0.93)
        except tk.TclError:
            pass
        self.configure(background=self.BG, padx=14, pady=10)
        pos = app.settings.get("overlay_pos") or [40, 40]
        self.geometry(f"460x190+{pos[0]}+{pos[1]}")

        bar = tk.Frame(self, background=self.BG)
        bar.pack(fill="x")
        self.title_lbl = tk.Label(bar, text="AI Coach", fg="#9ca3af", bg=self.BG, font=("Segoe UI", 9))
        self.title_lbl.pack(side="left")
        tk.Button(bar, text="×", command=self.close, bg=self.BG, fg="#9ca3af", bd=0,
                  activebackground=self.BG).pack(side="right")
        self.msg = tk.Label(self, text="", fg=self.FG, bg=self.BG, font=("Segoe UI", 13, "bold"),
                            wraplength=430, justify="left", anchor="w")
        self.msg.pack(fill="x", pady=(4, 6))
        self.sub = tk.Label(self, text="", fg="#9ca3af", bg=self.BG, font=("Segoe UI", 9),
                            wraplength=430, justify="left", anchor="w")
        self.sub.pack(fill="x")
        self.flash_lbl = tk.Label(self, text="", fg=self.ACC, bg=self.BG, font=("Segoe UI", 9, "bold"))
        self.flash_lbl.pack(fill="x")

        self.row = tk.Frame(self, background=self.BG)
        self.row.pack(fill="x", pady=(6, 0))
        self.num = tk.Entry(self.row, width=10, font=("Segoe UI", 12))
        self.num.bind("<Return>", lambda e: self._send_number())
        self.ok_btn = tk.Button(self.row, text="OK", command=self._send_number, bg=self.ACC, fg="black", bd=0,
                                padx=10)
        self.done_btn = tk.Button(self.row, text="Done  ]", command=app.coach_key_done, bg=self.ACC,
                                  fg="black", bd=0, padx=10)
        self.skip_btn = tk.Button(self.row, text="Skip", command=app.coach_skip, bg="#374151",
                                  fg=self.FG, bd=0, padx=8)
        self.stop_btn = tk.Button(self.row, text="Stop", command=app.coach_stop, bg="#7f1d1d",
                                  fg=self.FG, bd=0, padx=8)
        self.yes_btn = tk.Button(self.row, text="YES  ]", bg=self.ACC, fg="black", bd=0, padx=14,
                                 font=("Segoe UI", 10, "bold"))
        self.no_btn = tk.Button(self.row, text="NO  '", bg="#f97316", fg="black", bd=0, padx=14,
                                font=("Segoe UI", 10, "bold"))
        for w in (self, self.msg, self.sub, self.title_lbl, bar):
            w.bind("<ButtonPress-1>", self._start_drag)
            w.bind("<B1-Motion>", self._drag)

    def set(self, text, sub="", ask=False, done=False, close=False):
        if text != self.msg.cget("text"):
            try:
                self.lift()
                self.attributes("-topmost", True)
            except tk.TclError:
                pass
        self.msg.configure(text=text)
        self.sub.configure(text=sub)
        for w in (self.num, self.ok_btn, self.done_btn, self.skip_btn, self.stop_btn, self.yes_btn, self.no_btn):
            w.pack_forget()
        for w in getattr(self, "_choice_btns", []):
            w.destroy()
        self._choice_btns = []
        if ask:
            self.num.delete(0, "end")
            self.num.pack(side="left")
            self.ok_btn.pack(side="left", padx=6)
            self.after(50, self._grab_focus)
        if done:
            self.done_btn.pack(side="left")
        if not close:
            self.skip_btn.pack(side="right")
        self.stop_btn.pack(side="right", padx=4)
        if close:
            self.stop_btn.configure(text="Close", command=self.close)
        else:
            self.stop_btn.configure(text="Stop", command=self.app.coach_stop)
        self._fit()

    def _fit(self, width=None):
        """Grow / shrink to fit the text and every button - nothing gets cut off."""
        if getattr(self, "_plate_on", False):
            return
        try:
            w = width or max(460, getattr(self, "_width", 460))
            self._width = w
            for lbl in (self.msg, self.sub):
                lbl.configure(wraplength=w - 30)
            self.update_idletasks()
            need_w = max(w, self.row.winfo_reqwidth() + 30)
            if need_w != w:
                self._width = need_w
                for lbl in (self.msg, self.sub):
                    lbl.configure(wraplength=need_w - 30)
                self.update_idletasks()
            h = max(150, self.winfo_reqheight() + 6)
            self.geometry(f"{self._width}x{h}+{self.winfo_x()}+{self.winfo_y()}")
        except tk.TclError:
            pass

    def choices(self, text, sub, buttons):
        """buttons: [(label, callback, colour)]"""
        self.set(text, sub, close=True)
        for w in getattr(self, "_choice_btns", []):
            w.destroy()
        self._choice_btns = []
        for label, cb, col in buttons:
            b = tk.Button(self.row, text=label, command=cb, bg=col, fg="black", bd=0, padx=8,
                          font=("Segoe UI", 9, "bold"))
            b.pack(side="left", padx=(0, 5))
            self._choice_btns.append(b)
        self._width = 460
        self._fit()

    def ask_yes_no(self, text, sub, on_yes, on_no):
        self.set(text, sub, close=True)
        self.yes_btn.configure(command=on_yes)
        self.no_btn.configure(command=on_no)
        self.yes_btn.pack(side="left")
        self.no_btn.pack(side="left", padx=6)
        self._fit()

    def show_plate(self, on):
        if on == getattr(self, "_plate_on", False):
            return
        self._plate_on = on
        if on:
            if not hasattr(self, "plate"):
                self.plate = tk.Canvas(self, width=300, height=300, bg=self.BG, highlightthickness=0)
            self.msg.pack_forget(); self.sub.pack_forget(); self.flash_lbl.pack_forget(); self.row.pack_forget()
            self.plate.pack()
            self.flash_lbl.pack(fill="x")
            self.row.pack(fill="x", pady=(4, 0))
            for w in (self.num, self.ok_btn, self.done_btn, self.skip_btn):
                w.pack_forget()
            self.stop_btn.pack(side="right")
            x, y = self.winfo_x(), self.winfo_y()
            self.geometry(f"330x390+{x}+{y}")
        else:
            if hasattr(self, "plate"):
                self.plate.pack_forget()
            self.flash_lbl.pack_forget(); self.row.pack_forget()
            self.msg.pack(fill="x", pady=(4, 6)); self.sub.pack(fill="x")
            self.flash_lbl.pack(fill="x"); self.row.pack(fill="x", pady=(6, 0))
            self._fit(460)

    def draw_plate(self, pred, zone, history, label, info, flip_h=False, flip_v=False, new=False):
        c = self.plate
        c.delete("all")
        W = H = 300
        pts = [(o["h"], o["v"]) for o in history]
        if pred:
            pts.append((pred["h"], pred["v"]))
        if zone:
            pts += [(zone[0], zone[2]), (zone[1], zone[3])]
        if not pts:
            c.create_text(W / 2, H / 2, text="waiting for the next pitch...", fill="#9ca3af")
            return
        hs, vs = [p[0] for p in pts], [p[1] for p in pts]
        h0, h1, v0, v1 = min(hs), max(hs), min(vs), max(vs)
        sh = max(h1 - h0, 1e-6) * 0.25; sv = max(v1 - v0, 1e-6) * 0.25
        h0, h1, v0, v1 = h0 - sh, h1 + sh, v0 - sv, v1 + sv
        span = max(h1 - h0, v1 - v0)
        hc, vc = (h0 + h1) / 2, (v0 + v1) / 2

        def xy(h, v):
            x = (h - hc) / span * (W - 40) + W / 2
            y = H / 2 - (v - vc) / span * (H - 70)
            if flip_h:
                x = W - x
            if flip_v:
                y = H - y
            return x, y

        if zone:
            xa, ya = xy(zone[0], zone[2]); xb, yb = xy(zone[1], zone[3])
            c.create_rectangle(xa, ya, xb, yb, outline="#e5e7eb", width=2)
            for i in (1, 2):   # 3x3 grid
                xm = xa + (xb - xa) * i / 3; ym = ya + (yb - ya) * i / 3
                c.create_line(xm, ya, xm, yb, fill="#374151"); c.create_line(xa, ym, xb, ym, fill="#374151")
        for h, v in [(o["h"], o["v"]) for o in history]:
            x, y = xy(h, v)
            c.create_oval(x - 3, y - 3, x + 3, y + 3, fill="#4b5563", outline="")
        if pred:
            x, y = xy(pred["h"], pred["v"])
            col = "#22c55e" if label == "STRIKE" else "#f97316" if label == "BALL" else "#60a5fa"
            r = 14 if new else 11
            c.create_oval(x - r, y - r, x + r, y + r, fill=col, outline="white", width=2)
        c.create_text(W / 2, 18, text=label or "TARGET", fill="#22c55e" if label == "STRIKE" else "#f97316",
                      font=("Segoe UI", 22, "bold"))
        c.create_text(W / 2, H - 14, text=info, fill="#9ca3af", font=("Segoe UI", 8), width=W - 10)

    def _grab_focus(self):
        try:
            self.focus_force()
            self.num.focus_set()
        except tk.TclError:
            pass

    def flash(self, text):
        self.flash_lbl.configure(text=text)
        self.after(2500, lambda: self.flash_lbl.configure(text=""))

    def _send_number(self):
        self.app.coach_number(self.num.get())

    def _start_drag(self, e):
        self._dx, self._dy = e.x_root - self.winfo_x(), e.y_root - self.winfo_y()

    def _drag(self, e):
        self.geometry(f"+{e.x_root - self._dx}+{e.y_root - self._dy}")

    def close(self):
        self.app._save_settings(quiet=True)
        self.app.coach_stop(quiet=True)
        self.withdraw()


HELP_TEXT = """PS2 VALUE TRACKER - QUICK GUIDE

SETUP
1. Start your emulator and boot the game - or start a PC game.
   Works with: PCSX2 (PS2), RPCS3 (PS3), Dolphin (GameCube/Wii), PPSSPP (PSP), DuckStation (PS1),
   and any offline PC game or program. Online games with anti-cheat are blocked.
2. Pick it in the "Game:" list at the top (emulators are listed first). "System" fills in by
   itself; change it only if it guessed wrong. For other emulators (Cemu, Xenia, Project64...)
   pick "Other emulator, big-endian" or "PC game / any program".
3. Click "Attach". The bar shows what was found.
Addresses are shown the way that system names them: 0032A4C0 for PS2, 8034A2C0 for
GameCube/Wii, 0x08xxxxxx for PSP, gta_sa.exe+76F3B8 for PC games (those stay the same between
runs; plain PC heap addresses change every time the game starts).
Each game gets set up for itself: the tool reads the game's name from the emulator (PS3, GameCube/
Wii and PSP also give the disc ID), picks the game type (sports, open world, racing...) and only
shows the tabs that fit - Power boost and Ratings finder for sports, Spawn menu for open-world /
racing / shooters / RPGs. Wrong guess? Change "Game type" at the top; it remembers per game.
Every game has its own library, cheats and spawn lists (saved in the "libraries" folder). Switch
games in the emulator and the tool switches with you.
Tip: for PC games use windowed or borderless mode so the overlay can sit on top.

CHEATS & MOD MENU  - "Cheats & mod menu" tab
Type what you want: "infinite ammo on L1+R1", "money +10000 on L2+R2", "double car speed on F3",
"health 999", "set wanted level to 0 with R3". The value has to be in the Library first.
  keep it at  = stays on until you switch it off (no number = keeps whatever it is right now)
  set / add / multiply = happens once each time you press it
Click "Start mod menu". Then in the game:
  L3 + R1 (or Insert)  opens the menu.  D-pad up/down (Numpad 8/2) moves, Cross / A (Numpad 5)
  switches a cheat on/off or spawns, Circle / B (Numpad 0) goes back / closes.
  Each cheat's own hotkey works any time. "Set hotkey..." captures a combo: just hold it.
Controller: Xbox-style pads work directly (PS4/PS5 pads through Steam or DS4Windows). For other
pads, find the controller value in the game's memory and use "Learn game pad...".
"Export cheats..." also writes the right code format for the system: .pnach (PCSX2), Gecko codes
(Dolphin), CWCheat (PPSSPP), GameShark (DuckStation), or a Cheat Engine table (PC games, RPCS3).
Codes can only hold a value, so add/multiply and spawn items stay in the live mod menu.

SPAWN MENU  - "Spawn menu" tab (vehicles, weapons, items)
Games keep the ID of the car you're in, the weapon you hold, the item in a slot. Change that ID and
you get a different car / weapon / item.
1. "Find it with the AI Coach": sit in a car (or hold a weapon), switch to a different one when it
   tells you, press ]. Pick the result and click "Use as spawn ID".
2. Names: "Scan game folder..." or "Scan disc image / file..." reads the game's files and lists every
   ID -> name table it finds. The list that contains the IDs you've actually used rises to the top.
   Pick it and click "Use this list". No names (packed files)? Use the ID browser: Next ID / Prev ID
   and "Name this ID..." for whatever shows up.
3. "Spawn selected now", or "Add to mod menu" to spawn from the controller. "keep it for N s" holds
   the ID for a moment in case the game changes it back. Many games only swap the model when you get
   in / re-equip, so get out and back in (or switch weapon) after spawning if nothing changes.

AI COACH  - "AI Coach" tab  (start here)
1. Type what you're looking for, like you'd tell a friend: "ammo, I have 40", "my money",
   (the plan starts with "I UNDERSTOOD: ..." - if that's wrong, change "I want to:" and re-plan)
   "health, I'm at full", "car speed", "how high I jump", "game clock", "ball speed after I hit it".
2. Click "Make a plan" to see the steps, then Start. A small box appears on top of the game and
   tells you what to do ("Speed up for 5 seconds", "Take some damage, press ] when done",
   "Type your new ammo number"). The tool scans memory at the right moments by itself.
3. When it says "Found it!", the answer is in the list. Save it to the library, test it, or send it
   to Power boost.
Ball games: "ball speed after I hit it" runs the fully automatic hunt. Just play and press ] when
the ball is hit (or pick a saved ball value under "auto-detect hits" and don't press anything).
AI BRAIN (optional): pick Claude, Gemini (Google AI Studio key) or any OpenAI-compatible service
(OpenAI, OpenRouter, Groq, DeepSeek, xAI, Mistral, or Ollama / LM Studio running on this PC - no key
needed for those, just pick the URL). Paste the key, click "List models" and pick one, then "Test".
The brain is told which game you're playing so its steps fit that game. Without a key everything
still works offline with the built-in brain.

SPEED, JUMPS AND OTHER "ONE ACTION" VALUES
"run speed", "car speed", "how high I jump": you press ] and do it ONCE (run 2 s / jump / floor it),
then stop. The tool keeps values that rose and came back the same way every time. 4-6 tries.
When it stops, or any search ends with too many results, you get choices:
  Keep narrowing  - more rounds from where you are (Start also continues; "Start over" = new search)
  Test with me    - it holds half of the candidates still; try to move; say YES if you're stuck /
                    slower. It halves again each time: ~9 questions for 500 values.
                    Answer with the buttons or the keys:  ] = YES   ' = NO  (works in the game).
Searches stop by themselves when another round wouldn't help (what's left all changes together -
the real value and its copies). Then the tool tests them itself, loners first, and stops as soon
as it finds the one the game really uses - usually 2-3 actions from you in total.
  Speed hack test - same, but it multiplies them x3; YES if you're super fast.
Found it? "Speed hack ON/OFF" makes you x3 fast right away (capped at 3x your normal top speed) and
adds it to Cheats & mod menu, where you can give it a hotkey or change the multiplier.
The overlay is draggable. If the game is in exclusive fullscreen it may hide the overlay -
use borderless/windowed mode.

PREDICT WHERE THE CPU WILL THROW (pitch / shot / pass)  - AI Coach, "Predict where it will go"
Type something like "where is the pitcher going to throw it" (or pick the mode in "I want to:").
The game decides the spot BEFORE the pitcher throws. The tool hunts for that decision in memory -
it does not guess from where balls landed.
1. Press ] the moment the pitcher RELEASES the ball. Swing or take - EVERY pitch counts, hit or
   not. After ~3 pitches it has found the ball (the thing that flies toward you after release).
2. Keep pressing ] at each release. For every pitch it notes where the ball crossed the plate
   (the instant it stops coming at you - caught OR hit) and what memory looked like during the
   wind-up. Then it searches for a value that was already set during the wind-up and decides the
   spot, two ways:
     coordinates - a number that moves with the location (found in ~6 pitches)
     zone number - a number like 0-8 where the same number always means the same spot. It needs
                   a few repeats of each zone, so usually 8-12 pitches. It builds the zone table.
3. The overlay turns into a strike zone. During the wind-up a dot shows where the pitch is going:
   green = STRIKE, orange = BALL. "Zone #4 - never seen it yet" means that zone hasn't come up
   during learning; it learns it on that pitch.
4. Teach it the zone: after the umpire's call press ; for a strike or ' for a ball. Until then the
   zone is an estimate (adjust "Strike zone size %"). Flip left/right or up/down there too if the
   picture is mirrored compared to your TV.
"Export predictor findings" (AI Coach tab) saves a file with every pitch, every value that was set
before the wind-up, and what it decided. If it can't find the target, send that file to Claude.

DEEP TEST (when every quick test says COPY)  - runs by itself after a ball hunt
Some games rebuild the ball's speed every frame from a hidden value (like "hit power"), so
changing the speed you can see does nothing. The deep test changes hundreds of values at once
right after contact and watches if the ball leaves its normal path. If it does, it splits that
group in half and tries again on the next hit, until one value is left (about 10-15 hits for a
few thousand values). Everything is put back after every test. When it finds it, it fills Power
boost and picks the right trigger for you.

CODE PATCH (when even the deep test finds nothing)  - Cheat/menu maker, "Add code patch..."
Then the game's CODE caps or resets the value (e.g. "if power > 100 then power = 100").
Instead of changing a value you change that instruction:
1. In PCSX2: Debug > Open Debugger. In the Memory view go to the value's address (e.g. the ball
   speed), right-click it > "Add breakpoint (write)". Hit the ball - the game pauses on the
   instruction that writes it. Note the instruction's address (left column in the disassembly).
2. Cheat/menu maker > "Add code patch...", paste that address, keep 00000000 (NOP = skip the
   instruction), Export. The pnach makes PCSX2 patch the code itself, so it sticks (writing code
   live from this tool doesn't, because PCSX2 caches compiled code).
3. Test it. If the game crashes or acts weird, you NOP'd the wrong line - remove that patch and try
   the next write instruction instead. Keep one change at a time.

NOT SURE IF IT'S A FLOAT OR A BYTE?
Scanner: pick "any type (all 4)" - byte, u16, u32 and float are scanned side by side. Results show
the type next to the address. Select some and:
  Freeze / unfreeze  - holds them at their current value while you play (test which one is real)
  Set value...       - type a number into them (double-click a row does this too)
  Add to library (name it later) - goes in as "Unnamed 1 (float)" under Unsorted; rename it when
                       you know it's the right one. AI Coach results have the same two buttons.

VALUES THAT MOVE AROUND (new address every time the game starts / a level loads)
Every value you save remembers what surrounds it in memory (its "fingerprint"). When you attach, the
tool checks each saved value and follows the ones that moved - the status bar says what moved.
For values that move WHILE you play (respawn, new level), select it in the Library and click
"Moves around: track it": the tool also finds pointers to it and re-checks it every 2 seconds.
Each time it finds the value again it keeps only the pointer paths that still lead there, so it gets
more reliable every session. Mod menu cheats use the library, so they keep working.
"Re-find moved values" runs the check on demand. "LOST" = re-find it with the AI Coach.

AUTO-TEST (finds the value that really controls the game)
Games keep copies of values (display/HUD/render copies) that move exactly like the real one but
do nothing when you change them. After the coach narrows things down it tests every result by
itself: it changes each one for half a second and watches the game.
  CONTROLS IT = the game kept the change and other values reacted -> use this one
  COPY        = the game overwrote it instantly -> changing it does nothing
  If it isn't sure (the game kept the change but nothing else reacted), it puts a number like 77 in
  and asks you YES / NO: "does the game show 77 now?". NO -> it tests the values right next to it
  (all types: the real one is often a float twin or sits in the same struct) until one works.
Counters (ammo, money, health) are put back afterwards. For ball hunts the testing happens
between hits - keep playing - and the real ball speeds are filled into Power boost for you.
Power boost also warns you if the game overwrites a boost (you picked a copy).

FIND PLAYER RATINGS (speed, kick power, etc.)  - "Ratings finder" tab
The exact method works almost every time:
1. In the game go to Edit Player (Rosters → Edit Player) and pick a player.
2. Type the rating name (e.g. SPD) and its value now, click "1. Snapshot before".
3. Change that rating in the game by a point or two, confirm it, type the new value, click "2. Find it".
   If more than one address is listed, change it again and repeat until one is left.
4. Click "Use as Player 1". Do the same with the SAME rating on a different player → "Use as Player 2".
5. Type both players' ratings (as they are now) in Step 2 and click "Find roster table".
6. Check the preview of the first 5 players, then "Save table to library".
Now every player's SPD/KPW/etc. is labelled and editable in the Library tab.
"Quick auto search" tries the same thing from the ratings alone with no edits. It's faster when it
works but can fail where memory is busy.

TRACK LIVE VALUES (kick meter, ball speed, stamina, clock...)  - "Scanner" tab
Use the hotkeys while you play:
  F5  start a new "unknown value" scan (do this right before the thing happens)
  F6  keep values that changed        F7 keep values that did not change
  F8  keep values that went up        F9 keep values that went down
Example (kick meter): F5 while the meter is empty, start the kick, press F8 while it fills,
let it reset, press F9. Repeat F7 while nothing happens. A handful of results will be left.
Pick the right one (watch it change), double-click → name it and choose a category.
Tip: game values like speed are often "float"; meters/counters are often "u32". Try a few types.

RECORDER (AUTO-PINPOINT)  - "Recorder" tab
"What you'll do" lists events that fit the game: shoot twice then reload (ammo), take damage then
heal (health), spend / earn money, die, jump (height), run then stop (speed), go to lower ground
(elevation), switch weapon/car (ID)... Start recording, do what the "Next:" line says and press ]
each time - it cycles through the steps for you. It picks the value that followed every step.
For ball games, "Ball is hit" works like this:
When you're down to a handful of candidates and can't tell which is the ball:
1. Scanner tab: select the candidates (or leave nothing selected for all) → Recorder tab →
   "+ Scanner results".
2. Press [ in game to start recording. Play a few at-bats/kicks and tap ] the instant the ball
   is hit each time. Press [ again to stop.
3. The tool ranks every candidate: ball height (arcs up then down), vertical speed (jumps then
   falls steadily), launch/forward speed (jumps then holds or slows), or noise. The best guess is
   highlighted green and graphed with your hit marks as red lines.
4. Found the height? Select it and click "+ Neighbours of selected", then record again - the
   speed values usually sit right next to the position values.

POWER BOOST  - "Power boost" tab
Multiplies the ball's velocity the instant it's hit (x3 = hits fly about 3x faster).
1. Put the ball's velocity value(s) in the boxes (forward speed is the important one).
2. Set "Multiply by", click Start boost (or press the backslash key in game). Leave the tool open.
Not sure an address is the velocity? Pause the game mid-flight, put it in box 1, click
"Boost now (test)", unpause. Shoots off faster = velocity. Teleports = position.

LIBRARY
Everything you find is grouped by category, shows live values, and can be edited or frozen.
For roster tables use "Show player #" to look at any player and "Set field for ALL players".

CHEAT / MENU MAKER
Add cheats from library values (e.g. "All players 99 speed", "Max kick power").
Optional: give a cheat a button activator so it only applies while you hold a combo.
  To find the controller value: Scanner tab, type u16, press F5 while holding no buttons.
  Hold your combo on the controller and press F6. Let go and press F6 again. Press F7 a few times
  while not touching anything. The value left is the controller. Save it in category "Controller".
Export: PCSX2 gets <CRC>.pnach (enable it in the game's Properties → Cheats). Other systems get
their own code format with instructions for where to paste it.

NOTES
- Everything you do here changes memory only. Save your game in NCAA to keep roster edits,
  or use cheats to re-apply them every time.
- Emulator addresses (PS2 00000000-01FFFFFF etc.) stay the same between sessions for
  most static data. Live values (like the kick meter) may move between games/plays; if one stops
  working, re-find it.
"""


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
