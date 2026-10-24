"""
coach.py - the "AI coach": turns "ammo, I have 40" or "car speed" into a plan of
in-game instructions + scans, then runs it and narrows memory down for you.

Two brains:
  * plan_from_text()   built-in, offline, understands common game values
  * plan_with_claude() optional, uses the Claude API for anything else
Both produce the same recipe format, checked by validate_recipe().
"""
import json
import re
import urllib.request

import numpy as np

import ps2core as core

OPS = ("unknown", "exact", "changed", "unchanged", "increased", "decreased", "greater", "less")
FIRST_OPS = ("unknown", "exact", "greater", "less")
ALL_TYPES = ("u32", "u16", "byte", "float")

# --------------------------------------------------------------------------
# Built-in knowledge
# --------------------------------------------------------------------------
# name -> (keywords, category, lose hint, gain hint, likely types)
COUNTERS = {
    "ammo":   (["ammo", "ammunition", "bullets", "rounds", "clip", "magazine", "shells", "rockets",
                "grenades", "arrows"], "Weapons",
               "shoot a few times", "reload or pick up ammo", ["u32", "u16", "byte", "float"]),
    "money":  (["money", "cash", "dollars", "coins", "gold", "credits", "gil", "rupees", "bank",
                "funds", "bucks", "points to spend"], "Money",
               "spend some (buy something)", "earn or pick up some money", ["u32", "float", "u16"]),
    "lives":  (["lives", "life count", "extra lives", "continues", "tries"], "Game State",
               "lose a life", "get an extra life", ["byte", "u16", "u32"]),
    "score":  (["score", "points", "kills", "goals", "runs", "touchdowns"], "Game State",
               None, "score some points", ["u32", "u16", "float", "byte"]),
    "items":  (["potions", "items", "keys", "bombs", "medkits", "health packs"], "Items",
               "use one", "pick one up", ["byte", "u16", "u32"]),
    "wanted": (["wanted level", "wanted", "stars", "heat"], "Game State",
               "lose the police", "commit a crime until a star appears", ["byte", "u32", "float", "u16"]),
    "timeouts": (["timeouts", "time outs", "challenges", "downs"], "Game State",
                 "use one", None, ["byte", "u16", "u32"]),
}

BARS = {
    "health":  (["health", "hp", "hit points", "life bar", "hearts"], "Health",
                "take some damage (fall off something, get hit)", "heal (health pack, eat, rest)"),
    "armor":   (["armor", "armour", "shield", "defense"], "Health",
                "get hit until the armor drops", "pick up armor"),
    "stamina": (["stamina", "sprint", "endurance", "fatigue"], "Running",
                "sprint until the bar drops", "stop and rest"),
    "fuel":    (["fuel", "gas", "petrol", "gasoline"], "Vehicle",
                "drive around to burn fuel", "refuel"),
    "energy":  (["energy", "mana", "mp", "magic", "power bar", "special", "rage", "focus"], "Game State",
                "use a special move / spell", "let it recharge"),
    "nitro":   (["nitro", "boost", "nos", "turbo"], "Vehicle",
                "use nitro", "let it refill"),
    "oxygen":  (["oxygen", "air", "breath"], "Health",
                "go underwater", "come up for air"),
    "kick":    (["kick meter", "power meter", "kick power", "swing meter", "throw meter"], "Kicking",
                None, None),
}

SPEED_WORDS = ["speed", "velocity", "mph", "kph", "km/h", "rpm", "fast", "speedometer", "momentum"]
HEIGHT_WORDS = ["height", "altitude", "elevation", "jump height", "y position", "how high"]
POSITION_WORDS = ["position", "coordinates", "coords", "location", "x position", "z position",
                  "where i am", "teleport"]
TIMER_WORDS = ["timer", "time", "clock", "countdown", "shot clock", "game clock", "quarter", "seconds left",
               "time left", "day", "hour"]
EVENT_WORDS = ["ball", "puck", "projectile", "football", "baseball", "after i hit", "after hit", "kicked",
               "thrown", "pass", "shot ball", "launch", "exit velocity", "hit power", "batting power"]


def _num(text):
    m = re.search(r"(-?\d+(?:\.\d+)?)", text.replace(",", ""))
    if not m:
        return None
    s = m.group(1)
    return float(s) if "." in s else int(s)


def _has(text, words):
    for w in sorted(words, key=len, reverse=True):
        if re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", text):
            return w
    return None


def _step(say, scan=None, secs=0, until="timer", value=None):
    s = {"say": say, "scan": scan, "secs": secs, "until": until}
    if value is not None:
        s["value"] = value
    return s


