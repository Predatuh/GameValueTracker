"""
spawner.py - build spawn lists (vehicles, weapons, items...) for a game.

How spawning works here: games keep the ID of the thing you have - the car model you're in, the
weapon in your hand, the item in a slot. Find that ID value once (AI Coach / Spawn tab), and
writing another ID into it swaps in a different car / weapon / item.

Where the names come from:
  1. the game's own files - many games ship plain tables like "400, landstal, ..." (GTA .ide),
     "weapon_id = 12" (.ini/.cfg/.lua), XML, CSV. scan_path() reads a game folder or a disc image
     (.iso/.bin/.img) and finds every ID -> name table in it.
  2. name lists stored back to back in memory or files (item 0, item 1, ...) - position = ID.
  3. learning live: the ID browser steps through IDs and you name what shows up.
match_tables() then ranks the tables by how many of the IDs you've actually seen in the game
belong to them, so the right list rises to the top by itself.
"""
import os
import re
from collections import defaultdict

TEXT_EXT = {".ide", ".dat", ".txt", ".ini", ".cfg", ".csv", ".xml", ".lua", ".json", ".def", ".tbl",
            ".list", ".lst", ".h", ".inc", ".script", ".sc", ".yml", ".yaml", ".conf", ".info"}
IMAGE_EXT = {".iso", ".bin", ".img", ".gcm", ".rvz_raw", ".wbfs", ".cso_raw", ".nrg", ".mdf"}
KIND_WORDS = {
    "Vehicles": ["vehicle", "car", "cars", "truck", "bike", "boat", "heli", "plane", "tank", "jeep",
                 "veh", "model", "landstal", "infernus", "cheetah", "banshee", "sedan", "taxi"],
    "Weapons": ["weapon", "gun", "pistol", "rifle", "shotgun", "smg", "rocket", "grenade", "ammo",
                "ak47", "m4", "uzi", "sniper", "knife", "bat", "launcher", "wep"],
    "Items": ["item", "potion", "armor", "armour", "sword", "shield", "key", "ring", "herb", "food",
              "equip", "gear", "inventory"],
    "Characters": ["ped", "skin", "character", "char", "npc", "player", "costume", "outfit"],
}

ID_NAME = [
    # 400, landstal, landstal, car, ...      (id first)
    re.compile(r"^[ \t]*(\d{1,5})[ \t]*[,;\t ][ \t]*\"?([A-Za-z][\w\-\. ]{1,40}?)\"?[ \t]*(?:[,;\t]|$)", re.M),
    # name = 12   /   "name": 12   /  NAME 12
    re.compile(r"^[ \t]*\"?([A-Za-z][\w\-\. ]{1,40}?)\"?[ \t]*(?:=|:|,|\t)[ \t]*(\d{1,5})[ \t]*[,;]?[ \t]*$", re.M),
    # <thing id="12" name="Shotgun">   /  id="12" ... name="x"
    re.compile(r"\bid\s*=\s*\"(\d{1,5})\"[^>\n]{0,120}?\bname\s*=\s*\"([^\"]{2,40})\"", re.I),
    re.compile(r"\bname\s*=\s*\"([^\"]{2,40})\"[^>\n]{0,120}?\bid\s*=\s*\"(\d{1,5})\"", re.I),
]
NAME_FIRST = {1, 3}
STOP_NAMES = {"end", "objs", "tobj", "cars", "peds", "weap", "path", "anim", "txdp", "version", "true",
              "false", "null", "none", "id", "name", "type", "count", "size", "begin", "start"}


def kind_of(source, names):
    blob = (source + " " + " ".join(names[:80])).lower()
    best, score = "Other", 0
    for kind, words in KIND_WORDS.items():
        s = sum(blob.count(w) for w in words)
        if s > score:
            best, score = kind, s
    return best


def tables_from_text(text, source):
    """Every ID -> name table in one chunk of text."""
    found = []
    for pi, rx in enumerate(ID_NAME):
        rows = {}
        for m in rx.finditer(text):
            a, b = m.group(1), m.group(2)
            ident, name = (int(b), a) if pi in NAME_FIRST else (int(a), b)
            name = name.strip()
            if name.lower() in STOP_NAMES or len(name) < 2 or name.isdigit():
                continue
            rows.setdefault(ident, name)
        if len(rows) >= 6:
            names = list(rows.values())
            if len(set(n.lower() for n in names)) >= 0.7 * len(names):
                found.append({"source": source, "kind": kind_of(source, names),
                              "entries": sorted(rows.items()), "how": "id table"})
    return found


