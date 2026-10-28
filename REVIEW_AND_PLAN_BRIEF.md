# UIUC Schedule Planner: Code Review and Planning Brief

**Purpose of this document:** hand-off for a planning pass. Read the findings, then produce a prioritized implementation plan (ordered tasks, file-level changes, test strategy, open questions).

**Scope reviewed:** `planner_core.py` (also pasted as `.md`), `planner.py` GUI (uploaded as `deepseek_python_..._771651.py`), `DESIGN.md`, and legacy prototypes `solve.py`, `scan.py`, `compact.py`, plus `geo.json`. The review was by reading only; nothing was executed. The pasted `.md` stops after `score_schedule`; its promised §13 documentation was not present.

## 0. Project summary

A tkinter desktop app. The user enters classes. The app pulls sections from the UIUC CIS XML API, builds per-course bundles (lecture + one of each linked discussion/lab), searches combinations under hard rules and soft penalties, and draws the best week with a copyable CRN list. Walk times come from geocoded building coordinates (straight-line x 1.3 at 80 m/min). Optional bus times come from MTD or Google Directions.

**Current state:** the generic `planner_core` + GUI is a rewrite of the hand-tuned scripts (`solve.py`, `scan.py`, `compact.py`). Several behaviors from the scripts were lost or changed, and `DESIGN.md` describes features and rules the code does not implement.

---

## 1. Critical: fix first

| # | Issue | Where | Fix |
|---|---|---|---|
| 1 | **Only the first `<meeting>` per section is parsed.** Sections with multiple meetings (e.g. MW in one room, F in another; labs with differing days/times) are invisible to conflict checks, Friday counts, and the calendar. | `fetch_course` (`s.find(".//meeting")`), also `solve.py` | Iterate `findall(".//meeting")`, emit one record per meeting, and dedupe CRNs in the CRN output. |
| 2 | **Walk time is never compared to the gap.** Gap 5 min with walk 8 min is accepted (only adds a penalty). Without a bus key, walk > `max_walk` is also only a penalty. `solve.py` had hard `w >= 9: return None`. This is a regression and contradicts `DESIGN.md`. | `score_schedule` | Hard feasibility: `travel = min(walk, bus) if bus else walk`; reject if `travel > gap - 1`, and reject if `walk > max_walk` when no bus alternative. |
| 3 | **Bus key silently kills schedules.** With `has_bus_key`, any pair lacking bus data is rejected. API failures return `None` via bare `except: pass`; `None` is cached to disk permanently; a bad key looks like "no route". Result: "No valid schedules" with no explanation. | `score_schedule`, `bus_trip_minutes`, `_mtd_trip`, `_google_directions` | Fall back to walking when bus data is missing. Don't persist failures. Surface API errors to the UI. |
| 4 | **MTD API usage is probably wrong** (unverified). I believe v2.2 uses snake_case params (`origin_lat`, ...) and returns `travel_time` in minutes. Code sends camelCase and reads `travelTime`; missing key yields 9999, i.e. 166 min, so every bus transfer fails. `best/60 if best > 1000 else best` is a unit guess. | `_mtd_trip` | Verify against current MTD docs; pin units; add a test with a recorded response. |
| 5 | **Lectures bundle with other lecture sections.** `assoc` matches by first letter and does not exclude lectures, so `AL2` can become an "associated" group of `AL1`. | `bundles_for_course` | Add `"LEC" not in o["type"].upper()` to the filter. |
| 6 | **Quiz-late penalty condition is wrong vs. `solve.py`.** Original penalized every non-lecture except PHYS 212 L-sections. Now: `lab and c != "PHYS 212" and n[:1] != "L"` exempts all PHYS 212 sections and any section starting with "L" in any course. | `score_schedule` | Correct to `not (c == "PHYS 212" and n[:1] == "L")` short term. Better: decide by CIS section `type` (Laboratory vs Discussion/Quiz), with no hard-coded course. |
| 7 | **Brute-force search with no pruning.** GUI runs a full `itertools.product`, stores every valid schedule (with meeting lists), then sorts for the top 50. Memory/time unbounded for classes with many sections. `DESIGN.md` claims early pruning that does not exist. | `PlannerApp._run` | DFS adding one bundle at a time, aborting on conflict; pre-filter bundles violating earliest/latest individually; keep a `heapq.nsmallest(50)`; LRU-cache `walk_min`. |

---

## 2. Logic bugs: medium

