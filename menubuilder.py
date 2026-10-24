"""
menubuilder.py - "build me a mod menu": one sentence -> a list of cheats -> the tool finds each value
with you (AI Coach), makes the cheat and puts it in the in-game mod menu.

  plan_menu(text, brain)   the AI (or the built-in brain) splits the sentence into menu items
  MenuBuild                walks through the items one by one (pure logic - the GUI drives it)
"""
import json
import re

import coach as coachlib
import modmenu

KINDS = ("value", "speed", "topspeed", "jump", "spawn")
MODES = ("freeze", "scale", "set", "add", "multiply")

# words that mean "this value" when the sentence doesn't name it directly
ALIASES = [
    (("god mode", "invincible", "invincibility", "never die", "can't die", "cant die", "no damage"),
     "health", "Health"),
    (("one hit kill", "one-hit kill", "1 hit kill"), "enemy health", "Health"),
    (("never reload", "no reload"), "ammo", "Weapons"),
]
FILLER = r"^(?:please\s+)?(?:(?:make|build|give|create)\s+(?:me\s+)?(?:a\s+)?(?:mod\s+)?(?:menu|cheats?)" \
         r"\s*(?:with|that has|for)?\s*:?\s*|i\s+want\s+|give\s+me\s+|add\s+|with\s+)"


def _split(text):
    """'infinite ammo on L1 + R1, god mode and super speed' -> three parts (keeps 'L1 and R1' together)."""
    parts = [p.strip(" .!") for p in re.split(r"\s*(?:,|;|\n|&|\band also\b|\balso\b|\bplus\b|\band\b)\s*",
                                               text.strip(), flags=re.I)]
    out = []
    for p in parts:
        if not p:
            continue
        try:
            only_buttons = bool(modmenu.parse_combo(p)) and out
        except ValueError:
            only_buttons = False
        if only_buttons:
            out[-1] += " + " + p              # "on L1 and R1" was split in two
        else:
            out.append(p)
    return out


def _category(word):
    for key, (words, cat, *_rest) in coachlib.COUNTERS.items():
        if word in words or word == key:
            return cat
    for key, (words, cat, *_rest) in coachlib.BARS.items():
        if word in words or word == key:
            return cat
    return "Cheats"


def item_from_text(part):
    """One menu item from a few words ('infinite ammo on L1+R1'). Returns a dict (see validate_item)."""
    hotkey, t = modmenu.split_hotkey(part)
    t = re.sub(FILLER, " ", t.strip(), flags=re.I)
    t = " " + t.strip() + " "
    name = modmenu.pretty_name(re.sub(FILLER, "", part.strip(), flags=re.I), part)
    find, group, kind = None, None, "value"
    for words, what, cat in ALIASES:
        if any(w in t for w in words):
            find, group = what, cat
            break
    if find is None and re.search(r"\bspawn", t):
        k = coachlib.id_kind(t)
        return validate_item({"name": name, "find": {"Vehicles": "which car am I in (id)",
                                                     "Weapons": "which weapon am I holding (weapon id)",
                                                     "Characters": "which character skin id"}.get(k, "which item id"),
                              "kind": "spawn", "mode": "set", "group": "Spawn " + k, "hotkey": hotkey,
                              "spawn_kind": k})
    if find is None:
        if re.search(r"\b(top|max|maximum)\s+speed\b", t):
            kind = "topspeed"
        elif coachlib.pulse_kind(t) == "jump" or re.search(r"\b(super|high|moon|big)\s*jump", t):
            kind = "jump"
        elif coachlib._has(t, coachlib.SPEED_WORDS) or re.search(r"\b(fast|faster|speed ?hack)\b", t):
            kind = "speed"
        if kind != "value":
            veh = any(w in t for w in (" car", "vehicle", "drive", "driving", "bike", "kart", "truck", "boat"))
            find = "jump height" if kind == "jump" else ("car speed" if veh else "run speed")
            group = "Vehicle" if veh else "Movement"
    if find is None:
        for table in (coachlib.COUNTERS, coachlib.BARS):
            for key, (words, cat, *_rest) in table.items():
                w = coachlib._has(t, words)
                if w:
                    find, group = w, cat
                    break
            if find:
                break
    if find is None:                       # anything else: the thing they named, minus the cheat words
        rest = re.sub(r"\b(infinite|unlimited|inf|max|maxed|full|always|never run out of|freeze|lock|"
                      r"set|to|keep|super|double|triple|x\d+|\d+(?:\.\d+)?|more|give|get|of)\b", " ", t)
        find = re.sub(r"\s+", " ", rest).strip() or name
        group = _category(find)
    if kind in ("speed", "jump"):
        mode, value = modmenu.mode_and_value(t, find)
        if mode not in ("scale",):
            mode, value = "scale", (value if value and value > 1 else (2.0 if kind == "jump" else 3.0))
    elif kind == "topspeed":
        _, value = modmenu.mode_and_value(t, find)
        mode, value = "freeze", (value if value and value > 1 else 3.0)
    else:
        mode, value = modmenu.mode_and_value(t, find)
    return validate_item({"name": name, "find": find, "kind": kind, "mode": mode, "value": value,
                          "hotkey": hotkey, "group": group or _category(find)})


