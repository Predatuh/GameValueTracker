"""
gameinfo.py - work out WHICH game is running and WHAT KIND of game it is, so the tool can
show only the tabs and examples that make sense for it.
"""
import json
import re
import urllib.request

# recorder events that make sense for each kind of game (keys of ps2core.EVENT_RECIPES)
EVENTS = {'baseball': ['ball', 'score', 'run', 'stamina'], 'football': ['ball', 'score', 'run', 'stamina'], 'soccer': ['ball', 'score', 'run', 'stamina'], 'golf': ['ball', 'score'], 'sports': ['score', 'run', 'stamina', 'ball', 'timer'], 'racing': ['drive', 'money', 'lower', 'timer', 'stamina'], 'open_world': ['shoot', 'damage', 'money', 'die', 'jump', 'run', 'drive', 'lower', 'switch', 'item'], 'shooter': ['shoot', 'damage', 'die', 'jump', 'run', 'switch', 'item'], 'fighting': ['damage', 'stamina', 'timer', 'jump'], 'rpg': ['money', 'damage', 'item', 'die', 'run', 'switch'], 'action': ['die', 'damage', 'jump', 'item', 'money', 'run', 'lower']}


def events_for(genre):
    import ps2core
    keys = EVENTS.get(genre) or list(ps2core.EVENT_RECIPES)
    return keys + [k for k in ps2core.EVENT_RECIPES if k not in keys]


# what each kind of game gets ---------------------------------------------------------------
#   tabs: optional tabs to show (always shown: AI Coach, Scanner, Recorder, Library, Cheats, Mod menu, Help)
#   predict: show the pitch/shot predictor settings
GENRES = {
    "baseball":   {"label": "Baseball", "tabs": {"boost", "ratings"}, "predict": True,
                   "examples": ['"ball speed after I hit it"', '"where is the pitcher going to throw"',
                                '"batting power"', '"runs, we have 3"', '"pitch speed"', '"stamina"'],
                   "spawn": []},
    "football":   {"label": "Football", "tabs": {"boost", "ratings"}, "predict": False,
                   "examples": ['"kick power"', '"player speed"', '"game clock"', '"score, we have 14"',
                                '"ball speed after I kick it"', '"timeouts left"'],
                   "spawn": []},
    "soccer":     {"label": "Soccer", "tabs": {"boost", "ratings"}, "predict": True,
                   "examples": ['"shot power"', '"ball speed after I kick it"', '"player stamina"',
                                '"game clock"', '"score"'], "spawn": []},
    "golf":       {"label": "Golf", "tabs": {"boost"}, "predict": False,
                   "examples": ['"ball speed after I hit it"', '"drive power"', '"wind speed"', '"strokes"'],
                   "spawn": []},
    "sports":     {"label": "Other sports", "tabs": {"ratings"}, "predict": False,
                   "examples": ['"player speed"', '"game clock"', '"score, we have 20"', '"stamina"',
                                '"shot power"'], "spawn": []},
    "racing":     {"label": "Racing", "tabs": {"spawn"}, "predict": False,
                   "examples": ['"car speed"', '"nitro"', '"money, I have 5000"', '"lap time"',
                                '"race position"', '"damage"'], "spawn": ["Cars"]},
    "open_world": {"label": "Open world / action (GTA style)", "tabs": {"spawn"}, "predict": False,
                   "examples": ['"ammo, I have 30"', '"money"', '"health, I\'m full"', '"wanted level"',
                                '"car speed"', '"armor"', '"how high I jump"'],
                   "spawn": ["Vehicles", "Weapons"]},
    "shooter":    {"label": "Shooter", "tabs": {"spawn"}, "predict": False,
                   "examples": ['"ammo, I have 30"', '"health, I\'m full"', '"grenades"', '"armor"',
                                '"lives"'], "spawn": ["Weapons"]},
    "fighting":   {"label": "Fighting", "tabs": set(), "predict": False,
                   "examples": ['"health, I\'m full"', '"super meter"', '"round timer"', '"enemy health"'],
                   "spawn": []},
    "rpg":        {"label": "RPG", "tabs": {"spawn"}, "predict": False,
                   "examples": ['"gold, I have 250"', '"HP"', '"MP"', '"experience"', '"potions, I have 5"'],
                   "spawn": ["Items"]},
    "action":     {"label": "Platformer / action-adventure", "tabs": {"spawn"}, "predict": False,
                   "examples": ['"lives, I have 3"', '"health"', '"coins, I have 40"', '"how high I jump"',
                                '"ammo"'], "spawn": ["Items"]},
    "other":      {"label": "Other / not sure (show everything)", "tabs": {"boost", "ratings", "spawn"},
                   "predict": True,
                   "examples": ['"ammo, I have 40"', '"my money"', '"health, I\'m at full"', '"car speed"',
                                '"how high I jump"', '"game clock"', '"ball speed after I hit it"'],
                   "spawn": ["Vehicles", "Weapons", "Items"]},
}

