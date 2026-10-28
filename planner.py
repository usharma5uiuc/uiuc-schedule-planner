"""UIUC Schedule Planner: pick your classes, get the best week."""

import re, sys, threading, queue, datetime, ctypes
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, font as tkfont
import planner_core as core

ORANGE, BLUE, GRAY, SUPPORT = "#FF5F05", "#13294B", "#707372", "#1E56A0"
BG, PANEL, LINE, TEXT, MUTED = "#F7F5F2", "#FFFFFF", "#E3E0DB", "#13294B", "#707372"
COURSE_COLORS = ["#FF5F05", "#1E56A0", "#13294B", "#C84113", "#5E7CA6", "#707372", "#E8914F", "#2C6E6A"]
TIMES = [h * 60 + m for h in range(7, 22) for m in (0, 30)]


def fmt(mins):
    h, m = divmod(mins, 60)
    return f"{(h - 1) % 12 + 1}:{m:02} {'AM' if h < 12 else 'PM'}"


def load_fonts():
    """Use Source Sans 3 (close to UIUC's web type) from the bundled files; fall back to Segoe UI."""
    if sys.platform == "win32":
        for w in ("Regular", "Semibold", "Bold"):
            ctypes.windll.gdi32.AddFontResourceExW(core.resource(f"fonts/SourceSans3-{w}.ttf"), 0x10, 0)  # FR_PRIVATE


