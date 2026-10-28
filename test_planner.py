"""Smoke test against the live Spring 2027 CIS data: python test_planner.py"""
import time
import planner_core as core

PREFS = dict(earliest=600, latest=960, max_walk=9, max_bus=12, gap_weight=2, friday_weight=3, quiz_weight=2, walk_weight=2)
COURSES = [("PHYS", "212"), ("TAM", "210"), ("CS", "101"), ("MATH", "314"), ("MACS", "100")]
HAND_PICKED = {"38029", "56034", "38105", "36212", "78007", "31018", "58968", "76588", "78780", "63464", "63471"}

core.load_geo(); core.load_bus()
secs = {c: core.fetch_course(2027, "spring", *c) for c in COURSES}
bundles = [core.bundles_for_course(s) for s in secs.values()]

# no bundle pairs a lecture with another lecture
for grp in bundles:
    for b in grp:
        assert len({m["crn"] for m in b if core.is_lecture(m)}) <= 1, b

# the schedule found by hand earlier is still feasible
hand = [m for grp in bundles for b in grp for m in b if {x["crn"] for x in b} <= HAND_PICKED]
hand = list({(m["crn"], m["days"], m["s"]): m for m in hand}.values())
assert core.score_schedule(hand, PREFS) is not None, "hand-picked schedule rejected"

t = time.time()
res = core.search(bundles, PREFS)
print(f"{len(res)} results in {time.time() - t:.1f}s")
assert res, "no schedules"
for pen, worst, _, m in res:
    assert worst < 9
    for x in m:
        if x["online"]: continue
        assert x["s"] >= 600
        assert x["e"] <= 960 or (not core.is_lecture(x) and x["s"] < 960)

# exactly one discussion per course (online and in-person are the same requirement)
for grp in bundles:
    for b in grp:
        assert sum("DISC" in m["type"].upper() and not core.is_lecture(m) for m in b) <= 1, [m["n"] for m in b]

# hard rules: a 5-min gap with a 7-min walk must be rejected
a = dict(c="A", n="1", crn="1", type="Lecture", days="M", s=600, e=650, b="Armory", online=False)
b = dict(c="B", n="1", crn="2", type="Lecture", days="M", s=655, e=700, b="Loomis Laboratory", online=False)
assert core.score_schedule([a, b], PREFS) is None

# bus: Armory->Loomis walk is ~16 min, so only the bus (~12 min door to door) can make it
walk, bus = core.walk_min("Armory", "Loomis Laboratory"), core.bus_min("Armory", "Loomis Laboratory")
assert walk > core.WALK_ONLY_UNDER and bus is not None and bus < walk, (walk, bus)
b2 = dict(b, s=650 + int(bus) + 2)  # gap just big enough for the bus
assert core.score_schedule([a, b2], PREFS) is not None
assert core.score_schedule([a, b2], dict(PREFS, max_bus=bus - 1)) is None   # over the bus limit
assert core.score_schedule([a, dict(b, s=650 + int(bus) - 1)], PREFS) is None  # bus doesn't fit the gap
# short walks never use the bus
assert core.travel("Gregory Hall", "English Building", PREFS)[1] == "walk"
print("all checks passed")