def validate_item(it):
    if not isinstance(it, dict):
        raise ValueError("menu item is not an object")
    out = {"name": str(it.get("name") or it.get("find") or "Cheat").strip()[:50],
           "find": str(it.get("find") or it.get("name") or "").strip()[:80],
           "kind": it.get("kind") if it.get("kind") in KINDS else "value",
           "mode": it.get("mode") if it.get("mode") in MODES else "freeze",
           "group": str(it.get("group") or "Cheats").strip()[:24] or "Cheats",
           "hotkey": [], "value": None}
    if not out["find"]:
        raise ValueError("menu item doesn't say what to find")
    v = it.get("value")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        out["value"] = float(v)
    elif isinstance(v, str):
        try:
            out["value"] = float(v)
        except ValueError:
            pass
    hk = it.get("hotkey") or []
    try:
        out["hotkey"] = modmenu.parse_combo(" + ".join(hk) if isinstance(hk, list) else str(hk))
    except ValueError:
        out["hotkey"] = []
    if out["kind"] in ("speed", "jump"):
        out["mode"] = "scale"
        out["value"] = out["value"] if out["value"] and out["value"] > 1 else (2.0 if out["kind"] == "jump" else 3.0)
    if out["kind"] == "topspeed":
        out["mode"] = "freeze"
        out["value"] = out["value"] if out["value"] and out["value"] > 1 else 3.0
    if out["kind"] == "spawn":
        out["mode"] = "set"
        out["spawn_kind"] = it.get("spawn_kind") if it.get("spawn_kind") in (
            "Vehicles", "Weapons", "Characters", "Items") else "Vehicles"
    if out["mode"] in ("set", "add", "multiply") and out["value"] is None and out["kind"] != "spawn":
        out["mode"] = "freeze"
    return out


def plan_from_text(text):
    items, seen = [], set()
    for part in _split(text):
        try:
            it = item_from_text(part)
        except ValueError:
            continue
        key = (it["find"].lower(), it["kind"])
        if key in seen:
            continue
        seen.add(key)
        items.append(it)
    if not items:
        raise ValueError("I couldn't tell which cheats you want. Try: infinite ammo, god mode, super speed")
    return items[:12]


MENU_SYSTEM = """You plan an in-game mod menu for a game-hacking tool attached to an emulator (PS2, PS3,
GameCube/Wii, PSP, PS1) or an offline PC game. The user describes the menu in one sentence. The tool
can only change numbers in memory, so turn every wish into a number to find and what to do with it.
The message may name the game: use what you know about it.

Return ONLY a JSON object, no other text:
{"items": [
  {"name": short menu label ("Infinite ammo"),
   "find": what the AI coach should look for, in a few plain words ("ammo", "health", "money",
           "run speed", "car speed", "jump height", "wanted level", "which car am I in (id)"),
   "kind": "value" (a number on screen or a bar), "speed" (run/car/swim/fly speed - the tool keeps it
           multiplied), "topspeed" (raise the game's max speed setting instead), "jump" (jump power,
           kept multiplied), "spawn" (which car/weapon/item you have - for a spawn menu),
   "mode": "freeze" (keep it at a value; value null = keep the current value - use for infinite/
           unlimited/god mode), "set" (one press sets it), "add" (one press adds value), "scale"
           (speed/jump: keep multiplied by value),
   "value": number or null,
   "hotkey": [] or controller buttons / keys like ["L1","R1"] or ["F3"] (only if the user asked),
   "group": menu page: Weapons, Health, Money, Movement, Vehicle, Game State, Spawn Vehicles...}
]}
At most 10 items. One item per value (god mode = health freeze). Keep names short."""