PREDICT_WORDS = ["predict", "prediction", "aimbot", "aim bot", "before he", "before she", "before it",
                 "before they", "gonna throw", "going to throw", "will throw", "gonna pitch",
                 "going to pitch", "where he throws", "where it goes", "where it will go", "where it's going",
                 "read the pitch", "strike or ball", "strike or not", "ball or strike", "know to swing",
                 "where the pitch", "pitch location", "where he's aiming", "where he is aiming",
                 "where they shoot", "where he shoots", "where the shot", "which way", "target location"]
LAUNCH_OBJECTS = {"pitch": ["pitch", "pitcher", "pitches", "strike", "swing", "batter", "at bat"],
                  "shot": ["shot", "shoot", "shooter", "penalty", "goalie", "kick", "free kick"],
                  "throw": ["throw", "pass", "qb", "quarterback", "serve", "toss", "bowl", "bowler"]}


def predict_recipe(title="Where the pitch will go", action="pitch"):
    nice = {"pitch": "the pitcher RELEASES the ball", "shot": "the shot is taken",
            "throw": "the ball is thrown"}.get(action, "the ball is released")
    return {
        "title": title, "category": "Game State", "mode": "predict", "types": ["float"],
        "event": {"action": action,
                  "say": f"Play normally. Press ] the moment {nice}. About 9-12 {action}es: the first "
                         f"few find the ball, the rest learn where the CPU aims."},
        "steps": [], "loop": [],
    }


def detect_mode(text):
    """What kind of job is this? 'predict' | 'event' | 'scan'"""
    t = " " + text.lower() + " "
    if _has(t, PREDICT_WORDS) or (re.search(r"\bwhere\b", t) and re.search(
            r"\b(gonna|going to|will|before|about to)\b", t)):
        return "predict"
    ev = _has(t, EVENT_WORDS)
    if ev and (_has(t, SPEED_WORDS) or "power" in t or "after" in t or ev in ("ball", "puck", "projectile")):
        return "event"
    return "scan"


def launch_action(text):
    t = " " + text.lower() + " "
    for action, words in LAUNCH_OBJECTS.items():
        if _has(t, words):
            return action
    return "pitch"


def plan_from_text(text, force_mode=None):
    r = _plan_from_text(text, force_mode)
    r = _understood(r, text)
    if r.get("generic"):
        r["understood"] += (" - I wasn't sure what this is, so it's a general up/down search. Pick a "
                            "different mode in the dropdown or add a Claude key for a smarter plan.")
    return r


