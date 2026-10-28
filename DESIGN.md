# UIUC Schedule Planner — Design

A desktop app: type in the classes you want, it pulls every section from the UIUC CIS API, finds the best combination under your rules, and draws the week.

## What you'd see

```
┌───────────────────────────────────────────────────────────────┐
│ Term: [Spring ▾] [2027]                                       │
│ Classes: [PHYS 212] [TAM 210] [CS 101] [MATH 314] [+ Add]     │
│ Gen ed slot: [Hum + Western ▾]  (optional, scans all matches) │
├───────────────────────────────────────────────────────────────┤
│ Rules                                                         │
│  Earliest start [10:00]   Latest end [4:00]                   │
│  [x] Labs may run past latest end if they start before it     │
│  Max walk between back-to-back classes [9] min                │
│  Priorities:  Small gaps ▮▮▮▯  Light Friday ▮▮▮▮              │
│               Quizzes late in week ▮▯▯▯   Short walks ▮▮▯▯     │
│  Lock a section: [MACS 100 ADC]                               │
│                                   [ Find schedules ]          │
├───────────────────────────────────────────────────────────────┤
│ Results (best first)      │  Mon  Tue  Wed  Thu  Fri          │
│ ▸ #1  gaps 6h  Fri 2  7.4m│  ██   ██        ██   ██  10am     │
│   #2  gaps 6h  Fri 2  7.4m│  ██   ██   ██        ██  11am     │
│   #3  ...                 │  ...  calendar grid, color/class  │
│                           │  hover a block → room, CRN, walk  │
├───────────────────────────────────────────────────────────────┤
│ CRNs: 38029 56034 38105 36212 ...   [Copy]  [Export .txt]     │
└───────────────────────────────────────────────────────────────┘
```

## How it works

1. **Fetch sections**: `GET https://courses.illinois.edu/cisapp/explorer/schedule/{year}/{term}/{SUBJ}/{NUM}.xml?mode=detail`. Responses are cached to disk so re-runs don't re-download.
2. **Build bundles per class**: one lecture plus one of each other section type (discussion, lab). Links are read from the section notes (e.g. PHYS 212's "must also enroll in lecture section A1") and from the letter prefix (MATH 314's A-lecture goes with AD_ discussions).
3. **Gen ed slot (optional)**: searches Course Explorer for the chosen categories (e.g. `gened1=1WCC&gened2=1LA`), drops cross-listed duplicates by title, and tests each course in the open slot.
4. **Hard rules** (combination is thrown out if broken):
   - no time conflicts
   - nothing starts before the earliest start
   - nothing ends after the latest end, except labs/discussions that start before it
   - walk time between classes with a gap ≤ 20 min stays under the max
5. **Score** (lower is better, weighted by the sliders):
   - idle minutes between classes, beyond a 10-min passing period
   - number of Friday meetings
   - quiz/exam sections early in the week (discussions, labs)
   - total tight-walk minutes
6. **Show the top results**. Clicking one draws the calendar and fills in the CRN list.

## Walk times

- Building locations come from OpenStreetMap (Nominatim), cached in `geo.json`. The app asks you to place a building by hand if it can't be found.
- Walk = straight-line distance × 1.3 for paths, at 80 m/min. These are estimates; a real route can differ by a minute or two.
- Bus routing (MTD API) is left out for now. The walking estimate already covers campus-core trips. Add it if you need routes to far buildings.

## Speed

Every combination is tried, which can mean millions for classes with many sections, like PHYS 212. To keep it fast:
- the core classes are solved once
- the gen ed options are tested against only the core schedules that passed
- combinations are checked as they're built, so dead ends are dropped early

## Build plan (lean)

- One file, `planner.py`, using Python's built-in tkinter, so nothing to install.
- It reuses the logic in `solve.py` / `scan.py` / `compact.py` (loading, bundling, scoring, walk times) as functions instead of scripts.
- The calendar is drawn as a tkinter Canvas grid.
- Copy-to-clipboard for the CRNs, ready for Banner's "Enter CRNs" tab.
- Left out: live seat counts, Banner login or auto-registration, bus routing. Add them if you need them.

## Limits

- It only knows what's in the CIS API at the time you run it. Seat counts and rooms can change.
- It doesn't check prerequisites or major restrictions. Course Explorer notes them, but Banner enforces them at registration.
- Walk times are estimates, so check tight transfers on a map.
