"""Core logic for the UIUC schedule planner: building locations, walk/bus times,
CIS fetching, bundling, scoring, and search. No GUI, no API keys."""

import json, re, math, os, sys, time, heapq, itertools, functools
import urllib.request, urllib.parse
import xml.etree.ElementTree as ET

DAYS = "MTWRF"
WALK_ONLY_UNDER = 10   # walks shorter than this are always faster than waiting for a bus
STOP_RADIUS_M = 400    # how far you'd walk to a bus stop


def resource(name):
    """Bundled read-only file (works inside a PyInstaller exe too)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def user_file(name):
    """Writable per-user file for things the app learns (new building locations)."""
    d = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "UIUC Schedule Planner")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, name)


# ---------------------------------------------------------------------------
# Building locations
# ---------------------------------------------------------------------------

GEO = {}
MANUAL = {
    "Armory": (40.1047, -88.2316),
    "Materials Science & Eng Bld": (40.1107, -88.2265),
    "Literatures, Cultures, & Ling": (40.1070, -88.2258),
}
ALIAS = {
    "Loomis Laboratory": "Loomis Laboratory of Physics",
    "Siebel Center for Comp Sci": "Thomas M. Siebel Center for Computer Science",
    "English Building": "English Building, Urbana",
    "Gregory Hall": "Gregory Hall, Urbana",
    "Transportation Building": "Transportation Building, Urbana",
    "Psychology Building": "Psychology Building, Champaign",
    "Ceramics Building": "Ceramics Building, Urbana",
    "Sidney Lu Mech Engr Bldg": "Sidney Lu Mechanical Engineering Building",
    "Music Building": "Music Building, Urbana",
    "National Soybean Res Ctr": "National Soybean Research Center",
    "Lincoln Hall": "Lincoln Hall, Urbana",
}


def load_geo():
    GEO.clear()
    for path in (resource("geo.json"), user_file("geo.json")):  # user entries override bundled ones
        try:
            raw = json.load(open(path))
        except (OSError, json.JSONDecodeError):
            continue
        GEO.update({k: (v[0], v[1]) for k, v in raw.items() if v and len(v) >= 2})


def set_coord(b, lat, lon):
    GEO[ALIAS.get(b, b)] = (lat, lon)
    path = user_file("geo.json")
    try:
        saved = json.load(open(path))
    except (OSError, json.JSONDecodeError):
        saved = {}
    saved[ALIAS.get(b, b)] = [lat, lon]
    json.dump(saved, open(path, "w"), indent=1)


def has_coord(b):
    return bool(b) and (b in MANUAL or ALIAS.get(b, b) in GEO)


def coord(b):
    if b in MANUAL:
        return MANUAL[b]
    key = ALIAS.get(b, b)
    if key not in GEO:
        raise KeyError(f"No location for {b!r}")
    return GEO[key]


_NOM_LAST = [0.0]

def geocode(name):
    """OpenStreetMap lookup (free, no key, max 1 request/second)."""
    if not name:
        return None
    wait = 1.1 - (time.time() - _NOM_LAST[0])
    if wait > 0:
        time.sleep(wait)
    _NOM_LAST[0] = time.time()
    for q in (ALIAS.get(name, name), name):
        p = urllib.parse.urlencode({"q": q + ", Illinois", "format": "json", "limit": 1,
                                    "viewbox": "-88.26,40.13,-88.20,40.09", "bounded": 1})
        try:
            req = urllib.request.Request("https://nominatim.openstreetmap.org/search?" + p,
                                         headers={"User-Agent": "uiuc-schedule-planner/1.0"})
            data = json.load(urllib.request.urlopen(req, timeout=10))
            if data:
                return float(data[0]["lat"]), float(data[0]["lon"])
        except Exception:
            pass
    return None


# ---------------------------------------------------------------------------
# Walking / bus
# ---------------------------------------------------------------------------

def _walk_m(p, q):
    dx = (q[1] - p[1]) * 111_320 * math.cos(math.radians(p[0]))
    dy = (q[0] - p[0]) * 110_540
    return math.hypot(dx, dy) * 1.3  # paths aren't straight lines


def walk_min(a, b):
    return _walk_m(coord(a), coord(b)) / 80  # 80 m/min


BUS = {"stops": {}, "pairs": {}}

def load_bus():
    try:
        BUS.update(json.load(open(resource("bus_data.json"))))
    except (OSError, json.JSONDecodeError):
        pass
    bus_min.cache_clear()


@functools.lru_cache(maxsize=None)
def bus_min(a, b):
    """Average door-to-door bus time from MTD's published schedule, or None.
    walk to stop + average wait + average ride + walk from stop; direct trips only."""
    pa, pb = coord(a), coord(b)
    near = lambda p: [(s, _walk_m(p, xy) / 80) for s, xy in BUS["stops"].items() if _walk_m(p, xy) <= STOP_RADIUS_M]
    best = None
    for sa, wa in near(pa):
        row = BUS["pairs"].get(sa, {})
        for sb, wb in near(pb):
            if sb in row:
                ride, wait = row[sb]
                t = wa + wait + ride + wb
                best = t if best is None else min(best, t)
    return best


def travel(a, b, prefs):
    """(minutes, 'walk'|'bus') for the faster allowed option, or None if neither fits the limits."""
    w = walk_min(a, b)
    if w < WALK_ONLY_UNDER:
        return (w, "walk") if w <= prefs["max_walk"] else None
    bus = bus_min(a, b)
    options = [(w, "walk")] if w <= prefs["max_walk"] else []
    if bus is not None and bus <= prefs["max_bus"]:
        options.append((bus, "bus"))
    return min(options) if options else None


# ---------------------------------------------------------------------------
# CIS fetching
# ---------------------------------------------------------------------------

def parse_time(s):
    h, m = map(int, s[:5].split(":"))
    return (h % 12 + (12 if s[-2:] == "PM" else 0)) * 60 + m


def fetch_course(year, term, subj, num, skip_restricted=True):
    """List of sections, each a list of meeting records. [] if the course isn't offered."""
    url = (f"https://courses.illinois.edu/cisapp/explorer/schedule/"
           f"{year}/{term}/{subj}/{num}.xml?mode=detail")
    req = urllib.request.Request(url, headers={"User-Agent": "uiuc-schedule-planner/1.0"})
    try:
        root = ET.parse(urllib.request.urlopen(req, timeout=15)).getroot()
    except urllib.error.HTTPError as e:
        if e.code in (404, 500):  # CIS answers unknown courses with an error page
            return []
        raise
    title = root.findtext("label") or ""
    out = []
    for s in root.iter("detailedSection"):
        text = s.findtext("sectionText") or ""
        n = s.findtext("sectionNumber") or ""
        if skip_restricted and (n.upper().startswith("HON") or
                                re.search(r"consent|fill out this form|approval required|by application", text, re.I)):
            continue  # honors / permission-only: students can't just register
        link = re.search(r"lecture section (\w+)", text)
        mtgs = []
        for m in s.findall(".//meeting"):  # a section can meet at several times/rooms
            start = (m.findtext("start") or "").strip()
            days = "".join(d for d in (m.findtext("daysOfTheWeek") or "") if d in DAYS)
            online = start in ("", "ARRANGED") or not days  # online, TBA, or weekend-only
            mtgs.append(dict(
                c=f"{subj} {num}", title=title, n=n,
                crn=s.get("id") or "", type=(m.findtext("type") or "").strip(),
                days="" if online else days,
                s=0 if online else parse_time(start),
                e=0 if online else parse_time(m.findtext("end") or ""),
                b="" if online else (m.findtext("buildingName") or "").strip(),
                link=link.group(1) if link else None, online=online,
            ))
        if mtgs:
            out.append(mtgs)
    return out