KEYWORDS = [   # checked in order; first hit wins
    ("baseball", ["baseball", "mlb", "mvp 0", "world series", "the show", "slugfest", "home run",
                  "power pros", "bottom of the 9th", "triple play", "high heat", "all-star baseball"]),
    ("football", ["ncaa football", "madden", "nfl", "blitz", "college football", "espn football",
                  "all-pro football", "backbreaker", "football 20"]),
    ("soccer", ["fifa", "pro evolution", "winning eleven", "pes 20", "soccer", "mario strikers",
                "football manager", "uefa", "world cup"]),
    ("golf", ["golf", "tiger woods", "hot shots", "everybody's golf", "links "]),
    ("sports", ["nba", "basketball", "nhl", "hockey", "tennis", "top spin", "skate", "tony hawk", "ssx",
                "fight night", "boxing", "march madness", "bowling", "volleyball", "cricket", "rugby",
                "ncaa", "espn", "2k"]),
    ("racing", ["need for speed", "gran turismo", "burnout", "midnight club", "forza", "ridge racer",
                "motorstorm", "juiced", "mario kart", "cruis'n", "motocross", "mx vs", "atv",
                "wipeout", "f-zero", "nascar", "rally", "dirt", "test drive", "street racing",
                "outrun", "split/second", "grid", "racer", "racing", "kart", "twisted metal"]),
    ("open_world", ["grand theft auto", "gta", "saints row", "mercenaries", "scarface", "true crime",
                    "bully", "red dead", "just cause", "hit & run", "hit and run", "godfather",
                    "the getaway", "mafia", "driver", "spider-man", "spiderman", "simpsons", "infamous",
                    "prototype", "crackdown", "sleeping dogs", "watch dogs", "assassin", "lego"]),
    ("shooter", ["call of duty", "medal of honor", "battlefield", "halo", "killzone", "resistance",
                 "socom", "ghost recon", "rainbow six", "timesplitters", "doom", "counter-strike",
                 "half-life", "goldeneye", "perfect dark", "007", "black ops", "far cry", "crysis",
                 "bioshock", "borderlands", "gears of war", "metroid prime", "red faction", "black"]),
    ("fighting", ["tekken", "mortal kombat", "soulcalibur", "soul calibur", "street fighter",
                  "dragon ball", "budokai", "smackdown", "wwe", "ufc", "def jam", "naruto",
                  "dead or alive", "virtua fighter", "smash bros", "marvel vs", "king of fighters",
                  "guilty gear", "bloody roar"]),
    ("rpg", ["final fantasy", "kingdom hearts", "dragon quest", "persona", "elder scrolls", "oblivion",
             "skyrim", "fallout", "pokemon", "pokémon", "monster hunter", "tales of", "xenosaga",
             "dark souls", "demon's souls", "star ocean", "dark cloud", "shin megami", "disgaea",
             "baldur", "champions of norrath", "phantasy star", "fable", "mass effect", "dragon age",
             "the witcher", "diablo", ".hack", "suikoden", "wild arms", "valkyrie", "chrono"]),
    ("action", ["mario", "sonic", "crash", "spyro", "ratchet", "jak", "sly", "rayman", "banjo",
                "kirby", "donkey kong", "zelda", "god of war", "devil may cry", "prince of persia",
                "metal gear", "resident evil", "silent hill", "kingdom", "ape escape", "klonoa",
                "psychonauts", "okami", "shadow of the colossus", "ico", "tomb raider", "uncharted",
                "little big planet", "littlebigplanet", "castlevania", "ninja gaiden", "onimusha"]),
]