def _plan_from_text(text, force_mode=None):
    """Built-in brain. Returns a recipe dict. force_mode overrides what it detects."""
    raw = text.strip()
    t = " " + raw.lower() + " "
    n = _num(t)
    full = any(w in t for w in (" full ", " max", " maxed", "100%"))
    mode = force_mode or detect_mode(raw)

    if mode == "predict":
        action = launch_action(raw)
        title = {"pitch": "Where the pitch will go", "shot": "Where the shot will go",
                 "throw": "Where the throw will go"}[action]
        r = validate_recipe(predict_recipe(title, action))
        verb = {"pitch": "pitch", "shot": "shoot", "throw": "throw"}[action]
        r["understood"] = f"Predict where the CPU will {verb} BEFORE it happens, and show it on screen"
        return r

    # ---- ball / object after an event -> Auto hunt -------------------------
    if mode == "event":
        action = "kicked" if "kick" in t else "thrown" if ("throw" in t or "pass" in t) else "hit"
        return validate_recipe({
            "understood": f"Find the ball's speed/height right after it's {action} (for boosts)",
            "title": f"Ball after it's {action}", "category": "Game State", "mode": "event",
            "types": ["float"],
            "event": {"action": action,
                      "say": f"Play normally. Every time the ball is {action}, press ] right at that "
                             f"moment. 5-8 {action}s usually does it."},
            "steps": [], "loop": [],
        })

    # ---- jumps / running / driving: one action that rises and comes back --------------
    pk = pulse_kind(t)
    if pk:
        return validate_recipe(pulse_recipe(pk, raw))

    # ---- which car / weapon / item you have (for spawning) ---------------------------
    kind = id_kind(t)
    if kind:
        return validate_recipe(id_recipe(kind))

    # ---- speed -------------------------------------------------------------------
    w = _has(t, SPEED_WORDS)
    if w:
        thing = _thing(raw, w)
        veh = any(x in t for x in ("car", "vehicle", "bike", "boat", "plane", "truck", "drive", "kart"))
        go, stop = ("Accelerate (hold the gas)", "Brake to a full stop") if veh else \
                   ("Run / move as fast as you can", "Stop moving")
        return validate_recipe({
            "title": thing, "category": "Vehicle" if veh else "Running", "types": ["float", "u32", "u16"],
            "steps": [_step(f"{stop} and stay still.", "unknown", 5),
                      _step("Stay stopped...", "unchanged", 2)],
            "loop": [_step(f"{go} for 5 seconds!", "increased", 5),
                     _step(f"{stop} now.", "decreased", 5),
                     _step("Stay stopped...", "unchanged", 2)],
            "target": 4, "max_loops": 6,
        })

    # ---- known counters ----------------------------------------------------------
    for key, (words, cat, lose, gain, types) in COUNTERS.items():
        w = _has(t, words)
        if w:
            return validate_recipe(_counter_recipe(w, cat, lose, gain, types, n))

    # ---- bars (health etc.) -----------------------------------------------------
    for key, (words, cat, lose, gain) in BARS.items():
        w = _has(t, words)
        if w:
            if key == "kick":
                return validate_recipe(_meter_recipe(w, cat))
            if n is not None and not full:
                return validate_recipe(_counter_recipe(w, cat, lose, gain, list(ALL_TYPES), n))
            return validate_recipe(_bar_recipe(w, cat, lose, gain))

    # ---- height / position ------------------------------------------------------
    w = _has(t, HEIGHT_WORDS)
    if w:
        thing = _thing(raw, w)
        return validate_recipe({
            "title": thing, "category": "Game State", "types": ["float"],
            "steps": [_step("Stand on flat ground and don't move.", "unknown", 4),
                      _step("Keep still...", "unchanged", 2)],
            "loop": [_step("Go UP: climb stairs, a hill or a ledge, then stand still up there. "
                           "Press ] when you're standing still up high.", "increased", until="key"),
                     _step("Keep still...", "unchanged", 2),
                     _step("Go back DOWN and stand still. Press ] when done.", "decreased", until="key"),
                     _step("Keep still...", "unchanged", 2)],
            "target": 6, "max_loops": 5,
        })
    w = _has(t, POSITION_WORDS)
    if w:
        thing = _thing(raw, w)
        return validate_recipe({
            "title": thing, "category": "Game State", "types": ["float"],
            "steps": [_step("Stand still somewhere you can walk forward and back.", "unknown", 4),
                      _step("Keep still...", "unchanged", 2)],
            "loop": [_step("Walk forward a few steps, then stop. Press ] when stopped.", "changed", until="key"),
                     _step("Keep still...", "unchanged", 2),
                     _step("Walk back to about where you started, stop, press ].", "changed", until="key"),
                     _step("Keep still...", "unchanged", 2)],
            "target": 9, "max_loops": 5,
        })

    # ---- timers -----------------------------------------------------------------
    w = _has(t, TIMER_WORDS)
    if w:
        thing = _thing(raw, w)
        steps = [_step("Unpause the game and let time run.", "unknown", 2)]
        if n is not None:
            steps = [_step(f"Looking for {thing}. Pause the game, then type exactly what the clock "
                           "shows (minutes x 60 + seconds if it's a game clock).", "exact", value="ask",
                           until="key")]
        return validate_recipe({
            "title": thing, "category": "Game State", "types": ["float", "u32", "u16"],
            "steps": steps,
            "loop": [_step("Let the clock run (unpaused) for 3 seconds.", "changed", 3),
                     _step("PAUSE the game and leave it paused.", "unchanged", 3, until="timer"),
                     _step("Unpause and let it run 3 seconds.", "changed", 3)],
            "target": 4, "max_loops": 5,
        })

    # ---- anything else: generic up / down -----------------------------------------
    thing = raw.rstrip("?.! ") or "the value"
    if n is not None:
        return validate_recipe(_counter_recipe(thing, "Other", "make it go down", "make it go up",
                                               list(ALL_TYPES), n))
    return {**validate_recipe({
        "title": thing, "category": "Other", "types": list(ALL_TYPES),
        "steps": [_step(f"Starting the hunt for: {thing}. Don't touch anything.", "unknown", 3)],
        "loop": [_step(f"Make {thing} go UP (do whatever raises it). Press ] when it has.",
                       "increased", until="key"),
                 _step("Don't touch anything...", "unchanged", 3),
                 _step(f"Make {thing} go DOWN. Press ] when it has.", "decreased", until="key"),
                 _step("Don't touch anything...", "unchanged", 3)],
        "target": 5, "max_loops": 6,
    }), "generic": True}


def _understood(r, text):
    if not r.get("understood"):
        what = {"exact": "the exact number you see", "unknown": "how it changes"}
        first = next((s["scan"] for s in r["steps"] + r["loop"] if s["scan"]), "unknown")
        r["understood"] = (f"Find the memory value for '{r['title']}' "
                           f"(category {r['category']}), tracking {what.get(first, 'how it changes')}")
    return r


