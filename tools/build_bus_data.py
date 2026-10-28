"""Build bus_data.json from MTD's public GTFS feed (no API key).

Run once per semester (MTD changes schedules for fall/spring/summer):
    python tools/build_bus_data.py

For every pair of campus stops served by the same bus trip, it stores the
average ride time and the average wait (half the time between buses) for
weekday trips leaving between 9:00 and 17:00 on the busiest Wednesday in the feed.
"""
import csv, io, json, os, sys, zipfile, datetime, urllib.request
from collections import defaultdict

URL = "https://developer.mtd.org/gtfs/google_transit.zip"
BBOX = (40.095, 40.120, -88.245, -88.215)  # lat min/max, lon min/max: campus core
WINDOW = (9 * 60, 17 * 60)
OUT = os.path.join(os.path.dirname(__file__), "..", "bus_data.json")


def rows(z, name):
    return csv.DictReader(io.TextIOWrapper(z.open(name), encoding="utf-8-sig"))


def busiest_wednesday(z, trips_per_service):
    cal = list(rows(z, "calendar.txt"))
    extra = defaultdict(lambda: ([], []))  # date -> (added, removed)
    for r in rows(z, "calendar_dates.txt"):
        extra[r["date"]][0 if r["exception_type"] == "1" else 1].append(r["service_id"])
    start = min(r["start_date"] for r in cal)
    end = max(r["end_date"] for r in cal)
    d = datetime.datetime.strptime(start, "%Y%m%d").date()
    d += datetime.timedelta(days=(2 - d.weekday()) % 7)
    best = (0, None, set())
    while d.strftime("%Y%m%d") <= end:
        ds = d.strftime("%Y%m%d")
        active = {r["service_id"] for r in cal if r["wednesday"] == "1" and r["start_date"] <= ds <= r["end_date"]}
        active |= set(extra[ds][0])
        active -= set(extra[ds][1])
        n = sum(trips_per_service.get(s, 0) for s in active)
        if n > best[0]:
            best = (n, ds, active)
        d += datetime.timedelta(days=7)
    return best


def mins(t):
    h, m, _ = t.split(":")
    return int(h) * 60 + int(m)


def main(path=None):
    if path is None:
        path = "gtfs.zip"
        print("Downloading", URL)
        urllib.request.urlretrieve(URL, path)
    z = zipfile.ZipFile(path)

    trip_service = {r["trip_id"]: r["service_id"] for r in rows(z, "trips.txt")}
    per_service = defaultdict(int)
    for s in trip_service.values():
        per_service[s] += 1
    n, date, active = busiest_wednesday(z, per_service)
    print(f"Using {date}: {n} trips")

    stops = {}
    for r in rows(z, "stops.txt"):
        if r.get("location_type", "0") not in ("", "0"):
            continue
        lat, lon = float(r["stop_lat"]), float(r["stop_lon"])
        if BBOX[0] <= lat <= BBOX[1] and BBOX[2] <= lon <= BBOX[3]:
            stops[r["stop_id"]] = (round(lat, 6), round(lon, 6))

    by_trip = defaultdict(list)
    for r in rows(z, "stop_times.txt"):
        if r["stop_id"] in stops and trip_service.get(r["trip_id"]) in active:
            by_trip[r["trip_id"]].append((int(r["stop_sequence"]), r["stop_id"], mins(r["arrival_time"]), mins(r["departure_time"])))

    agg = defaultdict(lambda: [0, 0])  # (a, b) -> [ride minutes sum, departures]
    for seq in by_trip.values():
        seq.sort()
        for i, (_, a, _, dep) in enumerate(seq):
            if not WINDOW[0] <= dep <= WINDOW[1]:
                continue
            seen = set()
            for _, b, arr, _ in seq[i + 1:]:
                if b != a and b not in seen:  # first arrival only (loops revisit stops)
                    seen.add(b)
                    agg[(a, b)][0] += arr - dep
                    agg[(a, b)][1] += 1

    span = WINDOW[1] - WINDOW[0]
    pairs = defaultdict(dict)
    for (a, b), (ride, cnt) in agg.items():
        if cnt >= 4:  # at least one bus every two hours
            pairs[a][b] = [round(ride / cnt, 1), round(min(span / cnt / 2, 15), 1)]
    used = set(pairs) | {b for d in pairs.values() for b in d}
    out = {"source": URL, "date": date, "stops": {s: stops[s] for s in used}, "pairs": pairs}
    json.dump(out, open(OUT, "w"), separators=(",", ":"))
    print(f"Wrote {OUT}: {len(used)} stops, {sum(len(d) for d in pairs.values())} pairs")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