class Planner(tk.Tk):
    def __init__(self):
        load_fonts()
        super().__init__()
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # crisp text on high-DPI screens
        except Exception:
            pass
        fam = "Source Sans 3" if "Source Sans 3" in tkfont.families() else "Segoe UI"
        self.f = {k: (fam, s, w) for k, s, w in [("body", 11, "normal"), ("small", 10, "normal"), ("bold", 11, "bold"),
                                                ("h2", 13, "bold"), ("h1", 18, "bold"), ("block", 9, "normal"),
                                                ("blockb", 9, "bold")]}
        self.title("UIUC Schedule Planner")
        self.geometry("1280x820")
        self.minsize(1050, 680)
        self.configure(bg=BG)
        core.load_geo()
        core.load_bus()
        self.classes, self.results, self.current = [], [], None
        self.q, self.coord_q = queue.Queue(), queue.Queue()
        self._style()
        self._build()
        self.after(100, self._poll)

    # ---- look -------------------------------------------------------------
    def _style(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure(".", font=self.f["body"], background=PANEL, foreground=TEXT)
        s.configure("TFrame", background=PANEL)
        s.configure("Bg.TFrame", background=BG)
        s.configure("TLabel", background=PANEL, foreground=TEXT)
        s.configure("Muted.TLabel", foreground=MUTED, font=self.f["small"])
        s.configure("H2.TLabel", font=self.f["h2"])
        s.configure("TCombobox", fieldbackground="white", padding=4)
        s.configure("TSpinbox", fieldbackground="white", padding=4, arrowsize=12)
        s.configure("TEntry", fieldbackground="white", padding=6)
        s.configure("Horizontal.TScale", background=PANEL, troughcolor=LINE)
        s.configure("TCheckbutton", background=PANEL, foreground=TEXT, font=self.f["small"])
        s.map("TCheckbutton", background=[("active", PANEL)])
        s.configure("Go.TButton", font=self.f["h2"], background=ORANGE, foreground="white", padding=(10, 10), borderwidth=0)
        s.map("Go.TButton", background=[("disabled", "#F4B08A"), ("active", "#E85500")])
        s.configure("Add.TButton", background=BLUE, foreground="white", padding=(10, 5), borderwidth=0)
        s.map("Add.TButton", background=[("active", SUPPORT)])
        s.configure("Plain.TButton", background=PANEL, foreground=BLUE, padding=(8, 4), bordercolor=LINE)
        s.map("Plain.TButton", background=[("active", BG)])

    def _build(self):
        header = tk.Frame(self, bg=BLUE, height=58)
        header.pack(fill="x")
        tk.Label(header, text="I", bg=BLUE, fg=ORANGE, font=(self.f["h1"][0], 24, "bold")).pack(side="left", padx=(18, 8))
        tk.Label(header, text="UIUC Schedule Planner", bg=BLUE, fg="white", font=self.f["h1"]).pack(side="left")
        tk.Label(header, text="Unofficial student tool · not affiliated with the University of Illinois",
                 bg=BLUE, fg="#AEB8C8", font=self.f["small"]).pack(side="right", padx=18)
        tk.Frame(self, bg=ORANGE, height=4).pack(fill="x")

        body = ttk.Frame(self, style="Bg.TFrame", padding=14)
        body.pack(fill="both", expand=True)
        left = ttk.Frame(body, padding=16, width=360)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        right = ttk.Frame(body, style="Bg.TFrame")
        right.pack(side="left", fill="both", expand=True, padx=(14, 0))

        # term
        ttk.Label(left, text="Semester", style="H2.TLabel").pack(anchor="w")
        row = ttk.Frame(left); row.pack(fill="x", pady=(4, 14))
        today = datetime.date.today()
        self.term = ttk.Combobox(row, values=["Spring", "Summer", "Fall"], state="readonly", width=9)
        self.term.set("Spring" if today.month >= 8 or today.month <= 2 else "Fall")
        self.term.pack(side="left")
        self.year = ttk.Spinbox(row, from_=today.year - 1, to=today.year + 2, width=6)
        self.year.set(today.year + (1 if today.month >= 8 else 0))
        self.year.pack(side="left", padx=8)

        # classes
        ttk.Label(left, text="Your classes", style="H2.TLabel").pack(anchor="w")
        row = ttk.Frame(left); row.pack(fill="x", pady=(4, 2))
        self.entry = ttk.Entry(row)
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<Return>", lambda e: self._add_class())
        ttk.Button(row, text="Add", style="Add.TButton", command=self._add_class).pack(side="left", padx=(6, 0))
        ttk.Label(left, text="Type a class like  PHYS 212  and press Enter.", style="Muted.TLabel").pack(anchor="w")
        self.chips = ttk.Frame(left); self.chips.pack(fill="x", pady=(8, 14))

        # preferences
        ttk.Label(left, text="Preferences", style="H2.TLabel").pack(anchor="w")
        grid = ttk.Frame(left); grid.pack(fill="x", pady=(4, 6))
        labels = [fmt(t) for t in TIMES]
        self.earliest = self._pick(grid, "No classes before", labels, fmt(600), 0)
        self.latest = self._pick(grid, "No classes after", labels, fmt(960), 1)
        self.max_walk = self._spin(grid, "Longest walk (min)", 9, 2, 20, 2)
        self.max_bus = self._spin(grid, "Longest bus trip (min)", 12, 0, 30, 3)
        ttk.Label(left, text="Labs that start before your cutoff may run past it. Bus times come from\n"
                             "MTD's schedule and include walking to the stop and waiting.",
                  style="Muted.TLabel", justify="left").pack(anchor="w", pady=(0, 10))

        self.honors = tk.BooleanVar(value=False)
        ttk.Checkbutton(left, text="Include honors / permission-only sections", variable=self.honors).pack(anchor="w", pady=(0, 10))

        ttk.Label(left, text="What matters most", style="H2.TLabel").pack(anchor="w")
        self.sliders = {}
        for key, label, default in [("gap_weight", "Fewer gaps between classes", 2),
                                    ("friday_weight", "Lighter Fridays", 3),
                                    ("quiz_weight", "Quiz sections later in the week", 1),
                                    ("walk_weight", "Shorter walks", 2)]:
            r = ttk.Frame(left); r.pack(fill="x", pady=2)
            ttk.Label(r, text=label, font=self.f["small"]).pack(side="left")
            sc = ttk.Scale(r, from_=0, to=5, length=110)
            sc.set(default)
            sc.pack(side="right")
            self.sliders[key] = sc

        self.go = ttk.Button(left, text="Find my schedule", style="Go.TButton", command=self.find)
        self.go.pack(fill="x", side="bottom")
        self.status = ttk.Label(left, text="", style="Muted.TLabel", wraplength=320, justify="left")
        self.status.pack(side="bottom", anchor="w", pady=(0, 8))

        # results strip
        top = ttk.Frame(right, padding=(14, 10)); top.pack(fill="x")
        ttk.Label(top, text="Options", style="H2.TLabel").pack(side="left")
        self.pick = ttk.Combobox(top, state="readonly", width=70)
        self.pick.pack(side="left", padx=10, fill="x", expand=True)
        self.pick.bind("<<ComboboxSelected>>", lambda e: self._select(self.pick.current()))

        cal = ttk.Frame(right, padding=8); cal.pack(fill="both", expand=True, pady=(10, 0))
        self.canvas = tk.Canvas(cal, bg=PANEL, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self._draw())
        self.tip = tk.Label(self, bg=BLUE, fg="white", font=self.f["small"], justify="left", padx=8, pady=5)

        bottom = ttk.Frame(right, padding=(14, 10)); bottom.pack(fill="x", pady=(10, 0))
        ttk.Label(bottom, text="CRNs", style="H2.TLabel").pack(side="left")
        self.crns = tk.StringVar()
        ttk.Entry(bottom, textvariable=self.crns, state="readonly", font=self.f["bold"]).pack(
            side="left", fill="x", expand=True, padx=10)
        ttk.Button(bottom, text="Copy", style="Add.TButton", command=self._copy).pack(side="left")
        self.online = ttk.Label(right, text="", style="Muted.TLabel", background=BG)
        self.online.pack(anchor="w", pady=(6, 0))
        self._empty_state()

    def _pick(self, parent, label, values, default, row):
        ttk.Label(parent, text=label, font=self.f["small"]).grid(row=row, column=0, sticky="w", pady=3)
        cb = ttk.Combobox(parent, values=values, state="readonly", width=10)
        cb.set(default)
        cb.grid(row=row, column=1, sticky="e", pady=3)
        parent.columnconfigure(0, weight=1)
        return cb

    def _spin(self, parent, label, default, lo, hi, row):
        ttk.Label(parent, text=label, font=self.f["small"]).grid(row=row, column=0, sticky="w", pady=3)
        sp = ttk.Spinbox(parent, from_=lo, to=hi, width=5)
        sp.set(default)
        sp.grid(row=row, column=1, sticky="e", pady=3)
        return sp

    # ---- classes ----------------------------------------------------------
    def _add_class(self):
        raw = self.entry.get().strip().upper()
        if not raw:
            return
        for part in re.split(r"[,;]+", raw):
            m = re.match(r"^\s*([A-Z]{2,5})\s*-?\s*(\d{3})\s*$", part)
            if not m:
                self._say(f"“{part.strip()}” doesn't look like a class. Try something like CS 101.")
                return
            c = (m.group(1), m.group(2))
            if c not in self.classes:
                self.classes.append(c)
        self.entry.delete(0, "end")
        self._say("")
        self._chips()

    def _chips(self):
        for w in self.chips.winfo_children():
            w.destroy()
        row = None
        for i, (subj, num) in enumerate(self.classes):
            if i % 3 == 0:
                row = ttk.Frame(self.chips); row.pack(fill="x", pady=2)
            chip = tk.Frame(row, bg=BG, highlightbackground=LINE, highlightthickness=1)
            chip.pack(side="left", padx=(0, 6))
            tk.Label(chip, text=f"{subj} {num}", bg=BG, fg=BLUE, font=self.f["bold"]).pack(side="left", padx=(8, 2), pady=3)
            x = tk.Label(chip, text="×", bg=BG, fg=GRAY, font=self.f["h2"], cursor="hand2")
            x.pack(side="left", padx=(2, 6))
            x.bind("<Button-1>", lambda e, c=(subj, num): self._remove(c))

    def _remove(self, c):
        self.classes.remove(c)
        self._chips()

    # ---- search -----------------------------------------------------------
    def _prefs(self):
        return dict(earliest=TIMES[self.earliest.current()], latest=TIMES[self.latest.current()],
                    max_walk=float(self.max_walk.get()), max_bus=float(self.max_bus.get()),
                    **{k: float(s.get()) for k, s in self.sliders.items()})

    def find(self):
        if self.entry.get().strip():
            self._add_class()
        if not self.classes:
            self._say("Add at least one class first.")
            return
        try:
            prefs = self._prefs()
            year = int(self.year.get())
        except ValueError:
            self._say("Walk, bus, and year need to be numbers.")
            return
        if prefs["latest"] <= prefs["earliest"]:
            self._say("“No classes after” has to be later than “No classes before”.")
            return
        self.go.config(state="disabled")
        self._say("Looking up sections…")
        args = (year, self.term.get().lower(), list(self.classes), prefs, not self.honors.get())
        threading.Thread(target=self._run, args=args, daemon=True).start()

    def _run(self, year, term, classes, prefs, skip_restricted):
        try:
            bundles = []
            for subj, num in classes:
                self.q.put(("status", f"Looking up {subj} {num}…"))
                secs = core.fetch_course(year, term, subj, num, skip_restricted)
                if not secs:
                    self.q.put(("error", f"{subj} {num} isn't offered in {term.title()} {year} (or the schedule isn't posted yet)."))
                    return
                bundles.append(core.bundles_for_course(secs))
            buildings = sorted({m["b"] for g in bundles for b in g for m in b if m["b"]})
            missing = [b for b in buildings if not core.has_coord(b)]
            if missing:
                self.q.put(("status", f"Finding {len(missing)} building(s) on the map…"))
                found = {b: core.geocode(b) for b in missing}
                unknown = [b for b, c in found.items() if not c]
                if unknown:
                    self.q.put(("ask", unknown))
                    found.update(self.coord_q.get())
                if any(c is None for c in found.values()):
                    self.q.put(("error", "Can't plan walks without every building's location."))
                    return
                for b, c in found.items():
                    core.set_coord(b, *c)
            self.q.put(("status", "Comparing schedules…"))
            self.q.put(("results", core.search(bundles, prefs)))
        except OSError:
            self.q.put(("error", "Couldn't reach courses.illinois.edu. Check your internet connection."))
        except Exception as e:
            self.q.put(("error", f"Something went wrong: {e}"))

    def _poll(self):
        try:
            while True:
                kind, data = self.q.get_nowait()
                if kind == "status":
                    self._say(data)
                elif kind == "error":
                    self._say(data)
                    self.go.config(state="normal")
                elif kind == "ask":
                    self.coord_q.put(self._ask_coords(data))
                elif kind == "results":
                    self._show(data)
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _ask_coords(self, buildings):
        out = {}
        for b in buildings:
            while True:
                text = simpledialog.askstring(
                    "Where is this building?",
                    f"I couldn't find “{b}” on the map.\nType its street address, or a nearby building's name:",
                    parent=self)
                if text is None:
                    out[b] = None
                    break
                m = re.match(r"^\s*(-?\d+\.\d+)\s*,\s*(-?\d+\.\d+)\s*$", text)
                c = (float(m.group(1)), float(m.group(2))) if m else core.geocode(text)
                if c:
                    out[b] = c
                    break
                messagebox.showinfo("Not found", f"Couldn't find “{text}”. Try a street address.", parent=self)
        return out

    # ---- results ----------------------------------------------------------
    def _show(self, data):
        self.go.config(state="normal")
        self.results = data
        if not data:
            self.pick.set("")
            self.pick["values"] = []
            self.current = None
            self._empty_state("No schedule fits these rules.\nTry a later cutoff or a longer walk.")
            self._say("No schedule fits. Loosen a preference and try again.")
            return
        items = []
        for i, (_, worst, _, m) in enumerate(data, 1):
            s = core.summarize(m)
            h, mm = divmod(s["idle"], 60)
            gaps = f"{h}h {mm}m" if h and mm else f"{h}h" if h else f"{mm}m"
            items.append(f"Option {i}   ·   {s['fri']} Friday class{'es' if s['fri'] != 1 else ''}"
                         f"   ·   {gaps} of gaps a week   ·   longest trip {worst:.0f} min")
        self.pick["values"] = items
        self.pick.current(0)
        self._select(0)
        self._say(f"Found {len(data)} options. Option 1 fits your preferences best.")

    def _select(self, i):
        if i < 0 or i >= len(self.results):
            return
        _, _, self.trips, self.current = self.results[i]
        self.crns.set("  ".join(dict.fromkeys(m["crn"] for m in self.current)))
        online = sorted({f"{m['c']} {m['n']}" for m in self.current if m["online"]})
        self.online.config(text=("Online / no set time: " + ", ".join(online)) if online else "")
        self._draw()

    def _empty_state(self, msg="Add your classes on the left, then press  Find my schedule."):
        c = self.canvas
        c.delete("all")
        c.create_text(max(c.winfo_width(), 600) / 2, max(c.winfo_height(), 400) / 2, text=msg,
                      fill=MUTED, font=self.f["h2"], justify="center")

    def _draw(self):
        if not self.current:
            return self._empty_state() if not self.results else None
        c = self.canvas
        c.delete("all")
        live = [m for m in self.current if not m["online"]]
        start = min([m["s"] for m in live] + [600]) // 60 * 60
        end = -(-max([m["e"] for m in live] + [960]) // 60) * 60
        W, H = max(c.winfo_width(), 400), max(c.winfo_height(), 300)
        L, T, R, B = 64, 36, W - 12, H - 10
        cw, ph = (R - L) / 5, (B - T) / (end - start)
        y = lambda t: T + (t - start) * ph
        for i, d in enumerate(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]):
            c.create_text(L + cw * i + cw / 2, T - 16, text=d, fill=BLUE, font=self.f["bold"])
            c.create_line(L + cw * i, T, L + cw * i, B, fill=LINE)
        for t in range(start, end + 1, 60):
            c.create_line(L, y(t), R, y(t), fill=LINE)
            c.create_text(L - 8, y(t), text=fmt(t).replace(":00", ""), anchor="e", fill=MUTED, font=self.f["small"])
        colors = {}
        for m in live:
            colors.setdefault(m["c"], COURSE_COLORS[len(colors) % len(COURSE_COLORS)])
        for m in live:
            for d in m["days"]:
                i = core.DAYS.index(d)
                x0, x1, y0, y1 = L + cw * i + 3, L + cw * (i + 1) - 3, y(m["s"]) + 1, y(m["e"]) - 1
                tag = f"b{id(m)}{d}"
                c.create_rectangle(x0, y0, x1, y1, fill=colors[m["c"]], outline="", tags=tag)
                kind = m["type"].replace("Discussion/Recitation", "Discussion").replace("Lecture-Discussion", "Lecture")
                c.create_text(x0 + 6, y0 + 4, anchor="nw", fill="white", font=self.f["blockb"], text=m["c"], tags=tag)
                if y1 - y0 > 34:
                    c.create_text(x0 + 6, y0 + 19, anchor="nw", fill="white", font=self.f["block"], tags=tag,
                                  text=f"{kind}\n{m['b']}", width=x1 - x0 - 10)
                info = (f"{m['c']}  {m['n']}  ·  CRN {m['crn']}\n{kind}\n{fmt(m['s'])} – {fmt(m['e'])}\n{m['b']}")
                c.tag_bind(tag, "<Enter>", lambda e, t=info: self._tip(e, t))
                c.tag_bind(tag, "<Motion>", lambda e, t=info: self._tip(e, t))
                c.tag_bind(tag, "<Leave>", lambda e: self.tip.place_forget())
        by_crn = {}
        for m in live:
            by_crn.setdefault(m["crn"], []).append(m)
        for (d, a, b), (mins, mode) in self.trips.items():
            ma = next(m for m in by_crn[a] if d in m["days"])
            i = core.DAYS.index(d)
            c.create_text(L + cw * i + cw - 8, y(ma["e"]) + 1, anchor="ne", fill=BLUE, font=self.f["blockb"],
                          text=f"{'walk' if mode == 'walk' else 'bus'} {mins:.0f} min")

    def _tip(self, e, text):
        self.tip.config(text=text)
        x = e.x_root - self.winfo_rootx() + 14
        y = e.y_root - self.winfo_rooty() + 14
        self.tip.place(x=min(x, self.winfo_width() - 260), y=min(y, self.winfo_height() - 90))
        self.tip.lift()

    def _copy(self):
        if self.crns.get():
            self.clipboard_clear()
            self.clipboard_append(self.crns.get().replace("  ", " "))
            self._say("CRNs copied. Paste them into Banner's “Enter CRNs” tab.")

    def _say(self, text):
        self.status.config(text=text)


if __name__ == "__main__":
    Planner().mainloop()