def _thing(raw, word):
    m = re.search(r"([a-z]+\s+)?" + re.escape(word), raw.lower())
    s = m.group(0).strip() if m else word
    return s[:1].upper() + s[1:]


PULSES = {
    # kind: (what to do after pressing ], mid seconds, post seconds, category, title)
    "jump": ("Stand still. Press ] and JUMP right away, then land and stand still.", 0.4, 2.2,
             "Jumping", "Jump height / jump speed"),
    "run": ("Stand still. Press ] and RUN straight for 2 seconds, then stop and stand still.", 1.3, 3.8,
            "Running", "Run speed"),
    "drive": ("Stop the car. Press ] and floor it for 3 seconds, then brake to a full stop.", 2.2, 7.5,
              "Vehicle", "Car speed"),
    "swim": ("Float still. Press ] and swim for 2 seconds, then stop.", 1.3, 3.8, "Running", "Swim speed"),
    "fly": ("Hover still. Press ] and fly forward for 2 seconds, then stop.", 1.5, 4.5, "Vehicle", "Flying speed"),
}


def pulse_kind(t):
    t = " " + t.lower() + " "
    if re.search(r"\bjump", t):
        return "jump"
    if not (_has(t, SPEED_WORDS) or re.search(r"\b(run|sprint|walk|move|drive|driving)\b", t)):
        return None
    if any(w in t for w in ("ball", "puck", "pitch", "after i hit", "after hit", "kick")):
        return None                      # the ball hunt handles those
    if any(w in t for w in ("car", "vehicle", "drive", "driving", "bike", "kart", "truck", "boat", "race")):
        return "drive"
    if any(w in t for w in ("swim",)):
        return "swim"
    if any(w in t for w in ("plane", "fly", "flying", "heli", "jet")):
        return "fly"
    return "run"


def pulse_recipe(kind, raw=""):
    say, mid, post, cat, title = PULSES[kind]
    return {"understood": f"Find your {title.lower()}: you do it once, it rises and comes back - repeat 4-6 times",
            "title": title, "category": cat, "mode": "pulse", "types": ["float", "u32", "u16"],
            "pulse": {"kind": kind, "say": say, "mid": mid, "post": post}, "steps": [], "loop": []}


def id_kind(t):
    t = " " + t.lower() + " "
    if not any(w in t for w in (" id", "spawn", "which car", "which weapon", "model", "which item",
                                "what car", "what weapon", "current car", "current weapon", "type of car")):
        return None
    if any(w in t for w in ("car", "vehicle", "bike", "truck", "boat", "heli", "plane", "tank", "ride")):
        return "Vehicles"
    if any(w in t for w in ("weapon", "gun", "pistol", "rifle", "shotgun")):
        return "Weapons"
    if any(w in t for w in ("skin", "character", "outfit", "ped")):
        return "Characters"
    return "Items"


def id_recipe(kind):
    """Find the value holding WHICH car / weapon / item you have - what spawn menus write to."""
    a, b, back = {
        "Vehicles": ("Get in a car and sit still", "Get out and into a DIFFERENT kind of car",
                     "Get into yet another kind of car (or back into the first kind)"),
        "Weapons": ("Hold one weapon and stand still", "Switch to a DIFFERENT weapon",
                    "Switch to another weapon (or back to the first)"),
        "Characters": ("Stand still as your current character / outfit", "Change to a DIFFERENT outfit/character",
                       "Change again (or back to the first)"),
        "Items": ("Pick an item in your inventory / item slot and leave it selected",
                  "Select a DIFFERENT item", "Select another item (or the first one again)"),
    }[kind]
    return {"understood": f"Find which {kind[:-1].lower()} you have right now (its ID) - so the spawn menu "
                          f"can swap in any {kind[:-1].lower()}",
            "title": f"{kind[:-1]} ID", "category": "Spawn", "types": ["u32", "u16", "byte"],
            "steps": [_step(f"{a}.", "unknown", 3), _step("Keep still...", "unchanged", 2)],
            "loop": [_step(f"{b}. Press ] when you have it.", "changed", until="key"),
                     _step("Keep still...", "unchanged", 2),
                     _step(f"{back}. Press ] when you have it.", "changed", until="key"),
                     _step("Keep still...", "unchanged", 2)],
            "target": 4, "max_loops": 6, "spawn_kind": kind}


