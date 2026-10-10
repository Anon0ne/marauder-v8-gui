#!/usr/bin/env python3
"""
marauder_gui.py — clean desktop GUI for the ESP32 Marauder (V8).

Mirrors the on-device menu: commands are grouped by radio (WiFi / Bluetooth)
and category in a navigation tree. Selecting a command builds a parameter form;
the live command string and a Send button sit above a help panel that explains
the selected command. A live serial console runs along the bottom with optional
CSV logging of scan results, plus a PCAP inspector.

Run:
    pip install pyserial
    python marauder_gui.py

Only pyserial is required; the GUI uses Python's built-in tkinter.
Companion files (same folder): marauder.py, marauder_commands.py, marauder_pcap.py

Authorized use only: run active commands (deauth, beacon/BLE spam) exclusively
against devices and networks you own or have explicit written permission to test.
"""

from __future__ import annotations

import os
import re
import csv
import sys
import queue
import threading
import webbrowser
import datetime as _dt

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

__version__ = "0.1.0"
AUTHOR = "Justin Funderburk"
CONTACT = "justin@bizhostnc.com"

# Make companion modules importable regardless of the launch directory.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import serial  # noqa: F401  (pyserial presence check)
    from serial.tools import list_ports
except ImportError:
    sys.exit("pyserial is required.  Install it with:  pip install pyserial")

from marauder import Marauder, BAUD
from marauder_commands import CATALOG
import marauder_pcap


# --------------------------------------------------------------------------
# Theme
# --------------------------------------------------------------------------
PALETTE = {
    "bg":      "#0f141a",
    "panel":   "#161c24",
    "panel2":  "#1d2630",
    "entry":   "#0b1015",
    "fg":      "#e8edf2",
    "muted":   "#8b97a5",
    "accent":  "#2dd4bf",
    "accentfg":"#042f2a",
    "warn":    "#ff7b6b",
    "ok":      "#4ade80",
    "border":  "#2a3542",
}
MONO = ("Consolas", 10) if sys.platform == "win32" else ("Menlo", 11)
UI = ("Segoe UI", 10) if sys.platform == "win32" else ("Helvetica", 11)
UI_BOLD = (UI[0], 11, "bold")
UI_TITLE = (UI[0], 15, "bold")

# USB-UART bridge VIDs seen on ESP32 Marauder boards — used to auto-pick the port.
#   0x10C4 SiLabs CP210x · 0x1A86 WCH CH340/CH9102 · 0x0403 FTDI · 0x303A Espressif native USB
KNOWN_VIDS = {0x10C4, 0x1A86, 0x0403, 0x303A}

# Scan-line parsing: tolerant of the several Marauder output formats.
_MAC_RE = re.compile(r"([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})")
_RSSI_RE = re.compile(r"RSSI[:=\s]+(-?\d+)", re.I)
_CH_RE = re.compile(r"(?:\bCH|Channel|\bch)[:=\s]+(\d+)", re.I)
_SSID_RE = re.compile(r"SSID[:=\s]+(.+?)(?:\s+(?:BSSID|RSSI|CH|Channel)[:=]|$)", re.I)
_IP_RE = re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b")


def parse_scan_line(line: str):
    """Best-effort extraction of a scan row. Returns dict or None."""
    mac = _MAC_RE.search(line)
    rssi = _RSSI_RE.search(line)
    if not mac and not rssi:
        return None  # not a result row
    ssid = _SSID_RE.search(line)
    ch = _CH_RE.search(line)
    idx = re.match(r"\s*\[?(\d+)\]?[:\s]", line)
    # Guard: when the SSID is hidden/empty the loose regex can swallow the
    # following field (e.g. "BSSID: ..") — cut at the first known field word.
    ssid_val = ssid.group(1).strip() if ssid else ""
    ssid_val = re.split(r"\b(?:BSSID|RSSI|CH|Channel)\b", ssid_val)[0].strip(" :=\t")
    return {
        "ssid": ssid_val,
        "bssid": mac.group(1) if mac else "",
        "channel": ch.group(1) if ch else "",
        "rssi": rssi.group(1) if rssi else "",
        "index": idx.group(1) if idx else "",
    }


# Commands that run until explicitly stopped (scans, sniffs, attacks, spam…).
# A Stop button is surfaced for these and sending one logs a START event.
RUNNING_PREFIXES = ("sniff", "attack", "blespam", "scanall", "wardrive",
                    "mactrack", "packetcount", "nmea", "karma", "evilportal",
                    "arpscan", "pingscan", "portscan", "foxhunt")


def command_runs(base: str) -> bool:
    """True if `base` starts a long-running operation that needs a Stop."""
    toks = base.strip().split()
    if toks[:1] == ["recon"] and toks[1:2] in (["wifi"], ["ble"]):
        return True
    return base.strip().startswith(RUNNING_PREFIXES)


class MarauderGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"Marauder V8 — Control  v{__version__}")
        self.geometry("1180x780")
        self.minsize(960, 640)
        self.configure(bg=PALETTE["bg"])

        self.dev: Marauder | None = None
        self.reader_thread: threading.Thread | None = None
        self.reader_stop = threading.Event()
        self.rx_queue: queue.Queue[str] = queue.Queue()
        self._line_buf = ""

        self.csv_logging = tk.BooleanVar(value=False)
        self.csv_writer = None
        self.csv_file = None
        self.csv_seen = set()
        self.autoscroll = tk.BooleanVar(value=True)
        self.autoconnect = tk.BooleanVar(value=True)
        self._port_map = {}
        self._port_vids = {}      # device -> vid
        self._known_devices = set()
        self._connected_port = None
        self._autoconnect_tried = set()   # devices auto-connect already attempted

        self.running = False              # a long-running op is believed active
        self._last_running_base = ""      # base of the last START, for the right stop
        self._events_file = None
        self._events_path = None
        self._hosts = []                  # IPv4 hosts seen this session (ordered, unique)
        self._hosts_seen = set()

        # Live indexed lists feeding the pickers: ap/sta/ssid from `list -a/-s/-c`,
        # host from `arpscan`/`pingscan` output.
        self._lists = {"ap": {}, "sta": {}, "ssid": {}, "host": {}}
        self._host_n = 0
        self._parse_mode = None
        self._active_pickers = []         # [{tree, spec, lbl}] shown for current command

        self.current_cmd = None
        self.param_vars = []  # list of (spec, getter)
        self._entries = {}    # id(spec) -> Entry, so pickers can clear placeholders

        self._build_style()
        self._build_toolbar()
        self._build_body()
        self._build_console()

        self.refresh_ports()
        self.after(60, self._pump_rx)
        self.after(1500, self._poll_ports)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---- styling ---------------------------------------------------------
    def _build_style(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        p = PALETTE
        s.configure(".", background=p["panel"], foreground=p["fg"],
                    fieldbackground=p["entry"], bordercolor=p["border"],
                    font=UI)
        s.configure("TFrame", background=p["panel"])
        s.configure("Bg.TFrame", background=p["bg"])
        s.configure("Card.TFrame", background=p["panel2"])
        s.configure("TLabel", background=p["panel"], foreground=p["fg"])
        s.configure("Card.TLabel", background=p["panel2"], foreground=p["fg"])
        s.configure("Muted.TLabel", background=p["panel"], foreground=p["muted"])
        s.configure("CardMuted.TLabel", background=p["panel2"], foreground=p["muted"])
        s.configure("Title.TLabel", background=p["panel2"], foreground=p["fg"], font=UI_TITLE)
        s.configure("Warn.TLabel", background=p["panel2"], foreground=p["warn"], font=UI_BOLD)
        s.configure("TButton", background=p["panel2"], foreground=p["fg"],
                    bordercolor=p["border"], focusthickness=0, padding=6)
        s.map("TButton", background=[("active", p["border"])])
        s.configure("Accent.TButton", background=p["accent"], foreground=p["accentfg"],
                    font=UI_BOLD, padding=8)
        s.map("Accent.TButton", background=[("active", "#25b8a6"), ("disabled", p["border"])])
        s.configure("Stop.TButton", background=p["warn"], foreground="#3a0f0a",
                    font=UI_BOLD, padding=8)
        s.map("Stop.TButton", background=[("active", "#e86a5a"), ("disabled", p["panel2"])],
              foreground=[("disabled", p["muted"])])
        s.configure("TCheckbutton", background=p["panel"], foreground=p["fg"])
        s.map("TCheckbutton", background=[("active", p["panel"])])
        s.configure("Card.TCheckbutton", background=p["panel2"], foreground=p["muted"])
        s.map("Card.TCheckbutton", background=[("active", p["panel2"])])
        s.configure("TEntry", fieldbackground=p["entry"], foreground=p["fg"],
                    insertcolor=p["fg"], bordercolor=p["border"])
        s.configure("TCombobox", fieldbackground=p["entry"], foreground=p["fg"],
                    background=p["panel2"], arrowcolor=p["fg"])
        s.map("TCombobox", fieldbackground=[("readonly", p["entry"])])
        s.configure("Treeview", background=p["panel2"], fieldbackground=p["panel2"],
                    foreground=p["fg"], borderwidth=0, rowheight=24)
        s.map("Treeview", background=[("selected", p["accent"])],
              foreground=[("selected", p["accentfg"])])
        s.configure("Treeview.Heading", background=p["panel"], foreground=p["muted"])
        s.configure("TPanedwindow", background=p["bg"])
        s.configure("Vertical.TScrollbar", background=p["panel2"], troughcolor=p["bg"],
                    bordercolor=p["bg"], arrowcolor=p["muted"])
        s.configure("TNotebook", background=p["panel2"], borderwidth=0, tabmargins=(6, 4, 6, 0))
        s.configure("TNotebook.Tab", background=p["panel"], foreground=p["muted"],
                    padding=(14, 6), borderwidth=0)
        s.map("TNotebook.Tab", background=[("selected", p["panel2"])],
              foreground=[("selected", p["fg"])])
        s.configure("TMenubutton", background=p["panel2"], foreground=p["fg"],
                    arrowcolor=p["fg"], bordercolor=p["border"], padding=4)
        s.map("TMenubutton", background=[("active", p["border"])])

    # ---- toolbar ---------------------------------------------------------
    def _build_toolbar(self):
        bar = ttk.Frame(self, style="Bg.TFrame")
        bar.pack(side="top", fill="x", padx=12, pady=(10, 6))

        ttk.Label(bar, text="Port", style="Muted.TLabel",
                  background=PALETTE["bg"]).pack(side="left")
        self.port_cb = ttk.Combobox(bar, width=28, state="readonly")
        self.port_cb.pack(side="left", padx=(6, 4))
        ttk.Button(bar, text="⟳", width=3, command=self.refresh_ports).pack(side="left")

        ttk.Label(bar, text="Baud", style="Muted.TLabel",
                  background=PALETTE["bg"]).pack(side="left", padx=(14, 4))
        self.baud_cb = ttk.Combobox(bar, width=9, state="readonly",
                                    values=["9600", "115200", "230400", "921600"])
        self.baud_cb.set(str(BAUD))
        self.baud_cb.pack(side="left")

        self.connect_btn = ttk.Button(bar, text="Connect", style="Accent.TButton",
                                      command=self.toggle_connection)
        self.connect_btn.pack(side="left", padx=14)

        self.ac_chk = ttk.Checkbutton(bar, text="Auto-connect", variable=self.autoconnect)
        self.ac_chk.configure(style="TCheckbutton")
        # Checkbutton on the dark toolbar needs the Bg background.
        ttk.Style(self).configure("Bar.TCheckbutton", background=PALETTE["bg"],
                                  foreground=PALETTE["fg"])
        ttk.Style(self).map("Bar.TCheckbutton", background=[("active", PALETTE["bg"])])
        self.ac_chk.configure(style="Bar.TCheckbutton")
        self.ac_chk.pack(side="left")

        self.stop_all_btn = ttk.Button(bar, text="■ Stop", style="Stop.TButton",
                                       command=self.stop_running)
        self.stop_all_btn.pack(side="left", padx=(16, 0))

        self.status = ttk.Label(bar, text="● Disconnected", style="Muted.TLabel",
                                background=PALETTE["bg"])
        self.status.pack(side="left", padx=(12, 0))

        ttk.Button(bar, text="PCAP Inspector…",
                   command=self.open_pcap_dialog).pack(side="right")
        ttk.Button(bar, text="About", command=self.show_about).pack(side="right", padx=(0, 8))

    # ---- body: nav tree + builder ---------------------------------------
    def _build_body(self):
        self.vpane = ttk.Panedwindow(self, orient="vertical")
        self.vpane.pack(fill="both", expand=True, padx=12, pady=6)

        top = ttk.Panedwindow(self.vpane, orient="horizontal")
        self.vpane.add(top, weight=3)

        # Navigation tree
        navwrap = ttk.Frame(top, style="Card.TFrame")
        top.add(navwrap, weight=1)
        ttk.Label(navwrap, text="COMMANDS", style="CardMuted.TLabel",
                  font=UI_BOLD).pack(anchor="w", padx=12, pady=(10, 4))
        treewrap = ttk.Frame(navwrap, style="Card.TFrame")
        treewrap.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(treewrap, show="tree", selectmode="browse")
        vsb = ttk.Scrollbar(treewrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y", pady=(0, 10), padx=(0, 6))
        self.tree.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=(0, 10))
        self.tree.tag_configure("attack", foreground=PALETTE["warn"])
        self.tree.tag_configure("group", foreground=PALETTE["accent"])
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.cmd_by_iid = {}
        self._populate_tree()

        # Builder panel — scrollable so the Send button / help are never clipped
        # no matter how many parameters or how tall a picker a command has.
        build = ttk.Frame(top, style="Card.TFrame")
        top.add(build, weight=2)
        canvas = tk.Canvas(build, bg=PALETTE["panel2"], highlightthickness=0, bd=0)
        bvsb = ttk.Scrollbar(build, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=bvsb.set)
        bvsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = ttk.Frame(canvas, style="Card.TFrame")
        inner_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfigure(inner_id, width=e.width))

        def _wheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _wheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))
        self._build_builder(inner)

    def _populate_tree(self):
        for radio, subcats in CATALOG:
            rid = self.tree.insert("", "end", text=f"  {radio}", open=True, tags=("group",))
            for subname, cmds in subcats:
                sid = self.tree.insert(rid, "end", text=f"  {subname}", open=True)
                for cmd in cmds:
                    tag = "attack" if subname.lower().startswith("attack") else ""
                    label = ("  ⚠ " if tag else "  ") + cmd["name"]
                    iid = self.tree.insert(sid, "end", text=label, tags=(tag,) if tag else ())
                    self.cmd_by_iid[iid] = cmd

    def _build_builder(self, parent):
        pad = dict(padx=16)
        self.b_title = ttk.Label(parent, text="Select a command", style="Title.TLabel")
        self.b_title.pack(anchor="w", pady=(14, 0), **pad)
        self.b_base = ttk.Label(parent, text="", style="CardMuted.TLabel", font=MONO)
        self.b_base.pack(anchor="w", pady=(2, 10), **pad)

        self.b_warn = ttk.Label(parent, text="", style="Warn.TLabel")
        self.b_warn.pack(anchor="w", **pad)

        ttk.Label(parent, text="PARAMETERS", style="CardMuted.TLabel",
                  font=UI_BOLD).pack(anchor="w", pady=(6, 2), **pad)
        self.params_frame = ttk.Frame(parent, style="Card.TFrame")
        self.params_frame.pack(fill="x", **pad)

        # Command string + send
        sendrow = ttk.Frame(parent, style="Card.TFrame")
        sendrow.pack(fill="x", pady=(14, 4), **pad)
        ttk.Label(sendrow, text="Command string", style="CardMuted.TLabel").pack(anchor="w")
        row2 = ttk.Frame(sendrow, style="Card.TFrame")
        row2.pack(fill="x", pady=(2, 0))
        self.preview_var = tk.StringVar()
        self.preview = ttk.Entry(row2, textvariable=self.preview_var, font=MONO)
        self.preview.pack(side="left", fill="x", expand=True, ipady=4)
        self.send_btn = ttk.Button(row2, text="Send ▶", style="Accent.TButton",
                                   command=self.send_current)
        self.send_btn.pack(side="left", padx=(8, 0))
        # Shown only for long-running commands (packed in _load_command).
        self.stop_btn = ttk.Button(row2, text="■ Stop", style="Stop.TButton",
                                   command=self.stop_running)

        # Help panel (under the parameter/command box, as requested)
        ttk.Label(parent, text="HELP", style="CardMuted.TLabel",
                  font=UI_BOLD).pack(anchor="w", pady=(14, 2), **pad)
        helpwrap = ttk.Frame(parent, style="Card.TFrame")
        helpwrap.pack(fill="both", expand=True, padx=16, pady=(0, 14))
        self.help_text = tk.Text(helpwrap, height=6, wrap="word", relief="flat",
                                 bg=PALETTE["entry"], fg=PALETTE["muted"],
                                 insertbackground=PALETTE["fg"], font=UI,
                                 padx=12, pady=10, highlightthickness=1,
                                 highlightbackground=PALETTE["border"])
        self.help_text.pack(fill="both", expand=True)
        self.help_text.configure(state="disabled")

    # ---- console + event log --------------------------------------------
    def _build_console(self):
        nb = ttk.Notebook(self.vpane)
        self.vpane.add(nb, weight=2)

        # ----- Serial Console tab -----
        wrap = ttk.Frame(nb, style="Card.TFrame")
        nb.add(wrap, text="Serial Console")

        header = ttk.Frame(wrap, style="Card.TFrame")
        header.pack(fill="x", padx=10, pady=(8, 2))

        exp = ttk.Menubutton(header, text="Export ▾", style="TMenubutton")
        expmenu = tk.Menu(exp, tearoff=False, bg=PALETTE["panel2"], fg=PALETTE["fg"],
                          activebackground=PALETTE["accent"], activeforeground=PALETTE["accentfg"],
                          bd=0, relief="flat")
        expmenu.add_command(label="Nmap target list (-iL)…", command=self.export_nmap_targets)
        expmenu.add_command(label="Console log (.txt)…", command=self.export_console_log)
        expmenu.add_separator()
        expmenu.add_command(label="Open capture in Wireshark…", command=self.open_pcap_dialog)
        exp["menu"] = expmenu
        exp.pack(side="left")

        ttk.Checkbutton(header, text="Autoscroll", style="Card.TCheckbutton",
                        variable=self.autoscroll).pack(side="right")
        ttk.Checkbutton(header, text="Log scans → CSV", style="Card.TCheckbutton",
                        variable=self.csv_logging, command=self._toggle_csv).pack(side="right", padx=10)
        ttk.Button(header, text="Clear", command=self._clear_console).pack(side="right")
        self.csv_status = ttk.Label(header, text="", style="CardMuted.TLabel")
        self.csv_status.pack(side="right", padx=10)

        cwrap = ttk.Frame(wrap, style="Card.TFrame")
        cwrap.pack(fill="both", expand=True, padx=10, pady=(0, 4))
        self.console = tk.Text(cwrap, wrap="none", relief="flat", bg="#070b0f",
                               fg=PALETTE["fg"], insertbackground=PALETTE["fg"],
                               font=MONO, padx=10, pady=8, height=10)
        csb = ttk.Scrollbar(cwrap, orient="vertical", command=self.console.yview)
        self.console.configure(yscrollcommand=csb.set)
        csb.pack(side="right", fill="y")
        self.console.pack(side="left", fill="both", expand=True)
        self.console.tag_configure("tx", foreground=PALETTE["accent"])
        self.console.tag_configure("sys", foreground=PALETTE["muted"])
        self.console.tag_configure("row", foreground=PALETTE["ok"])

        rawrow = ttk.Frame(wrap, style="Card.TFrame")
        rawrow.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Label(rawrow, text="Raw", style="CardMuted.TLabel").pack(side="left")
        self.raw_var = tk.StringVar()
        raw_entry = ttk.Entry(rawrow, textvariable=self.raw_var, font=MONO)
        raw_entry.pack(side="left", fill="x", expand=True, padx=(6, 6), ipady=3)
        raw_entry.bind("<Return>", lambda e: self._send_raw())
        ttk.Button(rawrow, text="Send", command=self._send_raw).pack(side="left")

        # ----- Event Log tab -----
        ev = ttk.Frame(nb, style="Card.TFrame")
        nb.add(ev, text="Event Log")
        evh = ttk.Frame(ev, style="Card.TFrame")
        evh.pack(fill="x", padx=10, pady=(8, 2))
        ttk.Label(evh, text="Start / stop and connection events are recorded here "
                  "and appended to logs/events_*.log", style="CardMuted.TLabel").pack(side="left")
        ttk.Button(evh, text="Clear", command=self._clear_eventlog).pack(side="right")
        self.evlog_status = ttk.Label(evh, text="", style="CardMuted.TLabel")
        self.evlog_status.pack(side="right", padx=10)

        ewrap = ttk.Frame(ev, style="Card.TFrame")
        ewrap.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.eventlog = tk.Text(ewrap, wrap="none", relief="flat", bg="#070b0f",
                                fg=PALETTE["fg"], insertbackground=PALETTE["fg"],
                                font=MONO, padx=10, pady=8, height=10)
        esb = ttk.Scrollbar(ewrap, orient="vertical", command=self.eventlog.yview)
        self.eventlog.configure(yscrollcommand=esb.set)
        esb.pack(side="right", fill="y")
        self.eventlog.pack(side="left", fill="both", expand=True)
        self.eventlog.tag_configure("start", foreground=PALETTE["accent"])
        self.eventlog.tag_configure("stop", foreground=PALETTE["warn"])
        self.eventlog.tag_configure("conn", foreground=PALETTE["ok"])
        self.eventlog.tag_configure("info", foreground=PALETTE["muted"])
        self.eventlog.configure(state="disabled")

    # ---- tree selection / builder --------------------------------------
    def _on_tree_select(self, _evt):
        sel = self.tree.selection()
        if not sel:
            return
        cmd = self.cmd_by_iid.get(sel[0])
        if cmd:
            self._load_command(cmd)

    def _load_command(self, cmd):
        self.current_cmd = cmd
        self.b_title.configure(text=cmd["name"])
        self.b_base.configure(text=cmd["base"])
        is_attack = "authorized" in cmd["help"].lower() or "disrupt" in cmd["help"].lower()
        self.b_warn.configure(
            text="⚠ Active transmission — authorized targets only." if is_attack else "")

        # Surface Stop on the same page for commands that run until stopped.
        if command_runs(cmd["base"]):
            self.stop_btn.pack(side="left", padx=(8, 0))
        else:
            self.stop_btn.pack_forget()

        for w in self.params_frame.winfo_children():
            w.destroy()
        self.param_vars = []
        self._entries = {}
        self._active_pickers = []

        vars_by_spec = {}
        for i, spec in enumerate(cmd["params"]):
            vars_by_spec[id(spec)] = self._build_param_row(i, spec)

        # Double-click pickers for any params that reference a scanned list.
        prow = len(cmd["params"])
        for spec in cmd["params"]:
            if spec.get("source"):
                self._build_picker(prow, spec, vars_by_spec[id(spec)])
                prow += 1

        self._set_help(cmd)
        self._update_preview()

    def _build_param_row(self, row, spec):
        f = self.params_frame
        lbl = ttk.Label(f, text=spec["label"], style="Card.TLabel")
        lbl.grid(row=row, column=0, sticky="w", pady=4, padx=(0, 10))
        kind = spec["kind"]
        if kind == "bool":
            var = tk.BooleanVar(value=bool(spec.get("default")))
            ttk.Checkbutton(f, variable=var, style="Card.TCheckbutton",
                            command=self._update_preview).grid(row=row, column=1, sticky="w")
            self.param_vars.append((spec, lambda v=var: ("__flag__" if v.get() else "")))
        elif kind == "choice":
            var = tk.StringVar(value=spec.get("default", ""))
            cb = ttk.Combobox(f, textvariable=var, values=spec["choices"],
                              state="readonly", width=18)
            cb.grid(row=row, column=1, sticky="w")
            cb.bind("<<ComboboxSelected>>",
                    lambda e: (self._update_preview(), self._refresh_pickers()))
            self.param_vars.append((spec, lambda v=var: v.get().strip()))
        else:  # text / int
            var = tk.StringVar(value=spec.get("default", ""))
            ent = ttk.Entry(f, textvariable=var, width=26, font=MONO)
            ent.grid(row=row, column=1, sticky="we")
            self._entries[id(spec)] = ent
            if spec.get("placeholder"):
                self._add_placeholder(ent, var, spec["placeholder"])
            var.trace_add("write", lambda *_: self._update_preview())
            self.param_vars.append((spec, lambda v=var: v.get().strip()))
        if spec.get("help"):
            ttk.Label(f, text=spec["help"], style="CardMuted.TLabel",
                      font=(UI[0], 9)).grid(row=row, column=2, sticky="w", padx=(12, 0))
        f.grid_columnconfigure(1, weight=0)
        f.grid_columnconfigure(2, weight=1)
        return var

    def _add_placeholder(self, entry, var, text):
        def show():
            if not var.get():
                entry.configure(foreground=PALETTE["muted"])
                var.set(text)
                entry._ph = True
        def on_focus(_):
            if getattr(entry, "_ph", False):
                var.set("")
                entry.configure(foreground=PALETTE["fg"])
                entry._ph = False
        def on_blur(_):
            if not var.get():
                show()
        entry.bind("<FocusIn>", on_focus)
        entry.bind("<FocusOut>", on_blur)
        show()

    # ---- target pickers (double-click to fill) --------------------------
    _SRC_NAMES = {"ap": "APs", "sta": "stations", "ssid": "SSIDs", "host": "ARP hosts"}
    _SRC_CMD = {"ap": "list -a", "sta": "list -s", "ssid": "list -c", "host": "arpscan"}

    def _resolve_src(self, spec):
        """Concrete source ('ap'/'sta'/'ssid') for a spec, honoring 'auto'."""
        s = spec.get("source", "")
        if s != "auto":
            return s
        for sp, getter in self.param_vars:   # follow the -a/-s/-c dropdown
            if sp.get("kind") == "choice" and {"-a", "-s", "-c"} & set(sp.get("choices", [])):
                return {"-a": "ap", "-s": "sta", "-c": "ssid"}.get(getter(), "ap")
        return "ap"

    def _build_picker(self, row, spec, var):
        src = self._resolve_src(spec)
        f = ttk.Frame(self.params_frame, style="Card.TFrame")
        f.grid(row=row, column=0, columnspan=3, sticky="we", pady=(8, 2))
        top = ttk.Frame(f, style="Card.TFrame")
        top.pack(fill="x")
        lbl = ttk.Label(top, text=f"Pick from scanned {self._SRC_NAMES.get(src, 'list')}"
                        " — double-click to use", style="CardMuted.TLabel")
        lbl.pack(side="left")
        ttk.Button(top, text="↻ Refresh",
                   command=lambda: self._picker_refresh_cmd(spec)).pack(side="right")

        tw = ttk.Frame(f, style="Card.TFrame")
        tw.pack(fill="x", pady=(4, 0))
        cols = ("idx", "name", "bssid", "ch", "rssi")
        tree = ttk.Treeview(tw, columns=cols, show="headings", height=5, selectmode="browse")
        name_h, bssid_h = (("IP address", "MAC") if src == "host"
                           else ("SSID / name", "BSSID"))
        for c, txt, w, anch in (("idx", "#", 42, "center"), ("name", name_h, 190, "w"),
                                ("bssid", bssid_h, 150, "w"), ("ch", "CH", 44, "center"),
                                ("rssi", "RSSI", 54, "center")):
            tree.heading(c, text=txt)
            tree.column(c, width=w, anchor=anch, stretch=(c == "name"))
        sb = ttk.Scrollbar(tw, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        tree.pack(side="left", fill="x", expand=True)
        tree.bind("<Double-1>", lambda e: self._picker_pick(tree, spec, var))

        self._active_pickers.append({"tree": tree, "spec": spec, "lbl": lbl})
        self._populate_picker(tree, src)

    def _populate_picker(self, tree, src):
        tree.delete(*tree.get_children())
        data = self._lists.get(src, {})
        for idx in sorted(data, key=lambda x: int(x) if str(x).isdigit() else 0):
            r = data[idx]
            tree.insert("", "end", values=(idx, r.get("ssid", ""), r.get("bssid", ""),
                                           r.get("channel", ""), r.get("rssi", "")))

    def _refresh_pickers(self):
        for p in self._active_pickers:
            src = self._resolve_src(p["spec"])
            p["lbl"].configure(text=f"Pick from scanned {self._SRC_NAMES.get(src, 'list')}"
                               " — double-click to use")
            self._populate_picker(p["tree"], src)

    def _picker_pick(self, tree, spec, var):
        sel = tree.selection()
        if not sel:
            return
        idx = str(tree.item(sel[0], "values")[0])
        ent = self._entries.get(id(spec))
        if ent is not None:                 # drop placeholder state so value sticks
            ent._ph = False
            ent.configure(foreground=PALETTE["fg"])
        if spec.get("multi"):
            cur = var.get().strip()
            if cur == spec.get("placeholder", ""):
                cur = ""
            parts = [x for x in re.split(r"[,\s]+", cur) if x]
            if idx not in parts:
                parts.append(idx)
            var.set(",".join(parts))
        else:
            var.set(idx)
        self._update_preview()

    def _picker_refresh_cmd(self, spec):
        src = self._resolve_src(spec)
        cmd = self._SRC_CMD.get(src)
        if not self.dev:
            messagebox.showinfo("Not connected", "Connect to the Marauder first.")
            return
        if cmd:
            self._do_send(cmd)

    def _effective(self, spec, getter):
        """Return the user value for a param, treating placeholder as empty."""
        val = getter()
        if val == spec.get("placeholder"):
            return ""
        return val

    def _update_preview(self):
        if not self.current_cmd:
            return
        parts = [self.current_cmd["base"]]
        for spec, getter in self.param_vars:
            val = self._effective(spec, getter)
            if spec["kind"] == "bool":
                if val == "__flag__" and spec.get("flag"):
                    parts.append(spec["flag"])
            elif val:
                if spec.get("flag"):
                    parts.append(spec["flag"])
                parts.append(val)
        self.preview_var.set(" ".join(parts))

    def _set_help(self, cmd):
        self.help_text.configure(state="normal")
        self.help_text.delete("1.0", "end")
        self.help_text.insert("1.0", cmd["help"])
        self.help_text.configure(state="disabled")

    # ---- connection ------------------------------------------------------
    def _scan_ports(self):
        """Return port objects sorted so a likely Marauder (known USB-UART) is first."""
        ports = list(list_ports.comports())
        ports.sort(key=lambda p: (p.vid not in KNOWN_VIDS, p.device))
        return ports

    def refresh_ports(self):
        ports = self._scan_ports()
        labels = []
        self._port_map, self._port_vids = {}, {}
        for p in ports:
            label = f"{p.device} — {p.description}"
            labels.append(label)
            self._port_map[label] = p.device
            self._port_vids[p.device] = p.vid
        self.port_cb["values"] = labels
        self._known_devices = {p.device for p in ports}
        # Auto-select the top-ranked (Marauder-like) port if nothing chosen yet.
        if labels and not self.port_cb.get():
            self.port_cb.set(labels[0])

    def _marauder_device(self):
        """Device string of the first present port with a known USB-UART VID, else None."""
        for dev, vid in self._port_vids.items():
            if vid in KNOWN_VIDS:
                return dev
        return None

    def _poll_ports(self):
        """Hot-plug watcher: refresh the dropdown, auto-connect / auto-disconnect."""
        try:
            ports = self._scan_ports()
            devices = {p.device for p in ports}

            if devices != self._known_devices:
                # Rebuild list but preserve the user's current selection if it survives.
                keep = self.port_cb.get()
                self._port_map, self._port_vids, labels = {}, {}, []
                for p in ports:
                    label = f"{p.device} — {p.description}"
                    labels.append(label)
                    self._port_map[label] = p.device
                    self._port_vids[p.device] = p.vid
                self.port_cb["values"] = labels
                if keep in labels:
                    self.port_cb.set(keep)
                elif labels:
                    self.port_cb.set(labels[0])
                else:
                    self.port_cb.set("")
                self._known_devices = devices

            # Forget auto-connect attempts for ports that have been unplugged,
            # so re-plugging a device tries again.
            self._autoconnect_tried &= devices

            # Auto-connect when a Marauder-like port is present and we're idle.
            if self.autoconnect.get() and not self.dev:
                target = self._marauder_device()
                if target and target not in self._autoconnect_tried:
                    self._autoconnect_tried.add(target)
                    for lab, dev in self._port_map.items():
                        if dev == target:
                            self.port_cb.set(lab)
                            break
                    self._connect(silent_fail=True)

            # Auto-disconnect if the connected device was unplugged.
            if self.dev and self._connected_port and self._connected_port not in devices:
                self._emit("[device unplugged]\n", "sys")
                self._disconnect()
        finally:
            self.after(1500, self._poll_ports)

    def toggle_connection(self):
        if self.dev:
            self._disconnect()
        else:
            self._connect()

    def _connect(self, silent_fail=False):
        label = self.port_cb.get()
        if not label:
            if not silent_fail:
                messagebox.showwarning("No port", "Select a serial port first.")
            return
        port = self._port_map.get(label, label)
        baud = int(self.baud_cb.get())
        try:
            self.dev = Marauder(port, baud)
        except Exception as e:
            self.dev = None
            if not silent_fail:
                messagebox.showerror("Connection failed", str(e))
            return
        self._connected_port = port
        self.reader_stop.clear()
        self.reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self.reader_thread.start()
        self.connect_btn.configure(text="Disconnect")
        self.status.configure(text=f"● Connected  {port} @ {baud}", foreground=PALETTE["ok"])
        self._emit(f"[connected to {port} @ {baud}]\n", "sys")
        self.log_event("CONNECT", f"{port} @ {baud}")

    def _disconnect(self):
        port = self._connected_port
        self.reader_stop.set()
        if self.reader_thread:
            self.reader_thread.join(timeout=1.0)
        if self.dev:
            self.dev.close()
        self.dev = None
        self._connected_port = None
        self.running = False
        self.connect_btn.configure(text="Connect")
        self.status.configure(text="● Disconnected", foreground=PALETTE["muted"])
        self._emit("[disconnected]\n", "sys")
        self.log_event("DISCONNECT", port or "")

    def _reader_loop(self):
        while not self.reader_stop.is_set() and self.dev:
            try:
                data = self.dev.read_available()
            except Exception as e:
                self.rx_queue.put(f"[serial error: {e}]\n")
                break
            if data:
                self.rx_queue.put(data)
            else:
                self.reader_stop.wait(0.05)

    # ---- send ------------------------------------------------------------
    def send_current(self):
        cmd = self.preview_var.get().strip()
        if cmd:
            self._do_send(cmd)

    def _send_raw(self):
        cmd = self.raw_var.get().strip()
        if cmd:
            self._do_send(cmd)
            self.raw_var.set("")

    def _do_send(self, cmd, event_kind=None):
        if not self.dev:
            messagebox.showinfo("Not connected", "Connect to the Marauder first.")
            return
        try:
            self.dev.send(cmd)
            self._emit(f">> {cmd}\n", "tx")
        except Exception as e:
            self._emit(f"[send failed: {e}]\n", "sys")
            self.log_event("ERROR", f"send failed: {cmd}")
            return
        kind = event_kind or ("START" if command_runs(cmd) else "SEND")
        if kind == "START":
            self.running = True
            self._last_running_base = cmd
        self.log_event(kind, cmd)

    def stop_running(self):
        """Stop the running op and record it. Safe to press any time.

        Recon has its own stop verb; everything else halts with `stopscan`.
        """
        if not self.dev:
            messagebox.showinfo("Not connected", "Connect to the Marauder first.")
            return
        stopcmd = "recon stop" if self._last_running_base.strip().startswith("recon ") else "stopscan"
        self._do_send(stopcmd, event_kind="STOP")
        self.running = False
        self._last_running_base = ""

    def log_event(self, kind, text=""):
        """Publish an event to the Event Log tab and append it to logs/events_*.log."""
        now = _dt.datetime.now()
        tag = {"START": "start", "STOP": "stop", "CONNECT": "conn",
               "DISCONNECT": "conn"}.get(kind, "info")
        if getattr(self, "eventlog", None) is not None:
            line = f"{now.strftime('%H:%M:%S')}  {kind:<10} {text}".rstrip()
            self.eventlog.configure(state="normal")
            self.eventlog.insert("end", line + "\n", (tag,))
            self.eventlog.see("end")
            self.eventlog.configure(state="disabled")
        try:
            if self._events_file is None:
                logs = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
                os.makedirs(logs, exist_ok=True)
                self._events_path = os.path.join(logs, now.strftime("events_%Y%m%d.log"))
                self._events_file = open(self._events_path, "a", encoding="utf-8")
                if getattr(self, "evlog_status", None) is not None:
                    self.evlog_status.configure(text=f"→ {os.path.basename(self._events_path)}")
            self._events_file.write(
                f"{now.isoformat(timespec='seconds')}  {kind} {text}".rstrip() + "\n")
            self._events_file.flush()
        except Exception:
            pass

    # ---- RX pump + CSV ---------------------------------------------------
    def _pump_rx(self):
        try:
            while True:
                try:
                    chunk = self.rx_queue.get_nowait()
                except queue.Empty:
                    break
                self._ingest(chunk)
        except Exception:
            pass
        # Always reschedule — the pump must never die, or the console freezes.
        self.after(60, self._pump_rx)

    def _ingest(self, chunk):
        self._emit(chunk, None)
        # Line-buffer for parsing. Each line is isolated so one bad line can
        # never interrupt console rendering or freeze the receive loop.
        self._line_buf += chunk
        picker_dirty = False
        while "\n" in self._line_buf:
            line, self._line_buf = self._line_buf.split("\n", 1)
            try:
                if self.csv_logging.get():
                    self._maybe_log_row(line)
                self._harvest_ips(line)
                if self._track_list_line(line):
                    picker_dirty = True
            except Exception:
                pass
        if picker_dirty and self._active_pickers:
            try:
                self._refresh_pickers()
            except Exception:
                pass

    def _track_list_line(self, line):
        """Parse `list -a/-s/-c` output into self._lists. Returns True if changed.

        This firmware prints rows as:  [<idx>][CH:<ch>] <name or mac> <rssi>
        (a plain `[<idx>] <name>` fallback covers SSID lists / other builds).
        """
        # The firmware prints "> " as a prompt with no newline, so a command
        # echo often arrives as "> #list -a" (and the first data row as
        # "> [0]..."). Strip any leading prompt before detecting/parsing.
        raw = line.strip()
        while raw[:1] == ">":
            raw = raw[1:].lstrip()
        low = raw.lower()
        if low.startswith("#"):
            cmd = low[1:].strip()
            if cmd.startswith("list -a"):
                mode = "ap"
            elif cmd.startswith("list -s"):
                mode = "sta"
            elif cmd.startswith("list -c"):
                mode = "ssid"
            elif cmd.startswith(("arpscan", "pingscan")):
                mode = "host"
            else:
                mode = None
            self._parse_mode = mode
            if mode:
                self._lists[mode] = {}     # fresh capture
                self._host_n = 0
                return True
            return False
        if not self._parse_mode or not low:
            return False
        if any(k in low for k in ("selected", "available", "no ap", "no sta", "====")):
            return False

        # Host discovery (ARP / ping): one IP per line, bracketed index or order.
        if self._parse_mode == "host":
            ipm = _IP_RE.search(raw)
            if not ipm:
                return False
            # Only a *bracketed* leading [n] is an index; a bare leading number
            # would just be the IP's first octet, so fall back to arrival order.
            im = re.match(r"\[(\d+)\]", raw)
            idx = im.group(1) if im else str(self._host_n)
            mac = _MAC_RE.search(raw)
            self._lists["host"][idx] = {
                "index": idx, "ssid": ipm.group(0),
                "bssid": mac.group(1) if mac else "", "channel": "", "rssi": "",
            }
            self._host_n += 1
            return True

        ch = rssi = ""
        m = re.match(r"\[(\d+)\]\s*\[ch[:\s]*(\d+)\]\s*(.*?)\s*(-?\d+)\s*$", raw, re.I)
        if m:
            idx, ch, name, rssi = m.group(1), m.group(2), m.group(3).strip(), m.group(4)
        else:
            m2 = re.match(r"\[?(\d+)\]?[\s:).\-]+(.+)", raw)
            if not m2:
                return False
            idx, name = m2.group(1), m2.group(2).strip()
        mac = _MAC_RE.search(name)
        self._lists[self._parse_mode][idx] = {
            "index": idx, "ssid": name, "bssid": mac.group(1) if mac else "",
            "channel": ch, "rssi": rssi,
        }
        return True

    def _harvest_ips(self, line):
        """Collect IPv4 hosts seen in output (arp/ping/port scans) for Nmap export."""
        for ip in _IP_RE.findall(line):
            if ip in self._hosts_seen or ip in ("0.0.0.0", "255.255.255.255"):
                continue
            self._hosts_seen.add(ip)
            self._hosts.append(ip)

    def _maybe_log_row(self, line):
        row = parse_scan_line(line)
        if not row or not (row["bssid"] or row["ssid"]):
            return
        key = (row["bssid"], row["ssid"])
        if key in self.csv_seen:
            return
        self.csv_seen.add(key)
        if self.csv_writer:
            self.csv_writer.writerow([
                _dt.datetime.now().isoformat(timespec="seconds"),
                row["index"], row["ssid"], row["bssid"],
                row["channel"], row["rssi"],
            ])
            self.csv_file.flush()
            n = len(self.csv_seen)
            self.csv_status.configure(text=f"{n} row(s) logged")

    def _toggle_csv(self):
        if self.csv_logging.get():
            logs = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
            os.makedirs(logs, exist_ok=True)
            fn = os.path.join(logs, _dt.datetime.now().strftime("scan_%Y%m%d_%H%M%S.csv"))
            self.csv_file = open(fn, "w", newline="", encoding="utf-8")
            self.csv_writer = csv.writer(self.csv_file)
            self.csv_writer.writerow(["timestamp", "index", "ssid", "bssid", "channel", "rssi"])
            self.csv_seen = set()
            self.csv_status.configure(text=f"→ {os.path.basename(fn)}")
            self._emit(f"[CSV logging to {fn}]\n", "sys")
        else:
            if self.csv_file:
                self.csv_file.close()
            self.csv_writer = self.csv_file = None
            self.csv_status.configure(text="stopped")

    # ---- console helpers -------------------------------------------------
    def _emit(self, text, tag):
        self.console.configure(state="normal")
        self.console.insert("end", text, (tag,) if tag else ())
        if self.autoscroll.get():
            self.console.see("end")
        self.console.configure(state="disabled")

    def _clear_console(self):
        self.console.configure(state="normal")
        self.console.delete("1.0", "end")
        self.console.configure(state="disabled")

    def _clear_eventlog(self):
        self.eventlog.configure(state="normal")
        self.eventlog.delete("1.0", "end")
        self.eventlog.configure(state="disabled")

    # ---- exports for Nmap / Wireshark -----------------------------------
    def _logs_dir(self):
        d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
        os.makedirs(d, exist_ok=True)
        return d

    def export_nmap_targets(self):
        """Write host IPs seen this session as an Nmap -iL target list."""
        if not self._hosts:
            messagebox.showinfo(
                "No hosts yet",
                "No IPv4 hosts have appeared in the output.\n\n"
                "Join a network (WiFi → IP / Network → Join AP), then run "
                "ARP Scan / Ping Scan / Port Scan. Discovered host IPs are "
                "collected automatically and can then be exported.")
            return
        fn = os.path.join(self._logs_dir(),
                          _dt.datetime.now().strftime("nmap_targets_%Y%m%d_%H%M%S.txt"))
        with open(fn, "w", encoding="utf-8") as f:
            f.write("\n".join(self._hosts) + "\n")
        self.log_event("EXPORT", f"nmap targets -> {os.path.basename(fn)} ({len(self._hosts)} hosts)")

        win = tk.Toplevel(self)
        win.title("Nmap targets exported")
        win.configure(bg=PALETTE["panel2"])
        win.geometry("560x210")
        ttk.Label(win, text=f"Exported {len(self._hosts)} host(s)", style="Title.TLabel").pack(
            anchor="w", padx=16, pady=(14, 2))
        ttk.Label(win, text=fn, style="CardMuted.TLabel", font=MONO).pack(anchor="w", padx=16)
        ttk.Label(win, text="Run Nmap against the list:", style="CardMuted.TLabel").pack(
            anchor="w", padx=16, pady=(12, 2))
        cmd = f'nmap -iL "{fn}" -sV -T4'
        e = ttk.Entry(win, font=MONO)
        e.insert(0, cmd)
        e.configure(state="readonly")
        e.pack(fill="x", padx=16, ipady=4)
        row = ttk.Frame(win, style="Card.TFrame")
        row.pack(fill="x", padx=16, pady=14)

        def copy_cmd():
            self.clipboard_clear()
            self.clipboard_append(cmd)
        ttk.Button(row, text="Copy command", command=copy_cmd).pack(side="right")

    def export_console_log(self):
        """Dump the raw serial console to a timestamped text file."""
        text = self.console.get("1.0", "end-1c")
        if not text.strip():
            messagebox.showinfo("Nothing to export", "The console is empty.")
            return
        fn = os.path.join(self._logs_dir(),
                          _dt.datetime.now().strftime("console_%Y%m%d_%H%M%S.log"))
        with open(fn, "w", encoding="utf-8") as f:
            f.write(text)
        self.log_event("EXPORT", f"console log -> {os.path.basename(fn)}")
        messagebox.showinfo("Console exported", f"Saved:\n{fn}")

    # ---- about -----------------------------------------------------------
    def show_about(self):
        win = tk.Toplevel(self)
        win.title("About")
        win.configure(bg=PALETTE["panel2"])
        win.geometry("440x300")
        win.resizable(False, False)
        win.transient(self)
        ttk.Label(win, text="Marauder V8 — Control", style="Title.TLabel").pack(
            anchor="w", padx=22, pady=(20, 2))
        ttk.Label(win, text=f"Version {__version__}",
                  style="CardMuted.TLabel").pack(anchor="w", padx=22)
        ttk.Label(win, text=f"Made by {AUTHOR}", style="Card.TLabel").pack(
            anchor="w", padx=22, pady=(18, 0))
        ttk.Label(win, text="Contact me:", style="CardMuted.TLabel").pack(
            anchor="w", padx=22, pady=(10, 0))
        link = ttk.Label(win, text=CONTACT, style="Card.TLabel",
                         foreground=PALETTE["accent"], cursor="hand2")
        link.pack(anchor="w", padx=22)
        link.bind("<Button-1>", lambda e: webbrowser.open(f"mailto:{CONTACT}"))
        ttk.Label(win, text="A desktop control panel for the ESP32 Marauder (V8).\n"
                  "For authorized security testing only.",
                  style="CardMuted.TLabel", justify="left").pack(anchor="w", padx=22, pady=(16, 0))

        row = ttk.Frame(win, style="Card.TFrame")
        row.pack(fill="x", padx=22, pady=18, side="bottom")
        ttk.Button(row, text="Close", command=win.destroy).pack(side="right")

        def copy_email():
            self.clipboard_clear()
            self.clipboard_append(CONTACT)
        ttk.Button(row, text="Copy email", command=copy_email).pack(side="right", padx=(0, 8))

    # ---- PCAP ------------------------------------------------------------
    def open_pcap_dialog(self):
        path = filedialog.askopenfilename(
            title="Open a Marauder capture (from the SD card)",
            filetypes=[("Capture files", "*.pcap *.pcapng *.cap"), ("All files", "*.*")])
        if not path:
            return
        try:
            info = marauder_pcap.summarize(path)
            text = marauder_pcap.format_summary(info)
        except Exception as e:
            messagebox.showerror("PCAP error", str(e))
            return

        win = tk.Toplevel(self)
        win.title("PCAP Inspector")
        win.configure(bg=PALETTE["panel2"])
        win.geometry("520x340")
        ttk.Label(win, text="Capture summary", style="Title.TLabel").pack(
            anchor="w", padx=16, pady=(14, 6))
        box = tk.Text(win, height=11, wrap="word", relief="flat", bg=PALETTE["entry"],
                      fg=PALETTE["fg"], font=MONO, padx=12, pady=10)
        box.pack(fill="both", expand=True, padx=16)
        box.insert("1.0", text)
        box.configure(state="disabled")
        btns = ttk.Frame(win, style="Card.TFrame")
        btns.pack(fill="x", padx=16, pady=12)
        has_ws = marauder_pcap.find_wireshark() is not None
        b = ttk.Button(btns, text="Open in Wireshark" if has_ws else "Wireshark not found",
                       style="Accent.TButton" if has_ws else "TButton",
                       command=lambda: marauder_pcap.open_in_wireshark(path))
        b.pack(side="right")
        if not has_ws:
            b.state(["disabled"])

    # ---- shutdown --------------------------------------------------------
    def _on_close(self):
        try:
            if self.dev:
                self._disconnect()
            if self.csv_file:
                self.csv_file.close()
            if self._events_file:
                self._events_file.close()
        finally:
            self.destroy()


if __name__ == "__main__":
    MarauderGUI().mainloop()