def is_lecture(m):
    return "LEC" in m["type"].upper()


def bundles_for_course(secs):
    """One lecture section + one section of each associated non-lecture type.
    Each bundle is a flat tuple of meeting records."""
    lecs = [s for s in secs if is_lecture(s[0])]
    if not lecs:
        return [tuple(s) for s in secs]
    others = [s for s in secs if not is_lecture(s[0])]
    bundles = []
    for l in lecs:
        n = l[0]["n"]
        assoc = [o for o in others if o[0]["link"] == n or (not o[0]["link"] and o[0]["n"][:1] == n[:1])]
        if not assoc and others and len(lecs) == 1:
            assoc = others  # one lecture, sections with unrelated letters: all go with it
        groups = {}
        for o in assoc:  # "Online Discussion" and "Discussion/Recitation" are the same requirement
            kind = o[0]["type"].replace("Online", "").replace("/Recitation", "").strip().upper()
            groups.setdefault(kind, []).append(o)
        for combo in itertools.product(*groups.values()):
            bundles.append(tuple(m for sec in (l, *combo) for m in sec))
    return bundles


# ---------------------------------------------------------------------------
# Scoring and search
# ---------------------------------------------------------------------------

def score_schedule(mtgs, prefs):
    """(penalty, worst_trip, trips) or None if a hard rule breaks.
    Penalties are in "equivalent idle minutes"; sliders (0-5, default 2-3) scale them.
    trips: {(day, crn_from, crn_to): (minutes, mode)} for tight transfers."""
    pen, trips = 0.0, {}
    mtgs = [x for x in mtgs if not x["online"]]
    for x in mtgs:
        if x["s"] < prefs["earliest"]:
            return None
        if x["e"] > prefs["latest"] and (is_lecture(x) or x["s"] >= prefs["latest"]):
            return None  # only labs/discussions that start before the cutoff may run past it
        t = x["type"].upper()
        if "DISC" in t or "QUIZ" in t:  # quizzes usually happen here; pure labs don't count
            pen += (4 - max(DAYS.index(d) for d in x["days"])) * 15 * prefs["quiz_weight"] / 2
    worst = 0.0
    for d in DAYS:
        day = sorted((x for x in mtgs if d in x["days"]), key=lambda x: x["s"])
        for a, b in zip(day, day[1:]):
            gap = b["s"] - a["e"]
            if gap < 0:
                return None
            pen += max(0, gap - 10) * prefs["gap_weight"] / 2
            if a["b"] == b["b"] or gap > max(prefs["max_walk"], prefs["max_bus"]) + 10:
                continue  # same building, or plenty of time
            tr = travel(a["b"], b["b"], prefs)
            if tr is None or tr[0] > gap - 1:
                return None
            trips[(d, a["crn"], b["crn"])] = tr
            worst = max(worst, tr[0])
            pen += tr[0] * prefs["walk_weight"] / 2
    pen += sum("F" in x["days"] for x in mtgs) * 40 * prefs["friday_weight"]  # slider 3 = 2h of gaps per Friday class
    return pen, worst, trips