def _counter_recipe(word, cat, lose, gain, types, n):
    thing = word[:1].upper() + word[1:]
    # games often show two numbers (in the gun / spare): every step must use the same one
    which = " - the bullets in the gun, if it shows two numbers" if cat == "Weapons" else ""
    loop = []
    if lose:
        loop.append(_step(f"Change your {word}: {lose}. Then type the new number{which}.", "exact",
                          value="ask", until="key"))
    if gain:
        loop.append(_step(f"Now {gain}. Then type the new number{which}.", "exact", value="ask", until="key"))
    if not loop:
        loop.append(_step(f"Change your {word}, then type the new number.", "exact", value="ask",
                          until="key"))
    if n is not None:
        steps = [_step(f"Looking for {word} = {n}.", "exact", value=n)]
    else:
        steps = [_step(f"What number does the game show for {word} right now{which}? Type it.", "exact",
                       value="ask", until="key")]
    return {"title": thing, "category": cat, "types": types, "steps": steps, "loop": loop,
            "target": 3, "max_loops": 6}


def _bar_recipe(word, cat, lose, gain):
    thing = word[:1].upper() + word[1:]
    return {
        "title": thing, "category": cat, "types": ["float", "u32", "u16", "byte"],
        "steps": [_step(f"Get your {word} to FULL if you can, then stand still.", "unknown", 4)],
        "loop": [_step(f"Lose some {word}: {lose}. Press ] when it has gone down.", "decreased",
                       until="key"),
                 _step("Don't do anything for a moment...", "unchanged", 1.5),
                 _step(f"Get some {word} back: {gain}. Press ] when it has gone up.", "increased",
                       until="key"),
                 _step("Don't do anything for a moment...", "unchanged", 1.5)],
        "target": 3, "max_loops": 6,
    }


def _meter_recipe(word, cat):
    thing = word[:1].upper() + word[1:]
    return {
        "title": thing, "category": cat, "types": ["float", "u32", "u16", "byte"],
        "steps": [_step("Line up for a kick/swing but don't start the meter yet.", "unknown", 3),
                  _step("Wait...", "unchanged", 2)],
        "loop": [_step("Start the meter and press ] while it's about HALF full.", "increased",
                       until="key"),
                 _step("Let it finish, wait until the next setup screen, press ].", "changed",
                       until="key"),
                 _step("Wait...", "unchanged", 2)],
        "target": 4, "max_loops": 6,
    }


# --------------------------------------------------------------------------
# Recipe validation (both brains go through this)
# --------------------------------------------------------------------------
def _merge_steps(steps):
    """'Fire a few shots, press ]' + 'Type the new ammo' -> one step: fewer things for the player to do."""
    out = []
    i = 0
    act_scans = ("exact", "changed", "increased", "decreased", "greater", "less")
    while i < len(steps):
        st = steps[i]
        if st["scan"] is None and i + 2 < len(steps) and steps[i + 1]["scan"] == "unchanged" \
                and steps[i + 2]["scan"] in act_scans:
            out.append(steps[i + 1])              # the "do nothing" check belongs BEFORE the action
            steps = steps[:i] + [st] + steps[i + 2:]
            continue
        if st["scan"] is None and i + 1 < len(steps) and steps[i + 1]["scan"] in act_scans:
            nxt = dict(steps[i + 1])
            first = re.split(r"(?i)[.,;]?\s*(then )?(stop and )?(press \]|and press)", st["say"])[0].strip(" .,")
            if first:
                rest = nxt["say"]
                nxt["say"] = f"{first}, then {rest[:1].lower() + rest[1:]}"[:300]
            if st["until"] == "key" and nxt["until"] == "timer" and nxt.get("value") != "ask":
                nxt["until"] = "key"
            out.append(nxt)
            i += 2
            continue
        out.append(st)
        i += 1
    return out