def classify(title):
    t = " " + (title or "").lower() + " "
    for genre, words in KEYWORDS:
        for w in words:
            if (" " + w) in t or (w in t and len(w) > 4):
                return genre
    return "other"


CLAUDE_GENRE_PROMPT = ("Which kind of video game is this? Answer with exactly one word from this list: "
                       + ", ".join(GENRES) + ". Game: ")


def classify_with_brain(title, brain, timeout=20):
    word = brain.chat("Answer with one word.", CLAUDE_GENRE_PROMPT + title, max_tokens=10, timeout=timeout)
    word = re.sub(r"[^a-z_]", "", word.strip().lower())
    return word if word in GENRES else None


def classify_with_claude(title, api_key, model="claude-sonnet-5-5", timeout=20):
    body = json.dumps({"model": model, "max_tokens": 10,
                       "messages": [{"role": "user", "content": CLAUDE_GENRE_PROMPT + title}]}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, method="POST",
                                 headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                                          "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode())
    word = "".join(b.get("text", "") for b in data.get("content", [])).strip().lower()
    word = re.sub(r"[^a-z_]", "", word)
    return word if word in GENRES else None


# game name from the emulator's window titles ---------------------------------------------
SERIAL = r"[A-Z]{4}[-_ ]?\d{3,5}(?:\.\d{2})?"
NOISE = ("pcsx2", "rpcs3", "dolphin", "ppsspp", "duckstation", "game value tracker", "cheat engine",
         "settings", "log", "debugger", "memory card", "controller", "properties", "game list",
         "gamelist", "cheats", "graphics", "about")


def _clean(t):
    t = re.sub(r"[™®©]", "", t)
    t = re.sub(r"\s{2,}", " ", t)
    return t.strip(" -|:")


def detect(profile, titles, exe=""):
    """{'title', 'serial', 'key'} from the window titles of the emulator / game."""
    title = serial = None
    for raw in titles:
        t = raw.strip()
        if not t:
            continue
        m = None
        if profile == "ps3":
            m = re.search(r"\|\s*([^|]+?)\s*\[([A-Z]{4}\d{5})\]\s*$", t)
            if m:
                title, serial = m.group(1), m.group(2)
        elif profile == "gcwii":
            m = re.search(r"\|\s*([^|]+?)\s*\(([A-Z0-9]{6})\)\s*$", t)
            if m:
                title, serial = m.group(1), m.group(2)
        elif profile == "psp":
            m = re.search(r"-\s*([A-Z]{4}\d{5})\s*:\s*(.+)$", t)
            if m:
                serial, title = m.group(1), m.group(2)
        if m:
            break
    if not title:
        best = None
        for raw in titles:
            t = _clean(raw)
            low = t.lower()
            if not t or any(low.startswith(n) or low == n for n in NOISE):
                parts = [p for p in re.split(r"\s+[|\-–]\s+", t) if p and not any(
                    p.lower().startswith(n) for n in NOISE) and not re.match(r"^(v?\d|fps|vulkan|opengl|"
                                                                             r"direct3d|d3d|jit|hle|lle)", p.lower())]
                if not parts:
                    continue
                t = parts[-1]
            m = re.search(SERIAL, t)
            if m and not serial:
                serial = m.group(0).replace("_", "-").replace(" ", "-")
                t = _clean(t.replace(m.group(0), "").replace("[]", "").replace("()", ""))
            if t and (best is None or len(t) > len(best)):
                best = t
        title = best
    if title and profile != "pc" and re.sub(r"[^a-z0-9]", "", title.lower()) == \
            re.sub(r"[^a-z0-9]", "", re.sub(r"\.exe$", "", exe, flags=re.I).lower()):
        title = None                              # only the emulator's own name: no game booted
    found = bool(title)
    if profile == "pc" and not title:
        title = re.sub(r"\.exe$", "", exe, flags=re.I)
    title = _clean(title or "") or (re.sub(r"\.exe$", "", exe, flags=re.I) if exe else "Unknown game")
    key = serial or re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")[:60] or "unknown"
    return {"title": title, "serial": serial, "key": f"{profile}_{key}", "found": found or profile == "pc"}