- **Penalty cliff at gap = 20.** Gaps <= 20 get walk penalty only (no idle penalty). A 21-min gap costs `11 x gap_weight`; a 20-min gap costs about 0. `compact.py` and `DESIGN.md` penalize `gap - 10` for every gap. The GUI "idle" column uses that formula, so the displayed idle does not match the score.
- **Perverse bus incentive.** Walk <= max costs `0.5*w*ww`; longer walk costs `1.0*w*ww` (2x jump at the threshold); bus costs `0.4*bus*ww`. A 10-min walk vs. 5-min bus scores 2, cheaper than a 9-min walk at 4.5. Bus is never compared against walking: w=10, bus=18, gap=20 is rejected even though walking fits.
- **Friday weight drifted.** Comment says "~90 min per Friday meeting", but 90 penalty points at `gap_weight=2` is 45 idle minutes. `compact.py` used 120 idle minutes. "Light Friday" is about 2.7x weaker than the prototype. Penalty units (minutes x weight, days x weight, flat +40) are not commensurable and the 0-5 sliders are not normalized. Express everything as "equivalent minutes"; sliders become multipliers.
- **`walk_weight = 0` disables walk limits** in no-key mode (penalty becomes `w * 0`).
- **Crashes on edge data.**
  - `max(DAYS.index(d) for d in x["days"])` raises `ValueError` for non-online meetings with empty days (TBA) or weekend days (S/U).
  - `parse_time("")` returns 0, so a TBA-time section has `s=0 < earliest` and silently eliminates every schedule containing it.
- **Missing coordinates become free transfers.** `except Exception: w = 0.0` in `score_schedule`; an empty building string does the same. Fail loudly or flag.
- **Required components dropped silently.** If a lecture has no discussions matched by `link` or first letter (e.g. lecture `L`, discussions `AD1`), `assoc` is empty and the bundle is lecture-only. The discussion vanishes from schedule and CRNs with no warning.
- **Link regex hard-coded:** `r"lecture section (A\d)"` only matches A1-A9. Use `(\w+)`.
- **Lectures past latest end are only penalized (+40).** `DESIGN.md` says hard rule; a 6 pm lecture is currently allowed.
- **Time input handling.**
  - `hm()` raises on bad input.
  - `find()` disables the button before `_prefs()`, so a typo leaves it disabled forever with status stuck on "Fetching...".
  - Entering "4:00" (as in the mockup) means 04:00 and silently rejects everything.
  - No check that `latest > earliest`.
- **Bus departure time is nondeterministic.** If noon today has passed, `dep = now + 5 min` but the cache key still says 12:00. Date is "today" rather than a representative weekday of the target term. Cache key lacks provider, date, and term, so stale values persist.
- **Year default** `today().year + 1` is wrong from January through spring.
- **Geocode query uses `b`, not `ALIAS.get(b, b)`.** On a fresh `geo.json`, "Siebel Center for Comp Sci" fails in Nominatim even though the alias would succeed.

---

## 3. Design doc vs. code

| `DESIGN.md` says | Code does |
|---|---|
| Walk limit is a hard rule | Soft penalty, or bus hard-reject |
| Lectures past latest end are thrown out | +40 penalty |
| Idle beyond 10 min for all gaps | Gaps <= 20 skipped |
| Bus routing left out | Bus implemented (MTD + Google) |
| Disk cache for CIS responses | Not implemented; refetches every run |
| Gen ed slot, lock a section, class chips, hover tooltips, export .txt, "labs may overflow" checkbox | None implemented |
| Reuse `solve.py` logic as functions | Hand-tuned filters not carried over |

**Why the last row matters:** `solve.py` restricted MATH 314 to `AL1`/`BL1`, took only CS 101's first lecture, and used PHYS `D`/`L` naming. These were probably deliberate. The generic core includes all lectures, so results will differ. A "lock/allow sections" mechanism and a parity test are needed.

---

## 4. Architecture problems