def validate_recipe(r):
    if not isinstance(r, dict):
        raise ValueError("plan is not an object")
    out = {
        "title": str(r.get("title") or "Value")[:60],
        "category": str(r.get("category") or "Other")[:30],
        "mode": r.get("mode") if r.get("mode") in ("event", "predict", "pulse") else "scan",
        "understood": str(r.get("understood") or "")[:200],
        "types": [x for x in (r.get("types") or ALL_TYPES) if x in core.TYPES] or list(ALL_TYPES),
        "target": int(r.get("target") or 3),
        "max_loops": max(1, min(12, int(r.get("max_loops") or 6))),
        "steps": [], "loop": [],
    }
    if r.get("spawn_kind"):
        out["spawn_kind"] = str(r["spawn_kind"])[:20]
    if out["mode"] == "pulse":
        p = r.get("pulse") or {}
        kind = p.get("kind") if p.get("kind") in PULSES else "run"
        d = PULSES[kind]
        out["pulse"] = {"kind": kind, "say": str(p.get("say") or d[0])[:300],
                        "mid": max(0.15, min(10.0, float(p.get("mid") or d[1]))),
                        "post": max(0.5, min(20.0, float(p.get("post") or d[2])))}
        if out["pulse"]["post"] <= out["pulse"]["mid"]:
            out["pulse"]["post"] = out["pulse"]["mid"] + 1.5
        return out
    if out["mode"] in ("event", "predict"):
        ev = r.get("event") or {}
        default_say = ("Press ] every time the ball is hit." if out["mode"] == "event" else
                       "Press ] the moment the ball is released.")
        out["event"] = {"action": str(ev.get("action") or ("hit" if out["mode"] == "event" else "pitch"))[:20],
                        "say": str(ev.get("say") or default_say)[:300]}
        if out["mode"] == "predict":
            out["types"] = ["float"]
        return out
    for part in ("steps", "loop"):
        for s in r.get(part) or []:
            scan = s.get("scan")
            if scan is not None and scan not in OPS:
                raise ValueError(f"unknown scan '{scan}'")
            until = s.get("until") if s.get("until") in ("timer", "key") else "timer"
            secs = float(s.get("secs") or 0)
            if until == "timer":
                secs = max(0.0, min(30.0, secs))
            step = {"say": str(s.get("say") or "")[:300], "scan": scan, "secs": secs, "until": until}
            v = s.get("value")
            if v == "ask" or isinstance(v, (int, float)) and not isinstance(v, bool):
                step["value"] = v
            if scan in ("exact", "greater", "less") and "value" not in step:
                step["value"] = "ask"
                step["until"] = "key"
            out[part].append(step)
    for part in ("steps", "loop"):
        out[part] = _merge_steps(out[part])
    scans = [s for s in out["steps"] + out["loop"] if s["scan"]]
    if not scans:
        raise ValueError("plan has no scans")
    first = next(s for s in out["steps"] + out["loop"] if s["scan"])
    if first["scan"] not in FIRST_OPS:
        # a compare-scan needs something to compare with: start with an unknown snapshot
        out["steps"].insert(0, {"say": "Starting... don't touch anything.", "scan": "unknown",
                                "secs": 2, "until": "timer"})
    if not out["loop"]:
        raise ValueError("plan needs a loop of steps to repeat")
    return out


# --------------------------------------------------------------------------
# Optional: Claude as the brain
# --------------------------------------------------------------------------
CLAUDE_SYSTEM = """You plan memory searches for a game-hacking tool (like Cheat Engine) attached to an
emulator (PS2, PS3, GameCube/Wii, PSP, PS1) or an offline PC game. The message may name the game:
use what you know about it (how it stores health/ammo, what the player can do) to pick good steps. The user says what value they want to find. You write a step-by-step plan: short
instructions the player follows in the game, and the memory scan to run when each step ends.

Return ONLY a JSON object, no other text:
{
 "title": short name of the value,
 "category": one of Ratings, Running, Passing, Kicking, Jumping, Defense, Game State, Controller,
             Weapons, Health, Money, Vehicle, Items, Other,
 "mode": "scan" to find a value; "pulse" for anything that goes up during ONE action and comes
         back when it ends - jump height, run speed, car speed, swim/fly speed (needs "pulse":
         {"kind": "jump"|"run"|"drive"|"swim"|"fly", "say": what to do after pressing ], "mid": seconds
         after ] when it's at its peak, "post": seconds after ] when it's back to rest}); "event" ONLY to find a ball/object's speed right after it is
         hit/kicked/thrown (for power boosts); "predict" when the user wants to know in advance
         where the CPU will throw/pitch/shoot/aim (the tool then learns which value in memory
         decides the target and shows it live),
 "understood": one sentence saying what you think the user wants,
 "types": value types to try, from "u32","u16","byte","float" (counters shown as whole numbers:
          u32,u16,byte,float; smooth physical things like speed/position/height: float first),
 "steps": [steps run once at the start],
 "loop": [steps repeated until few results are left],
 "target": stop when this many or fewer results remain (3-6),
 "max_loops": 3-8,
 "event": {"action": "hit"|"kicked"|"thrown" (event) or "pitch"|"shot"|"throw" (predict),
           "say": instruction - for predict: press ] the moment the ball is released}
           (event/predict modes only; steps and loop can be empty for them)
}
Each step: {"say": instruction shown on screen (one short sentence, tell the player exactly what to
do), "scan": one of unknown, exact, changed, unchanged, increased, decreased, greater, less, or
null for no scan, "until": "timer" (scan runs when "secs" seconds are up) or "key" (scan runs when
the player presses ]), "secs": number, "value": a number, or "ask" to make the player type the
number they see}.
BE FAST - the player may only get a few chances (lives, deaths, rare events):
- As few steps as possible. Every step the player does must end with a scan. Never make a separate
  "press ]" step without a scan: put the action and the scan in one step ("Fire 2 shots, then type
  the ammo number").
- If the number is visible on screen, use "exact" with "ask" every time it changes - that is by far
  the fastest (2-3 steps usually leaves only copies).
- target 3-6, max_loops 3-5. The tool tests the last few results by itself, so don't over-narrow.
Rules: the first scan must be "unknown" or "exact". Compare-scans (changed/unchanged/increased/
decreased) compare with the previous scan. Use "unchanged" steps of 1.5-3 s where the player does
nothing, to remove values that change on their own - but not for values that keep changing by
themselves. If the user gave the current number, start with an exact scan of it and then ask for
the new number each time it changes. Things that refill by themselves (regenerating health):
keep the unchanged steps short."""