def name_lists_from_bytes(data, source, min_run=8):
    """Runs of short NUL-separated names stored back to back (position = ID)."""
    out = []
    for m in re.finditer(rb"(?<![A-Za-z0-9_ \-\.'])(?:[A-Za-z][A-Za-z0-9_ \-\.']{2,31}\x00{1,4}){%d,400}" % min_run, data):
        names = [n.decode("latin-1") for n in re.split(rb"\x00+", m.group(0)) if n]
        if len(names) >= min_run and len(set(names)) >= 0.8 * len(names):
            out.append({"source": f"{source} @ {m.start():X}", "kind": kind_of(source, names),
                        "entries": list(enumerate(names)), "how": "name list (position = ID)"})
    return out


def _is_text(sample):
    if not sample:
        return False
    bad = sum(1 for b in sample if b < 9 or 13 < b < 32)
    return bad < len(sample) * 0.02


def scan_path(path, progress=None, max_tables=400, stop=None):
    """Scan a game folder, a single file, or a disc image. Returns tables, best first."""
    tables = []
    files = []
    if os.path.isdir(path):
        for root, _, names in os.walk(path):
            for n in names:
                files.append(os.path.join(root, n))
    else:
        files = [path]
    total = sum(os.path.getsize(f) for f in files if os.path.isfile(f)) or 1
    done = 0
    for f in files:
        if stop and stop():
            break
        try:
            size = os.path.getsize(f)
        except OSError:
            continue
        ext = os.path.splitext(f)[1].lower()
        rel = os.path.relpath(f, path) if os.path.isdir(path) else os.path.basename(f)
        try:
            with open(f, "rb") as fh:
                if ext in TEXT_EXT or (size < 4 << 20 and _is_text(fh.read(4096))):
                    fh.seek(0)
                    data = fh.read(16 << 20)
                    tables += tables_from_text(data.decode("latin-1"), rel)
                    tables += name_lists_from_bytes(data, rel)
                elif ext in IMAGE_EXT or not os.path.isdir(path) or size <= (64 << 20):
                    # big or binary: walk it in chunks and look at the readable text inside
                    chunk, overlap, pos = 8 << 20, 4096, 0
                    while True:
                        if stop and stop():
                            break
                        fh.seek(max(0, pos - overlap))
                        data = fh.read(chunk + overlap)
                        if not data:
                            break
                        for m in re.finditer(rb"[\t\r\n\x20-\x7e]{200,}", data):
                            tables += tables_from_text(m.group(0).decode("latin-1"),
                                                       f"{rel} @ {pos + m.start():X}")
                        tables += name_lists_from_bytes(data, f"{rel} @ {pos:X}")
                        pos += chunk
                        if progress:
                            progress(min(1.0, (done + min(pos, size)) / total), rel)
                        if pos >= size:
                            break
        except OSError:
            pass
        done += size
        if progress:
            progress(min(1.0, done / total), rel)
    return rank_tables(dedupe(tables))[:max_tables]


def dedupe(tables):
    seen, out = set(), []
    for t in tables:
        key = tuple(t["entries"][:40])
        if key not in seen:
            seen.add(key)
            out.append(t)
    return out


def rank_tables(tables, observed=()):
    obs = set(int(x) for x in observed)

    def score(t):
        ids = {i for i, _ in t["entries"]}
        hit = len(obs & ids)
        named = 1.0 if t["kind"] != "Other" else 0.5
        return (hit, named * min(len(ids), 300) + (40 if t["how"] == "id table" else 0))

    return sorted(tables, key=score, reverse=True)


def match_tables(tables, observed):
    """[(table, how many seen IDs it contains)] best first."""
    obs = [int(x) for x in observed]
    ranked = rank_tables(tables, obs)
    return [(t, sum(1 for o in set(obs) if o in {i for i, _ in t["entries"]})) for t in ranked]


def merge_learned(table_entries, learned):
    """Add names the player typed in the ID browser."""
    d = dict(table_entries)
    d.update({int(k): v for k, v in learned.items()})
    return sorted(d.items())