- **Swallowed exceptions + negative caching.** Every network function does `except Exception: pass`. `geo.json` shows the damage: `"Armory, Urbana": null` and two other nulls are cached failures (which is why `MANUAL` exists). Distinguish "not found" from "request failed"; never persist failures.
- **UI freezes.** `_resolve_coords` runs on the Tk thread, including network geocoding (1.1 s rate-limit sleep + up to 10 s timeout per building). Geocode in the worker; only show dialogs on the main thread. Cancelling one dialog discards already-resolved buildings.
- **Bus matrix is O(N^2) API calls** (N x (N-1) directed pairs, up to 8 s each, billable). Compute lazily and only for pairs that occur in a tight transfer with walk > max. Directions are rarely meaningfully asymmetric.
- **Scoring is not incremental.** `score_schedule` rescored whole schedules, which blocks pruning and makes the gen ed idea (`scan.py` rescored every core schedule per candidate) inefficient. Split into hard checks (`can_add(state, bundle)`) and a soft cost function.
- **Course-specific hacks in generic code:** the `"PHYS 212"` check, the `A\d` regex, and the `n[:1]` prefix heuristic belong in data/config (per-course overrides).
- **Leaky coupling.** `has_bus_key` is injected into `prefs` by the GUI but describes data availability. A `TravelModel.minutes(a, b, gap)` object owning walk, bus, caching, and fallback would remove most bus problems above.
- **Global mutable state and relative paths.** `GEO` and `MTD_CACHE` are module globals; `set_coord` rewrites the whole file on every call; `geo.json`/`mtd_cache.json` resolve against the CWD. Use `Path(__file__).parent`.
- **Mixed `geo.json` keys.** Some are CIS names, some alias targets ("English Building, Urbana"), some full names. Key by the exact CIS building string; keep aliases as geocoding hints only. `scan.py` and `solve.py` use different key schemes against the same file.
- **Smaller issues.**
  - `scan.py` re-reads `geo.json` on each `coord` miss because `solve.py`'s `geo` is stale.
  - `compact.py` has a dead `if False` branch.
  - `exec(src[:src.index("res = []")])` is fragile.
  - Nominatim viewbox excludes some southern buildings (e.g. Vet Med); Google results are not sanity-checked as inside Champaign-Urbana.
  - Enrollment status is unused. I believe CIS detail XML includes it; a schedule full of closed sections is not useful.

---

## 5. What checks out

- Conflict detection is sound: sort by start and compare neighbors; a nested overlap always implies an adjacent one.
- `parse_time` handles 12:xx AM/PM, single-digit hours, and trailing spaces.
- Nominatim viewbox order (left, top, right, bottom) is correct; the rate limiter works.
- Tk threading is mostly right (widget reads on the main thread, queue back, dialog round-trip works) apart from blocking work on the Tk thread.
- `geo.json` coordinates look plausible for spot-checked buildings.

---

## 6. Suggested order of work (starting proposal)

1. **Correctness fixes in core:** multi-meeting parsing, hard walk/gap feasibility, exclude lectures from `assoc`, fix quiz-penalty condition, handle TBA/empty-days/weekend meetings.
2. **`TravelModel` class:** walk + bus + fallback to walk, no negative caching, explicit errors surfaced to the UI, deterministic departure date/time, cache keyed by provider/term/date.
3. **Search rewrite:** hard checks separated from soft cost; DFS with pruning; top-N heap; `walk_min` cache. Do this before gen ed.
4. **Parity test:** run PHYS 212, TAM 210, CS 101, MATH 314 through `planner_core` and `solve.py`; top results should match once section filters (e.g. MATH 314 AL1/BL1, CS 101 first lecture) are applied via a lock/allow mechanism.
5. **Unit tests on pure functions:** `parse_time`, `bundles_for_course`, `score_schedule` (gap 0 + walk 8, empty-days meeting, TBA time), time-input validation.
6. **GUI robustness:** input validation before disabling the button; geocoding off the Tk thread; cache CIS responses to disk.
7. **Normalize scoring** into "equivalent minutes" with slider multipliers; fix the gap=20 cliff and the bus incentive.
8. **Reconcile `DESIGN.md`** with what is actually built; decide which unbuilt features (gen ed, lock section, export, hover) are in scope.

---

## 7. Questions the planner should resolve with the author

1. Is walk limit a hard cap (per `DESIGN.md` and `solve.py`) or a soft preference? Recommendation: hard cap plus the gap check.
2. Should lectures past latest end be rejected outright (per `DESIGN.md`)?
3. Is bus routing in scope, or should it be cut as `DESIGN.md` suggests? If kept, which provider is primary?
4. How should per-course section filters (MATH 314 AL1/BL1, CS 101 first lecture) be expressed: config file, GUI "lock/allow" field, or both?
5. Target scale: how many courses and sections per run? This decides whether DFS + heap suffices or branch-and-bound is needed.
6. Should closed or full sections be excluded or flagged?
7. Is gen ed scanning (`scan.py`) to be ported into the GUI, and if so should it reuse the incremental solver against precomputed core schedules?

---

## 8. Deliverable requested from the planner

A phased implementation plan with: module/file layout, function signatures for the hard-check/soft-cost split and `TravelModel`, data-model changes (one record per meeting, section type taxonomy, per-course overrides), test plan with the parity test as the gate for the search rewrite, and an explicit list of `DESIGN.md` items to keep, change, or drop.