def plan_with_brain(text, brain, game_hint="", timeout=60):
    """Any AI (Claude, Gemini, OpenAI-compatible...) writes the plan."""
    user = text if not game_hint else f"Game: {game_hint}\nWhat I want to find: {text}"
    reply = brain.chat(CLAUDE_SYSTEM, user, max_tokens=1500, timeout=timeout)
    return validate_recipe(parse_json_reply(reply))


def plan_with_claude(text, api_key, model="claude-sonnet-5-5", timeout=60):
    import brain as _b
    return plan_with_brain(text, _b.Brain("anthropic", api_key, model), timeout=timeout)


def parse_json_reply(reply):
    m = re.search(r"\{.*\}", reply, re.S)
    if not m:
        raise ValueError("Claude didn't return a plan")
    return json.loads(m.group(0))


def make_plan(text, api_key=None, model="claude-sonnet-5-5", force_mode=None, brain=None, game_hint=""):
    """The AI brain when one is set up (falls back to built-in on any problem). Returns (recipe, source, note)."""
    if brain is None and api_key:
        import brain as _b
        brain = _b.Brain("anthropic", api_key, model)
    use = brain is not None and brain.usable
    asked = text
    if force_mode and use:
        asked += {"predict": " (The user chose: PREDICT mode.)", "event": " (The user chose: EVENT mode.)",
                  "scan": " (The user chose: SCAN mode - find a value.)"}[force_mode]
    if use:
        try:
            r = plan_with_brain(asked, brain, game_hint)
            if force_mode and r["mode"] != force_mode and not (force_mode == "scan" and r["mode"] == "pulse"):
                r = plan_from_text(text, force_mode)
            return r, brain.name, ""
        except Exception as e:  # network, key, bad JSON...
            note = f"{brain.name} unavailable ({type(e).__name__}: {str(e)[:100]}); used the built-in brain."
            return plan_from_text(text, force_mode), "built-in", note
    return plan_from_text(text, force_mode), "built-in", ""


