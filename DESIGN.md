# UIUC Schedule Planner: Design

A desktop app: add the classes you want, it pulls every section from the UIUC Course Explorer API, finds the best combination under your rules, and draws the week. No API keys, no install.

## Layout

```
┌───────────────────────────────────────────────────────────────────┐
│ ▌UIUC Schedule Planner          Unofficial student tool · …        │
├──────────────────────────┬────────────────────────────────────────┤
│ Semester  [Spring▾][2027]│ Options [Option 1 · 2 Friday classes ▾]│
│ Your classes             │                                        │
│ [ PHYS 212        ][Add] │   Mon   Tue   Wed   Thu   Fri          │
│ (PHYS 212 ×)(CS 101 ×)   │   ███         ███         ███  11 AM   │
│ Preferences              │         ███  walk 3 min                │
│  No classes before [10AM]│   ...  colored blocks per course,      │
│  No classes after  [4PM] │        walk/bus time between classes,  │
│  Longest walk / bus trip │        hover a block for CRN and room  │
│  [ ] Include honors      │                                        │
│ What matters most        ├────────────────────────────────────────┤
│  sliders ×4              │ CRNs  [77737 31018 …]          [Copy]  │
│ [ Find my schedule ]     │ Online / no set time: …                │
└──────────────────────────┴────────────────────────────────────────┘
```

Illinois Orange `#FF5F05` and Illinois Blue `#13294B`, with Source Sans 3 bundled in the app.

## Pipeline (`planner_core.py`)

1. **Fetch**: `GET courses.illinois.edu/cisapp/explorer/schedule/{year}/{term}/{SUBJ}/{NUM}.xml?mode=detail`.
   - Every `<meeting>` is read, so sections that meet at more than one time or room are fully covered.
   - Online, TBA, and weekend-only meetings have no time slot to check.
   - Honors and permission-only sections are skipped by default: `HON*` section numbers, or notes mentioning consent, an application, or a form.
2. **Bundle**: one lecture section plus one section of each other component.
   - Components are matched by the "must also enroll in lecture section X" note, or else by the section letter prefix.
   - Online and in-person discussions count as the same component, so a course never gets two.
   - Lectures are never paired with other lectures.
3. **Locate buildings**: `geo.json` ships with the app.
   - Unknown buildings are looked up on OpenStreetMap and saved to `%APPDATA%\UIUC Schedule Planner\geo.json`.
   - If OpenStreetMap can't find one, the app asks for an address.
4. **Travel between back-to-back classes**:
   - Walk = straight-line distance × 1.3, at 80 m/min.
   - Walks under 10 minutes are always walked.
   - Longer trips also consider the bus, using `bus_data.json`. The bus time is the fastest direct trip between stops within 400 m of each building: walk to the stop + average wait + average ride + walk from the stop.
   - The trip has to fit the walk or bus limit **and** finish at least a minute before the next class starts.
5. **Hard rules**: no conflicts, nothing before the start time, and nothing past the end time except labs/discussions that start before it. The travel rules above also apply.
6. **Score**, in "equivalent idle minutes" scaled by the sliders:
   - gap minutes beyond a 10-minute passing period
   - 40 × weight per Friday meeting (the default slider makes each Friday class cost about 2 hours of gaps)
   - quiz sections (any section listed as Discussion or Quiz) early in the week
   - travel minutes
7. **Search**: depth-first over courses, fewest choices first.
   - A partial schedule that already breaks a hard rule is dropped, since adding classes can't fix it.
   - The best 50 are kept in a heap.
   - A typical 5-class semester takes about 2 seconds.

## Bus data (`tools/build_bus_data.py`)

Built offline from MTD's public GTFS feed:
- It picks the busiest Wednesday in the feed and keeps weekday trips leaving between 9:00 and 17:00.
- For every pair of campus stops on the same trip, it stores the average ride and the average wait (half the time between buses, capped at 15 min).
- Pairs with fewer than 4 buses in that window are dropped.

Rerun it each semester.

## Packaging

PyInstaller `--onefile --windowed`, bundling `geo.json`, `bus_data.json`, and `fonts/`. The result is a single ~12 MB exe, published as a GitHub Release asset, not committed. Bundled files are found through `sys._MEIPASS`. Learned data is written to `%APPDATA%`.

## Not included

- **Seat counts:** check them in Course Explorer.
- **Prerequisite checks:** Banner enforces these at registration.
- **Live bus times:** the planner uses schedule averages, which is enough for planning a semester.
- **Transfers:** bus trips with a transfer are skipped, since a transfer never fits a passing period.
- **macOS build:** it runs from source. A GitHub Actions job could build a Mac version if anyone asks.