def plan_with_brain(text, brain, game_hint="", timeout=60):
    user = text if not game_hint else f"Game: {game_hint}\nThe mod menu I want: {text}"
    reply = brain.chat(MENU_SYSTEM, user, max_tokens=1500, timeout=timeout)
    data = coachlib.parse_json_reply(reply)
    raw = data.get("items") if isinstance(data, dict) else None
    if not isinstance(raw, list) or not raw:
        raise ValueError("the AI didn't list any menu items")
    items = []
    for r in raw[:12]:
        try:
            items.append(validate_item(r))
        except ValueError:
            pass
    if not items:
        raise ValueError("the AI's menu items were unusable")
    return items


def plan_menu(text, brain=None, game_hint=""):
    """(items, brain name, note) - the AI when one is set up, the built-in brain otherwise or on any problem."""
    if brain is not None and brain.usable:
        try:
            return plan_with_brain(text, brain, game_hint), brain.name, ""
        except Exception as e:
            note = f"{brain.name} unavailable ({type(e).__name__}: {str(e)[:100]}); used the built-in brain."
            return plan_from_text(text), "built-in", note
    return plan_from_text(text), "built-in", ""


def describe_item(it):
    v = it.get("value")
    hk = f"  [{modmenu.combo_text(it['hotkey'])}]" if it.get("hotkey") else ""
    n = "" if v is None else f"{v:g}"
    what = {"freeze": "keep it at " + (n or "its current value"), "scale": f"keep it x{n}",
            "set": f"set it to {n}", "add": f"add {n}", "multiply": f"multiply by {n}"}[it["mode"]]
    if it["kind"] == "spawn":
        what = "spawn menu (swap in any " + it.get("spawn_kind", "Vehicles")[:-1].lower() + ")"
    elif it["kind"] == "topspeed":
        what = f"raise the game's top speed x{v:g}"
    return f"{it['name']}: find {it['find']!r} -> {what}{hk}"


def find_in_library(it, library):
    """A library value that's already this item (so it doesn't have to be found again), or None."""
    words = [w for w in re.split(r"[^a-z0-9]+", it["find"].lower()) if len(w) > 2 and w not in ("which", "the")]
    best, score = None, 0.0
    for e in library:
        if e.get("kind") != "value" or e.get("category") == "Unsorted" or "?" in e["name"]:
            continue
        if it["kind"] == "topspeed" and "top speed" not in e["name"].lower():
            continue
        name = e["name"].lower()
        s = sum(1 for w in words if w in name) / max(1, len(words))
        if s > score:
            best, score = e, s
    return best if score >= 0.99 else None


def cheat_for(it, entry):
    """The cheat for a found value (entry = library value)."""
    v = it.get("value")
    if it["kind"] == "topspeed":
        v = None          # the GUI fills in top speed x factor once it knows the setting's value
    elif v is not None and entry["type"] != "float" and it["mode"] in ("freeze", "set", "add"):
        v = int(round(v))
    return {"name": it["name"], "entry": entry["name"], "mode": it["mode"], "value": v,
            "hotkey": list(it.get("hotkey") or []), "group": it.get("group") or "Cheats", "activator": None}


class MenuBuild:
    """Walks the items: the GUI finds each one with the coach, then calls found() or skip()."""

    def __init__(self, items):
        self.items = [dict(i) for i in items]
        self.i = 0
        self.log = []            # (item, 'made' | 'had' | 'skipped', detail)

    @property
    def done(self):
        return self.i >= len(self.items)

    @property
    def current(self):
        return None if self.done else self.items[self.i]

    def progress(self):
        return f"{min(self.i + 1, len(self.items))}/{len(self.items)}"

    def found(self, how="made", detail=""):
        self.log.append((self.current, how, detail))
        self.i += 1

    def skip(self, why=""):
        self.log.append((self.current, "skipped", why))
        self.i += 1

    def summary(self):
        made = [it["name"] for it, how, _ in self.log if how in ("made", "had")]
        skipped = [it["name"] for it, how, _ in self.log if how == "skipped"]
        s = f"Mod menu built: {len(made)} cheat(s)" + (f" ({', '.join(made)})" if made else "")
        if skipped:
            s += f". Skipped: {', '.join(skipped)}"
        return s + "."

    def to_json(self):
        return json.dumps({"items": self.items, "i": self.i})