# --------------------------------------------------------------------------
# Running a plan
# --------------------------------------------------------------------------
class Coach:
    def __init__(self, recipe):
        self.r = recipe
        self.scanners = {vt: core.Scanner() for vt in recipe["types"]}
        self.started = False
        self.pos = 0              # index into steps, then loop
        self.loops = 0
        self.done = False
        self.failed = False
        self.stalled = False
        self.loop_totals = []
        self.history = []

    # -- current instruction --
    def _seq(self):
        return self.r["steps"] if self.pos < len(self.r["steps"]) else self.r["loop"]

    def current(self):
        if self.done:
            return None
        if self.pos < len(self.r["steps"]):
            return self.r["steps"][self.pos]
        return self.r["loop"][(self.pos - len(self.r["steps"])) % len(self.r["loop"])]

    @property
    def total(self):
        return sum(s.count for s in self.scanners.values() if s.active)

    def counts(self):
        return {vt: s.count for vt, s in self.scanners.items() if s.active}

    # -- do it --
    def apply(self, snap, typed=None):
        step = self.current()
        if step is None:
            return
        op = step.get("scan")
        if op:
            value = step.get("value")
            if value == "ask":
                value = typed
            if op in ("exact", "greater", "less") and value is None:
                raise ValueError("This step needs the number from the game.")
            if step.get("value") == "ask" and self.started:
                # a typo / the wrong one of two numbers on screen must not throw the whole search away
                saved = {vt: (sc.idx, sc.prev, sc.count, sc.scans) for vt, sc in self.scanners.items()}
                self._scan(snap, op, value)
                if self.total == 0:
                    for vt, (idx, prev, count, scans) in saved.items():
                        sc = self.scanners[vt]
                        sc.idx, sc.prev, sc.count, sc.scans = idx, prev, count, scans
                    self.failed = self.done = False
                    self.retyped = getattr(self, "retyped", 0) + 1
                    raise ValueError(f"Nothing in memory is {value:g} now - check the number and type it again "
                                     "(if the game shows two numbers, type the same one as before, e.g. the "
                                     "bullets in your gun, not the spare ammo). Or press Skip.")
            else:
                self._scan(snap, op, value)
            self.history.append((step["say"], op, value, self.total))
        self._advance()

    def _scan(self, snap, op, value):
        if not self.started:
            mode = op if op in FIRST_OPS else "unknown"
            for vt, sc in list(self.scanners.items()):
                v = None
                if mode != "unknown":
                    v = self._value_for(vt, value)
                    if v is None:              # e.g. 12.5 can't be a whole-number type
                        del self.scanners[vt]
                        continue
                sc.first(snap, vt, {"greater": "greater than", "less": "less than"}.get(mode, mode), v)
            self.started = True
        else:
            if op == "unknown":                 # nothing to compare - just a new reference point
                for sc in self.scanners.values():
                    if sc.active and sc.idx is not None:
                        sc.prev = sc._view(snap)[sc.idx].copy()
                    elif sc.active:
                        sc.prev = sc._view(snap).copy()
                return
            mode = {"exact": "exact", "greater": "greater than", "less": "less than"}.get(op, op)
            for vt, sc in list(self.scanners.items()):
                if not sc.active or sc.count == 0:
                    continue
                v = None
                if mode in core.VALUE_MODES:
                    v = self._value_for(vt, value)
                    if v is None:
                        sc.idx = np.array([], dtype=np.int32)
                        sc.prev = sc.prev[:0]
                        sc.count = 0
                        continue
                sc.next(snap, mode, v)
        # stop conditions
        tot = self.total
        if self.started and tot == 0:
            self.failed = True
            self.done = True
        elif self.started and 0 < tot <= self.r["target"] and \
                all(s.idx is not None for s in self.scanners.values() if s.active):
            self.done = True

    @staticmethod
    def _value_for(vt, value):
        if value is None:
            return None
        if vt == "float":
            return float(value)
        if float(value) != int(float(value)):
            return None
        v = int(float(value))
        bits = 8 * core.TYPES[vt][2]
        return v if 0 <= v < (1 << bits) else None

    def _advance(self):
        self.pos += 1
        k = self.pos - len(self.r["steps"])
        if k > 0 and k % len(self.r["loop"]) == 0:
            self.loops += 1
            tot = self.total
            self.loop_totals.append(tot)
            # no real progress in a whole round: what's left all moves together (copies) - more rounds
            # won't separate them, testing will. Stop instead of making you repeat it 10 more times.
            if len(self.loop_totals) >= 2 and tot <= 400 and tot >= 0.85 * self.loop_totals[-2]:
                self.stalled = True
                self.done = True
            if self.loops >= self.r["max_loops"]:
                self.done = True

    def extend(self, more=3):
        """Keep going from where we are (don't start over)."""
        self.done = False
        self.failed = False
        self.stalled = False
        self.loop_totals = self.loop_totals[-1:]
        self.r["max_loops"] = self.loops + more
        if self.pos < len(self.r["steps"]):
            self.pos = len(self.r["steps"])

    def candidates(self, snap, limit=5000):
        return [(a, vt) for vt, a, _ in self.results(snap, limit)]

    def results(self, snap, limit=60):
        """[(type, addr, value)] - one entry per memory spot, in the plan's preferred type."""
        found = []
        for rank, vt in enumerate(self.r["types"]):
            sc = self.scanners.get(vt)
            if sc and sc.active and sc.idx is not None:
                for addr, cur, prev in sc.results(snap, max(2000, limit)):
                    found.append((rank, vt, addr, cur))
        found.sort(key=lambda x: (x[0], x[2]))
        taken, out = [], []
        for rank, vt, addr, cur in found:
            end = addr + core.TYPES[vt][2]
            if any(addr < e and s < end for s, e in taken):
                continue                      # same spot already listed as a better type
            taken.append((addr, end))
            out.append((vt, addr, cur))
        out.sort(key=lambda x: (self.r["types"].index(x[0]), x[1]))
        return out[:limit]

    def summary(self):
        c = self.counts()
        if not self.started:
            return "Not started"
        if all(s.idx is None for s in self.scanners.values() if s.active):
            return "Watching all of memory..."
        return ", ".join(f"{n:,} {vt}" for vt, n in c.items() if n) or "0 left"