def search(all_bundles, prefs, top=50):
    """Depth-first over courses, dropping any partial schedule that already breaks a hard rule
    (adding classes can only make that worse). Returns the best `top` as (pen, worst, trips, mtgs)."""
    order = sorted(all_bundles, key=len)  # fewest choices first = earliest pruning
    best, tick = [], itertools.count()

    def go(i, mtgs):
        if i == len(order):
            r = score_schedule(mtgs, prefs)
            if r:
                item = (-r[0], next(tick), (r[0], r[1], r[2], mtgs))
                if len(best) < top:
                    heapq.heappush(best, item)
                elif item[0] > best[0][0]:
                    heapq.heapreplace(best, item)
            return
        for b in order[i]:
            nxt = mtgs + list(b)
            if i + 1 < len(order) and score_schedule(nxt, prefs) is None:
                continue
            go(i + 1, nxt)

    go(0, [])
    return sorted((x[2] for x in best), key=lambda r: r[0])


def summarize(mtgs):
    """Plain-language stats for one schedule: Friday meetings, idle minutes, days on campus."""
    live = [x for x in mtgs if not x["online"]]
    idle = 0
    for d in DAYS:
        day = sorted((x for x in live if d in x["days"]), key=lambda x: x["s"])
        idle += sum(max(0, b["s"] - a["e"] - 10) for a, b in zip(day, day[1:]))
    return dict(fri=sum("F" in x["days"] for x in live), idle=idle,
                days=len({d for x in live for d in x["days"]}))
