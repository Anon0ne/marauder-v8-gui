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

__version__ = "0.3.0"
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
import marauder_flash
import marauder_ai


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
    """Best-effort extraction of a scan row. Returns dict or None.

    Handles both the `list` format and the live `recon` format, e.g.
    `-81 Ch: 153 10:f0:68:9c:ad:e0 ESSID: LuxSpeed 11 15` (leading RSSI,
    `ESSID:` label, and two trailing counter columns).
    """
    mac = _MAC_RE.search(line)
    rssi_m = _RSSI_RE.search(line)
    rssi = rssi_m.group(1) if rssi_m else ""
    if not rssi:
        lead = re.match(r"\s*(-\d{1,3})\b", line)  # recon rows begin with the RSSI
        if lead:
            rssi = lead.group(1)
    if not mac and not rssi:
        return None  # not a result row
    ssid = _SSID_RE.search(line)   # also matches the ESSID: label
    ch = _CH_RE.search(line)
    idx = re.match(r"\s*\[?(\d+)\]?[:\s]", line)
    # Guard: when the SSID is hidden/empty the loose regex can swallow the
    # following field (e.g. "BSSID: ..") — cut at the first known field word.
    ssid_val = ssid.group(1).strip() if ssid else ""
    ssid_val = re.split(r"\b(?:BSSID|RSSI|CH|Channel)\b", ssid_val)[0].strip(" :=\t")
    ssid_val = re.sub(r"\s+\d+\s+\d+\s*$", "", ssid_val)  # drop recon trailing counts
    return {
        "ssid": ssid_val,
        "bssid": mac.group(1) if mac else "",
        "channel": ch.group(1) if ch else "",
        "rssi": rssi,
        "index": idx.group(1) if idx else "",
    }


# Commands that run until explicitly stopped (scans, sniffs, attacks, spam…).
# A Stop button is surfaced for these and sending one logs a START event.
RUNNING_PREFIXES = ("sniff", "attack", "blespam", "scanall", "wardrive",
                    "mactrack", "packetcount", "nmea", "karma", "evilportal",
                    "arpscan", "pingscan", "portscan", "foxhunt",
                    "sigmon", "btwardrive")


def redact(cmd: str) -> str:
    """Mask secrets before anything is shown, logged, or exported — currently the
    WiFi password after `-p` (e.g. `join -a 3 -p hunter2` -> `join -a 3 -p ***`).
    The real command is still sent to the device; only display/log copies change."""
    return re.sub(r"(?<!\S)(-p\s+)(\S+)", r"\1***", cmd)


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
        self._build_menu()
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

    # ---- menu bar --------------------------------------------------------
    def _build_menu(self):
        bar = tk.Menu(self)
        tools = tk.Menu(bar, tearoff=False, bg=PALETTE["panel2"], fg=PALETTE["fg"],
                        activebackground=PALETTE["accent"], activeforeground=PALETTE["accentfg"])
        tools.add_command(label="Live RF Dashboard…", command=self.open_dashboard)
        tools.add_command(label="Automated Survey…", command=self.open_survey)
        tools.add_command(label="AI Assistant (Ollama)…", command=self.open_ai_dialog)
        tools.add_separator()
        tools.add_command(label="Firmware updater…", command=self.open_firmware_dialog)
        tools.add_command(label="PCAP inspector…", command=self.open_pcap_dialog)
        bar.add_cascade(label="Tools", menu=tools)
        helpm = tk.Menu(bar, tearoff=False, bg=PALETTE["panel2"], fg=PALETTE["fg"],
                        activebackground=PALETTE["accent"], activeforeground=PALETTE["accentfg"])
        helpm.add_command(label="About", command=self.show_about)
        bar.add_cascade(label="Help", menu=helpm)
        self.config(menu=bar)

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
        ttk.Button(bar, text="Firmware…",
                   command=self.open_firmware_dialog).pack(side="right", padx=(0, 8))
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

        self.b_warn = ttk.Label(parent, text="", style="Warn.TLabel")  # packed on demand

        self.params_label = ttk.Label(parent, text="PARAMETERS", style="CardMuted.TLabel",
                                      font=UI_BOLD)
        self.params_label.pack(anchor="w", pady=(6, 2), **pad)
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

        self._build_targets_tab(nb)

    # ---- Targets tab (multi-select → select -a/-s) ----------------------
    def _build_targets_tab(self, nb):
        tg = ttk.Frame(nb, style="Card.TFrame")
        nb.add(tg, text="Targets")
        head = ttk.Frame(tg, style="Card.TFrame")
        head.pack(fill="x", padx=10, pady=(8, 2))
        ttk.Label(head, text="Highlight rows (Ctrl/Shift-click), then Select to target them",
                  style="CardMuted.TLabel").pack(side="left")
        ttk.Button(head, text="Select highlighted →", style="Accent.TButton",
                   command=self._targets_select).pack(side="right")
        ttk.Button(head, text="↻ Refresh", command=self._targets_refresh).pack(side="right", padx=8)
        self.tgt_kind = tk.StringVar(value="ap")
        kind = ttk.Combobox(head, textvariable=self.tgt_kind, values=["ap", "sta"],
                            state="readonly", width=6)
        kind.pack(side="right", padx=8)
        kind.bind("<<ComboboxSelected>>", lambda e: self._targets_populate())

        tw = ttk.Frame(tg, style="Card.TFrame")
        tw.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        cols = ("idx", "name", "bssid", "ch", "rssi")
        self.tgt_tree = ttk.Treeview(tw, columns=cols, show="headings", selectmode="extended")
        for c, txt, w, a in (("idx", "#", 44, "center"), ("name", "SSID / name", 220, "w"),
                             ("bssid", "BSSID", 150, "w"), ("ch", "CH", 44, "center"),
                             ("rssi", "RSSI", 54, "center")):
            self.tgt_tree.heading(c, text=txt)
            self.tgt_tree.column(c, width=w, anchor=a, stretch=(c == "name"))
        sb = ttk.Scrollbar(tw, orient="vertical", command=self.tgt_tree.yview)
        self.tgt_tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.tgt_tree.pack(side="left", fill="both", expand=True)

    def _targets_refresh(self):
        if not self.dev:
            messagebox.showinfo("Not connected", "Connect to the Marauder first.")
            return
        self._do_send("list -s" if self.tgt_kind.get() == "sta" else "list -a")

    def _targets_populate(self):
        if getattr(self, "tgt_tree", None) is None:
            return
        self.tgt_tree.delete(*self.tgt_tree.get_children())
        data = self._lists.get(self.tgt_kind.get(), {})
        for idx in sorted(data, key=lambda x: int(x) if str(x).isdigit() else 0):
            r = data[idx]
            self.tgt_tree.insert("", "end", iid=idx,
                                 values=(idx, r.get("ssid", ""), r.get("bssid", ""),
                                         r.get("channel", ""), r.get("rssi", "")))

    def _targets_select(self):
        sel = self.tgt_tree.selection()
        if not sel:
            messagebox.showinfo("No rows", "Highlight one or more rows first (Ctrl/Shift-click).")
            return
        flag = "-s" if self.tgt_kind.get() == "sta" else "-a"
        idxs = ",".join(sorted(sel, key=lambda x: int(x) if str(x).isdigit() else 0))
        self._do_send(f"select {flag} {idxs}")

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
        if is_attack:
            self.b_warn.configure(text="⚠ Active transmission — authorized targets only.")
            if not self.b_warn.winfo_ismapped():
                self.b_warn.pack(anchor="w", padx=16, after=self.b_base)
        else:
            self.b_warn.pack_forget()   # no empty gap for non-attack commands

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

        # Collapse the PARAMETERS section entirely for commands that take none,
        # so param-less pages (List APs, Reboot, …) don't show an empty block.
        if cmd["params"]:
            if not self.params_label.winfo_ismapped():
                anchor_to = self.b_warn if is_attack else self.b_base
                self.params_label.pack(anchor="w", padx=16, pady=(6, 2), after=anchor_to)
                self.params_frame.pack(fill="x", padx=16, after=self.params_label)
        else:
            self.params_label.pack_forget()
            self.params_frame.pack_forget()

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
        shown = redact(cmd)
        try:
            self.dev.send(cmd)
            self._emit(f">> {shown}\n", "tx")
        except Exception as e:
            self._emit(f"[send failed: {e}]\n", "sys")
            self.log_event("ERROR", f"send failed: {shown}")
            return
        kind = event_kind or ("START" if command_runs(cmd) else "SEND")
        if kind == "START":
            self.running = True
            self._last_running_base = cmd
        self.log_event(kind, shown)

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
        # Cap the partial-line buffer so a newline-less flood can't grow forever.
        if len(self._line_buf) > 65536:
            self._line_buf = self._line_buf[-8192:]
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
        if picker_dirty:
            try:
                if self._active_pickers:
                    self._refresh_pickers()
                self._targets_populate()
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
        if not low:
            return False
        if not self._parse_mode:
            # Not inside a `list` capture → this may be a live recon stream row
            # ("-81 Ch: 153 <mac> ESSID: <ssid> ..."). Fold it into the AP list so
            # the dashboard / Targets populate during recon, deduped by BSSID.
            parsed = parse_scan_line(raw)
            if parsed and parsed.get("bssid"):
                ap = self._lists["ap"]
                idx = next((i for i, r in ap.items() if r.get("bssid") == parsed["bssid"]), None)
                if idx is None:
                    idx = str(len(ap))
                ap[idx] = {"index": idx, "ssid": parsed.get("ssid", ""),
                           "bssid": parsed["bssid"], "channel": parsed.get("channel", ""),
                           "rssi": parsed.get("rssi", "")}
                return True
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
        # Bound console growth so a high-volume sniff can't balloon memory.
        try:
            last = int(self.console.index("end-1c").split(".")[0])
            if last > 6000:
                self.console.delete("1.0", f"{last - 4000}.0")
        except Exception:
            pass
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

        # Windows nmap accepts forward slashes, and they survive shell pasting
        # (backslashes in C:\Users\… get eaten and break `-iL`).
        fwd = fn.replace("\\", "/")
        cmd_file = f'nmap -iL "{fwd}" -sV -T4'
        cmd_inline = "nmap -sV -T4 " + " ".join(self._hosts)

        win = tk.Toplevel(self)
        win.title("Nmap targets exported")
        win.configure(bg=PALETTE["panel2"])
        win.geometry("640x320")
        ttk.Label(win, text=f"Exported {len(self._hosts)} host(s)", style="Title.TLabel").pack(
            anchor="w", padx=16, pady=(14, 2))
        ttk.Label(win, text=fwd, style="CardMuted.TLabel", font=MONO).pack(anchor="w", padx=16)

        ttk.Label(win, text="Run against the file (forward slashes — paste-safe):",
                  style="CardMuted.TLabel").pack(anchor="w", padx=16, pady=(12, 2))
        e1 = ttk.Entry(win, font=MONO)
        e1.insert(0, cmd_file)
        e1.configure(state="readonly")
        e1.pack(fill="x", padx=16, ipady=4)

        ttk.Label(win, text="…or targets inline (no file needed):",
                  style="CardMuted.TLabel").pack(anchor="w", padx=16, pady=(12, 2))
        e2 = ttk.Entry(win, font=MONO)
        e2.insert(0, cmd_inline)
        e2.configure(state="readonly")
        e2.pack(fill="x", padx=16, ipady=4)

        row = ttk.Frame(win, style="Card.TFrame")
        row.pack(fill="x", padx=16, pady=14)

        def _copy(text):
            self.clipboard_clear()
            self.clipboard_append(text)
        ttk.Button(row, text="Copy inline", command=lambda: _copy(cmd_inline)).pack(side="right")
        ttk.Button(row, text="Copy file command", command=lambda: _copy(cmd_file)).pack(side="right", padx=8)

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

    # ---- Live RF dashboard ----------------------------------------------
    @staticmethod
    def _band(ch):
        try:
            return "5 GHz" if int(ch) > 14 else "2.4 GHz"
        except (TypeError, ValueError):
            return "?"

    def open_dashboard(self):
        win = tk.Toplevel(self)
        win.title("Live RF Dashboard")
        win.configure(bg=PALETTE["panel2"])
        win.geometry("760x620")
        win.transient(self)
        self._dash_win = win
        pad = dict(padx=16)

        top = ttk.Frame(win, style="Card.TFrame")
        top.pack(fill="x", pady=(14, 2), **pad)
        ttk.Label(top, text="Live RF Dashboard", style="Title.TLabel").pack(side="left")
        ttk.Label(top, text="Auto-updates from scans. Run Recon / Scan All / List to populate.",
                  style="CardMuted.TLabel").pack(side="left", padx=12)

        tiles = ttk.Frame(win, style="Card.TFrame")
        tiles.pack(fill="x", pady=(10, 6), **pad)
        self._dash_tiles = {}
        for key, label in (("ap", "Access points"), ("sta", "Stations"), ("host", "Hosts"),
                           ("ch", "Channels"), ("g24", "2.4 GHz"), ("g5", "5 GHz")):
            cell = tk.Frame(tiles, bg=PALETTE["entry"], bd=0)
            cell.pack(side="left", expand=True, fill="x", padx=4)
            val = tk.Label(cell, text="0", bg=PALETTE["entry"], fg=PALETTE["accent"],
                           font=(UI[0], 20, "bold"))
            val.pack(anchor="w", padx=12, pady=(8, 0))
            tk.Label(cell, text=label, bg=PALETTE["entry"], fg=PALETTE["muted"],
                     font=(UI[0], 9)).pack(anchor="w", padx=12, pady=(0, 8))
            self._dash_tiles[key] = val

        gps = ttk.Frame(win, style="Card.TFrame")
        gps.pack(fill="x", pady=(8, 0), **pad)
        ttk.Button(gps, text="Read GPS", command=self._dash_read_gps).pack(side="left")
        self._dash_gps = ttk.Label(gps, text="GPS: press Read GPS", style="CardMuted.TLabel", font=MONO)
        self._dash_gps.pack(side="left", padx=10)

        ttk.Label(win, text="Access points per channel", style="CardMuted.TLabel",
                  font=UI_BOLD).pack(anchor="w", pady=(8, 2), **pad)
        self._dash_canvas = tk.Canvas(win, height=150, bg="#070b0f", highlightthickness=0, bd=0)
        self._dash_canvas.pack(fill="x", **pad)

        ttk.Label(win, text="Access points (strongest first)", style="CardMuted.TLabel",
                  font=UI_BOLD).pack(anchor="w", pady=(10, 2), **pad)
        tw = ttk.Frame(win, style="Card.TFrame")
        tw.pack(fill="both", expand=True, padx=16, pady=(0, 14))
        cols = ("rssi", "ch", "band", "ssid", "bssid")
        self._dash_tree = ttk.Treeview(tw, columns=cols, show="headings")
        for c, txt, w, a in (("rssi", "RSSI", 60, "center"), ("ch", "CH", 50, "center"),
                             ("band", "Band", 70, "center"), ("ssid", "SSID / name", 230, "w"),
                             ("bssid", "BSSID", 150, "w")):
            self._dash_tree.heading(c, text=txt)
            self._dash_tree.column(c, width=w, anchor=a, stretch=(c == "ssid"))
        sb = ttk.Scrollbar(tw, orient="vertical", command=self._dash_tree.yview)
        self._dash_tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._dash_tree.pack(side="left", fill="both", expand=True)
        self._dash_refresh()

    def _dash_read_gps(self):
        if not self.dev:
            self._dash_gps.configure(text="GPS: connect first")
            return
        self._dash_gps.configure(text="GPS: reading…")
        self._do_send("gpsdata")
        self.after(2200, self._dash_parse_gps)

    def _dash_parse_gps(self):
        if self.dev:
            self._do_send("stopscan", event_kind="STOP")
        try:
            txt = self.console.get("1.0", "end")[-2500:]
        except Exception:
            txt = ""

        def g(key):
            m = re.search(key + r"\s*:?\s*([\w.\-]+)", txt, re.I)
            return m.group(1) if m else "?"
        win = getattr(self, "_dash_win", None)
        if win and win.winfo_exists():
            self._dash_gps.configure(
                text=f"GPS  Fix:{g('Fix')}  Sats:{g('Sats')}  "
                     f"Lat:{g('Lat')}  Lon:{g('Lon')}  Alt:{g('Alt')}")

    def _dash_refresh(self):
        win = getattr(self, "_dash_win", None)
        if win is None or not win.winfo_exists():
            return
        aps = self._lists.get("ap", {})
        chans = {}
        g24 = g5 = 0
        for r in aps.values():
            ch = r.get("channel", "")
            if ch:
                chans[ch] = chans.get(ch, 0) + 1
                if self._band(ch) == "5 GHz":
                    g5 += 1
                elif self._band(ch) == "2.4 GHz":
                    g24 += 1
        self._dash_tiles["ap"].configure(text=str(len(aps)))
        self._dash_tiles["sta"].configure(text=str(len(self._lists.get("sta", {}))))
        self._dash_tiles["host"].configure(text=str(len(self._lists.get("host", {}))))
        self._dash_tiles["ch"].configure(text=str(len(chans)))
        self._dash_tiles["g24"].configure(text=str(g24))
        self._dash_tiles["g5"].configure(text=str(g5))

        c = self._dash_canvas
        c.delete("all")
        if chans:
            w = c.winfo_width() or 700
            items = sorted(chans.items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 0)
            n = len(items)
            bw = max(14, min(48, (w - 20) // max(n, 1) - 8))
            mx = max(chans.values())
            x = 14
            for ch, cnt in items:
                h = int(120 * cnt / mx) if mx else 0
                c.create_rectangle(x, 130 - h, x + bw, 130, fill=PALETTE["accent"], outline="")
                c.create_text(x + bw / 2, 142, text=ch, fill=PALETTE["muted"], font=(UI[0], 8))
                c.create_text(x + bw / 2, 128 - h - 6, text=str(cnt), fill=PALETTE["fg"], font=(UI[0], 8))
                x += bw + 8

        def _rk(r):
            try:
                return int(r.get("rssi") or -999)
            except ValueError:
                return -999
        self._dash_tree.delete(*self._dash_tree.get_children())
        for r in sorted(aps.values(), key=_rk, reverse=True):
            self._dash_tree.insert("", "end", values=(r.get("rssi", ""), r.get("channel", ""),
                                   self._band(r.get("channel", "")), r.get("ssid", ""), r.get("bssid", "")))
        win.after(1500, self._dash_refresh)

    # ---- Automated passive survey ---------------------------------------
    def open_survey(self):
        win = tk.Toplevel(self)
        win.title("Automated Survey (passive)")
        win.configure(bg=PALETTE["panel2"])
        win.geometry("780x600")
        win.transient(self)
        self._survey_win = win
        if not hasattr(self, "_survey_inv"):
            self._survey_inv = {}
        self._survey_on = False
        self._survey_i = 0
        self._survey_mask_mac = tk.BooleanVar(value=False)
        self._survey_omit_ssid = tk.BooleanVar(value=False)
        pad = dict(padx=16)

        ttk.Label(win, text="Automated Survey", style="Title.TLabel").pack(anchor="w", pady=(14, 2), **pad)
        ttk.Label(win, text="Passive, receive-only loop (recon → list). Deduplicates devices over time "
                  "and accumulates an inventory you can export. Nothing transmits.",
                  style="CardMuted.TLabel", wraplength=740, justify="left").pack(anchor="w", **pad)

        row = ttk.Frame(win, style="Card.TFrame")
        row.pack(fill="x", pady=(10, 4), **pad)
        self._survey_btn = ttk.Button(row, text="▶ Start survey", style="Accent.TButton",
                                      command=self._survey_toggle)
        self._survey_btn.pack(side="left")
        self._survey_status = ttk.Label(row, text="0 devices", style="CardMuted.TLabel")
        self._survey_status.pack(side="left", padx=12)
        ttk.Checkbutton(row, text="Mask MACs", style="Card.TCheckbutton",
                        variable=self._survey_mask_mac).pack(side="right")
        ttk.Checkbutton(row, text="Omit SSIDs", style="Card.TCheckbutton",
                        variable=self._survey_omit_ssid).pack(side="right", padx=10)

        exp = ttk.Frame(win, style="Card.TFrame")
        exp.pack(fill="x", pady=(2, 6), **pad)
        ttk.Label(exp, text="Export inventory:", style="CardMuted.TLabel").pack(side="left")
        ttk.Button(exp, text="JSON", command=lambda: self._survey_export("json")).pack(side="left", padx=6)
        ttk.Button(exp, text="CSV", command=lambda: self._survey_export("csv")).pack(side="left")
        ttk.Button(exp, text="KML", command=lambda: self._survey_export("kml")).pack(side="left", padx=6)
        ttk.Button(exp, text="Clear", command=self._survey_clear).pack(side="right")

        tw = ttk.Frame(win, style="Card.TFrame")
        tw.pack(fill="both", expand=True, padx=16, pady=(6, 14))
        cols = ("ssid", "bssid", "ch", "band", "rssi", "count", "last")
        self._survey_tree = ttk.Treeview(tw, columns=cols, show="headings")
        for c, txt, w, a in (("ssid", "SSID / name", 190, "w"), ("bssid", "BSSID", 150, "w"),
                             ("ch", "CH", 44, "center"), ("band", "Band", 64, "center"),
                             ("rssi", "RSSI", 54, "center"), ("count", "Seen", 50, "center"),
                             ("last", "Last seen", 150, "w")):
            self._survey_tree.heading(c, text=txt)
            self._survey_tree.column(c, width=w, anchor=a, stretch=(c == "ssid"))
        sb = ttk.Scrollbar(tw, orient="vertical", command=self._survey_tree.yview)
        self._survey_tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._survey_tree.pack(side="left", fill="both", expand=True)
        self._survey_update_table()

    _SURVEY_STEPS = [("recon wifi", 3500), ("stopscan", 600), ("list -a", 1200),
                     ("__merge_ap", 50), ("list -s", 1200), ("__merge_sta", 50)]

    def _survey_toggle(self):
        self._survey_on = not self._survey_on
        if self._survey_on:
            if not self.dev:
                messagebox.showinfo("Not connected", "Connect to the Marauder first.")
                self._survey_on = False
                return
            self._survey_i = 0
            self._survey_btn.configure(text="■ Stop survey")
            self._survey_step()
        else:
            self._survey_btn.configure(text="▶ Start survey")
            if self.dev:
                self._do_send("stopscan", event_kind="STOP")

    def _survey_step(self):
        if not self._survey_on or not self.dev:
            return
        action, delay = self._SURVEY_STEPS[self._survey_i % len(self._SURVEY_STEPS)]
        self._survey_i += 1
        if action == "__merge_ap":
            self._survey_merge("ap")
        elif action == "__merge_sta":
            self._survey_merge("sta")
        elif not marauder_ai.is_active(action):   # safety: passive only
            self._do_send(action)
        win = getattr(self, "_survey_win", None)
        if win and win.winfo_exists():
            win.after(delay, self._survey_step)

    def _survey_merge(self, kind):
        now = _dt.datetime.now().strftime("%H:%M:%S")
        for r in self._lists.get(kind, {}).values():
            key = r.get("bssid") or f"{kind}:{r.get('ssid','')}:{r.get('channel','')}"
            if not key:
                continue
            e = self._survey_inv.get(key)
            if e is None:
                self._survey_inv[key] = {
                    "kind": kind, "bssid": r.get("bssid", ""), "ssid": r.get("ssid", ""),
                    "channel": r.get("channel", ""), "band": self._band(r.get("channel", "")),
                    "rssi": r.get("rssi", ""), "first_seen": now, "last_seen": now, "count": 1}
            else:
                e["last_seen"] = now
                e["count"] += 1
                if r.get("ssid"):
                    e["ssid"] = r["ssid"]
                if r.get("channel"):
                    e["channel"] = r["channel"]
                    e["band"] = self._band(r["channel"])
                try:
                    if r.get("rssi") and int(r["rssi"]) > int(e.get("rssi") or -999):
                        e["rssi"] = r["rssi"]
                except ValueError:
                    pass
        self._survey_update_table()

    def _survey_update_table(self):
        win = getattr(self, "_survey_win", None)
        if win is None or not win.winfo_exists():
            return
        self._survey_tree.delete(*self._survey_tree.get_children())
        for e in sorted(self._survey_inv.values(), key=lambda x: x.get("last_seen", ""), reverse=True):
            self._survey_tree.insert("", "end", values=(e["ssid"], e["bssid"], e["channel"],
                                     e["band"], e["rssi"], e["count"], e["last_seen"]))
        self._survey_status.configure(text=f"{len(self._survey_inv)} devices")

    def _survey_clear(self):
        self._survey_inv = {}
        self._survey_update_table()

    def _survey_rows(self):
        """Inventory rows with privacy controls applied (for export)."""
        mask = self._survey_mask_mac.get()
        omit = self._survey_omit_ssid.get()
        rows = []
        for e in self._survey_inv.values():
            bssid = e["bssid"]
            if mask and bssid and bssid.count(":") == 5:
                bssid = ":".join(bssid.split(":")[:3] + ["xx", "xx", "xx"])
            rows.append({"kind": e["kind"], "ssid": "" if omit else e["ssid"], "bssid": bssid,
                         "channel": e["channel"], "band": e["band"], "rssi": e["rssi"],
                         "count": e["count"], "first_seen": e["first_seen"], "last_seen": e["last_seen"]})
        return rows

    def _survey_export(self, fmt):
        if not self._survey_inv:
            messagebox.showinfo("Nothing to export", "The inventory is empty — start the survey first.")
            return
        rows = self._survey_rows()
        d = self._logs_dir()
        stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        if fmt == "json":
            import json as _json
            fn = os.path.join(d, f"survey_{stamp}.json")
            with open(fn, "w", encoding="utf-8") as f:
                _json.dump(rows, f, indent=2)
        elif fmt == "csv":
            fn = os.path.join(d, f"survey_{stamp}.csv")
            with open(fn, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                w.writeheader()
                w.writerows(rows)
        else:  # kml
            fn = os.path.join(d, f"survey_{stamp}.kml")
            with open(fn, "w", encoding="utf-8") as f:
                f.write('<?xml version="1.0" encoding="UTF-8"?>\n'
                        '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>\n')
                f.write("<!-- No GPS coordinates captured in this build; placemarks omitted. "
                        "Device inventory is listed as a fallback. -->\n")
                for r in rows:
                    f.write(f"<Placemark><name>{(r['ssid'] or r['bssid'])}</name>"
                            f"<description>ch {r['channel']} {r['band']} rssi {r['rssi']}</description>"
                            "</Placemark>\n")
                f.write("</Document></kml>\n")
        self.log_event("EXPORT", f"survey {fmt} -> {os.path.basename(fn)} ({len(rows)} devices)")
        messagebox.showinfo("Survey exported", f"Saved {len(rows)} device(s):\n{fn}")

    # ---- AI assistant (local Ollama) ------------------------------------
    def open_ai_dialog(self):
        win = tk.Toplevel(self)
        win.title("AI Assistant — local Ollama")
        win.configure(bg=PALETTE["panel2"])
        win.geometry("720x620")
        win.transient(self)
        self._ai_win = win
        self._ai_q = queue.Queue()
        self._ai_ready = False
        self._ai_busy = False
        self._ai_survey_on = False
        self._ai_survey_seq = ["recon wifi", "stopscan", "list -a",
                               "recon ble", "stopscan"]
        self._ai_survey_i = 0
        self._ai_history = []
        self._ai_autorun = tk.BooleanVar(value=False)
        pad = dict(padx=16)

        ttk.Label(win, text="AI Assistant", style="Title.TLabel").pack(anchor="w", pady=(16, 2), **pad)
        ttk.Label(win, text="Local, optional analysis via Ollama. It summarizes and recommends; it never "
                  "sends commands itself — suggestions load into the Raw box for you to review and send. "
                  "Active/transmitting steps always require your approval.",
                  style="CardMuted.TLabel", wraplength=680, justify="left").pack(anchor="w", **pad)

        row1 = ttk.Frame(win, style="Card.TFrame")
        row1.pack(fill="x", pady=(12, 4), **pad)
        ttk.Label(row1, text="Model", style="CardMuted.TLabel").pack(side="left")
        self._ai_model = ttk.Entry(row1, width=18, font=MONO)
        self._ai_model.insert(0, marauder_ai.DEFAULT_MODEL)
        self._ai_model.pack(side="left", padx=8)
        ttk.Button(row1, text="Enable / verify", style="Accent.TButton",
                   command=self._ai_enable).pack(side="left")
        self._ai_status = ttk.Label(row1, text="● not connected", style="CardMuted.TLabel")
        self._ai_status.pack(side="left", padx=10)

        row2 = ttk.Frame(win, style="Card.TFrame")
        row2.pack(fill="x", pady=(6, 4), **pad)
        ttk.Button(row2, text="Analyze observations", command=self._ai_analyze).pack(side="left")
        ttk.Button(row2, text="New chat", command=self._ai_newchat).pack(side="left", padx=8)
        self._ai_survey_btn = ttk.Button(row2, text="▶ Passive survey", command=self._ai_survey_toggle)
        self._ai_survey_btn.pack(side="left")
        ttk.Checkbutton(row2, text="Let AI run passive commands", style="Card.TCheckbutton",
                        variable=self._ai_autorun).pack(side="right")

        row3 = ttk.Frame(win, style="Card.TFrame")
        row3.pack(fill="x", pady=(6, 4), **pad)
        ttk.Label(row3, text="Ask", style="CardMuted.TLabel").pack(side="left")
        self._ai_ask_var = tk.StringVar()
        ask = ttk.Entry(row3, textvariable=self._ai_ask_var, font=UI)
        ask.pack(side="left", fill="x", expand=True, padx=(6, 6), ipady=3)
        ask.bind("<Return>", lambda e: self._ai_ask())
        ttk.Button(row3, text="Send", command=self._ai_ask).pack(side="left")

        ow = ttk.Frame(win, style="Card.TFrame")
        ow.pack(fill="both", expand=True, padx=16, pady=(8, 16))
        self._ai_out_txt = tk.Text(ow, wrap="word", relief="flat", bg="#070b0f",
                                   fg=PALETTE["fg"], font=UI, padx=10, pady=8)
        sb = ttk.Scrollbar(ow, orient="vertical", command=self._ai_out_txt.yview)
        self._ai_out_txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._ai_out_txt.pack(side="left", fill="both", expand=True)
        self._ai_drain()

    def _ai_out(self, s):
        self._ai_q.put(s)

    def _ai_drain(self):
        win = getattr(self, "_ai_win", None)
        if win is None or not win.winfo_exists():
            return
        try:
            while True:
                s = self._ai_q.get_nowait()
                self._ai_out_txt.insert("end", s)
                self._ai_out_txt.see("end")
        except queue.Empty:
            pass
        win.after(80, self._ai_drain)

    def _ai_enable(self):
        def work():
            model = self._ai_model.get().strip() or marauder_ai.DEFAULT_MODEL
            ok, models, err = marauder_ai.check_ollama()
            if not ok:
                self._ai_ready = False
                self._ai_out(f"Could not reach Ollama at {marauder_ai.OLLAMA_HOST}\n  {err}\n"
                             "Install/run Ollama (https://ollama.com) and `ollama pull "
                             f"{model}`.\n")
                self._ai_set_status("● not connected", PALETTE["warn"])
                return
            if not marauder_ai.has_model(models, model):
                self._ai_ready = False
                self._ai_out(f"Connected to Ollama, but model '{model}' isn't installed.\n"
                             f"Installed: {', '.join(models) or '(none)'}\n"
                             f"Run:  ollama pull {model}\n")
                self._ai_set_status("● model missing", PALETTE["warn"])
                return
            self._ai_ready = True
            self._ai_out(f"Connected to Ollama — model '{model}' is available. Ready.\n")
            self._ai_set_status("● ready", PALETTE["ok"])
        threading.Thread(target=work, daemon=True).start()

    def _ai_set_status(self, text, color):
        win = getattr(self, "_ai_win", None)
        if win and win.winfo_exists():
            win.after(0, lambda: self._ai_status.configure(text=text, foreground=color))

    def _ai_context(self):
        try:
            events = self.eventlog.get("1.0", "end")  # already redacted
        except Exception:
            events = ""
        return marauder_ai.sanitize_context(self._lists.get("ap", {}),
                                            self._lists.get("sta", {}),
                                            self._lists.get("host", {}), events)

    def _ai_newchat(self):
        self._ai_history = []
        self._ai_out("\n[new conversation — history cleared]\n")

    def _ai_chat(self, user_text):
        """Conversational turn with memory. Current observations are attached so the
        model always sees the latest state; its RUN: commands are then dispatched."""
        if not self._ai_ready:
            self._ai_out("Enable / verify the model first.\n")
            return
        if self._ai_busy:
            return
        self._ai_busy = True
        model = self._ai_model.get().strip() or marauder_ai.DEFAULT_MODEL
        content = f"{user_text}\n\n[Current observations]\n{self._ai_context()}"
        self._ai_history.append({"role": "user", "content": content})

        def work():
            acc = []
            try:
                marauder_ai.chat(self._ai_history, model=model,
                                 stream_cb=lambda s: (acc.append(s), self._ai_out(s)))
            except Exception as e:  # noqa: BLE001
                self._ai_out(f"\n[AI error] {e}\n")
                self._ai_busy = False
                return
            reply = "".join(acc)
            self._ai_history.append({"role": "assistant", "content": reply})
            self._ai_out("\n")
            for cmd in marauder_ai.extract_run_commands(reply):
                self._ai_dispatch(cmd)
            self._ai_busy = False
        threading.Thread(target=work, daemon=True).start()

    def _ai_dispatch(self, cmd):
        """Run a model-requested command: passive ones auto-run if allowed; anything
        that transmits is queued in the Raw box for the operator to approve."""
        if marauder_ai.is_active(cmd):
            win = getattr(self, "_ai_win", None)
            if win and win.winfo_exists():
                win.after(0, lambda: self.raw_var.set(cmd))
            self._ai_out(f"[needs approval — transmitting] {cmd}  →  loaded in Raw box; review and Send.\n")
        elif self._ai_autorun.get() and self.dev:
            win = getattr(self, "_ai_win", None)
            if win and win.winfo_exists():
                win.after(0, lambda c=cmd: self._do_send(c))
            self._ai_out(f"[auto-run passive] {cmd}\n")
        else:
            win = getattr(self, "_ai_win", None)
            if win and win.winfo_exists():
                win.after(0, lambda: self.raw_var.set(cmd))
            self._ai_out(f"[suggested] {cmd}  →  loaded in Raw box (enable auto-run, or Send).\n")

    def _ai_analyze(self):
        self._ai_out("\n--- Analysis ---\n")
        self._ai_chat("Summarize what's present and note anything notable.")

    def _ai_ask(self):
        q = self._ai_ask_var.get().strip()
        if not q:
            return
        self._ai_ask_var.set("")
        self._ai_out(f"\n> {q}\n")
        self._ai_chat(q)

    def _ai_suggest(self):
        if not self._ai_ready:
            self._ai_out("Enable / verify the model first.\n")
            return
        if self._ai_busy:
            return
        self._ai_busy = True
        model = self._ai_model.get().strip() or marauder_ai.DEFAULT_MODEL
        prompt = ("Given these observations, recommend the single most useful NEXT Marauder "
                  "command (prefer passive reconnaissance). Reply with ONLY the command on one "
                  "line, nothing else.\n\n" + self._ai_context())

        def work():
            try:
                out = marauder_ai.generate(prompt, model=model)
                cmd = out.strip().splitlines()[0].strip().strip("`").strip() if out.strip() else ""
                if not cmd:
                    self._ai_out("\n[no suggestion]\n")
                    return
                active = marauder_ai.is_active(cmd)
                tag = "ACTIVE — needs your explicit approval" if active else "passive"
                self._ai_out(f"\nSuggested ({tag}): {cmd}\n"
                             "Loaded into the Raw box — review and press Send to run it.\n")
                win = getattr(self, "_ai_win", None)
                if win and win.winfo_exists():
                    win.after(0, lambda: self.raw_var.set(cmd))
            except Exception as e:  # noqa: BLE001
                self._ai_out(f"\n[AI error] {e}\n")
            finally:
                self._ai_busy = False
        threading.Thread(target=work, daemon=True).start()

    def _ai_survey_toggle(self):
        self._ai_survey_on = not self._ai_survey_on
        if self._ai_survey_on:
            if not self.dev:
                messagebox.showinfo("Not connected", "Connect to the Marauder first.")
                self._ai_survey_on = False
                return
            self._ai_survey_i = 0
            self._ai_survey_btn.configure(text="■ Stop survey")
            self._ai_out("\n[passive survey started — receive-only loop]\n")
            self._ai_survey_step()
        else:
            self._ai_survey_btn.configure(text="▶ Passive survey")
            self._ai_out("[passive survey stopped]\n")
            if self.dev:
                self._do_send("stopscan", event_kind="STOP")

    def _ai_survey_step(self):
        if not self._ai_survey_on or not self.dev:
            return
        cmd = self._ai_survey_seq[self._ai_survey_i % len(self._ai_survey_seq)]
        self._ai_survey_i += 1
        if marauder_ai.is_active(cmd):   # safety: never transmit from the survey loop
            cmd = "stopscan"
        self._do_send(cmd)
        self.after(6000, self._ai_survey_step)

    # ---- firmware flasher (V8 / ESP32-C5) --------------------------------
    def open_firmware_dialog(self):
        win = tk.Toplevel(self)
        win.title("Firmware updater — Marauder V8 (ESP32-C5)")
        win.configure(bg=PALETTE["panel2"])
        win.geometry("660x580")
        win.transient(self)
        self._fw_win = win
        self._fw_q = queue.Queue()
        self._fw_url = None
        self._fw_busy = False
        pad = dict(padx=16)

        ttk.Label(win, text="Firmware updater", style="Title.TLabel").pack(anchor="w", pady=(16, 2), **pad)
        ttk.Label(win, text="Flashes the official Marauder V8 build (the `_v8` asset, an ESP32-C5 image). "
                  "The chip is auto-detected, so the architecture can't be set wrong. Keep the device "
                  "plugged in and do not unplug it while flashing.",
                  style="CardMuted.TLabel", wraplength=620, justify="left").pack(anchor="w", **pad)

        portrow = ttk.Frame(win, style="Card.TFrame")
        portrow.pack(fill="x", pady=(12, 4), **pad)
        port = self._connected_port or self._port_map.get(self.port_cb.get(), self.port_cb.get())
        self._fw_port = port
        ttk.Label(portrow, text=f"Port:  {port or '(none — connect or pick a port first)'}",
                  style="Card.TLabel", font=MONO).pack(side="left")
        ttk.Button(portrow, text="Read chip info", command=self._fw_chipinfo).pack(side="right")

        srcrow = ttk.Frame(win, style="Card.TFrame")
        srcrow.pack(fill="x", pady=(10, 4), **pad)
        ttk.Button(srcrow, text="Fetch + download latest V8 firmware",
                   style="Accent.TButton", command=self._fw_fetch).pack(side="left")
        ttk.Button(srcrow, text="Browse .bin…", command=self._fw_browse).pack(side="left", padx=8)

        self._fw_file = tk.StringVar(value="")
        ttk.Label(win, text="Firmware file to flash:", style="CardMuted.TLabel").pack(anchor="w", pady=(8, 2), **pad)
        fe = ttk.Entry(win, textvariable=self._fw_file, font=MONO)
        fe.pack(fill="x", ipady=3, **pad)
        self._fw_verline = tk.StringVar(value=self._fw_version_line())
        ttk.Label(win, textvariable=self._fw_verline, style="CardMuted.TLabel").pack(anchor="w", **pad)
        self._fw_file.trace_add("write", lambda *_: self._fw_verline.set(self._fw_version_line()))

        actrow = ttk.Frame(win, style="Card.TFrame")
        actrow.pack(fill="x", pady=(10, 4), **pad)
        ttk.Label(actrow, text="Baud", style="CardMuted.TLabel").pack(side="left")
        self._fw_baud = ttk.Combobox(actrow, values=["115200", "460800", "921600"],
                                     state="readonly", width=8)
        self._fw_baud.set("921600")
        self._fw_baud.pack(side="left", padx=8)
        self._fw_flash_btn = ttk.Button(actrow, text="⚡ Flash firmware",
                                        style="Stop.TButton", command=self._fw_flash)
        self._fw_flash_btn.pack(side="right")

        ttk.Label(win, text="esptool output", style="CardMuted.TLabel").pack(anchor="w", pady=(10, 2), **pad)
        lw = ttk.Frame(win, style="Card.TFrame")
        lw.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        self._fw_log = tk.Text(lw, height=12, wrap="word", relief="flat", bg="#070b0f",
                               fg=PALETTE["fg"], font=MONO, padx=10, pady=8)
        sb = ttk.Scrollbar(lw, orient="vertical", command=self._fw_log.yview)
        self._fw_log.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._fw_log.pack(side="left", fill="both", expand=True)

        self._fw_drain()

    def _fw_out(self, s):
        self._fw_q.put(s)

    def _fw_drain(self):
        win = getattr(self, "_fw_win", None)
        if win is None or not win.winfo_exists():
            return
        try:
            while True:
                s = self._fw_q.get_nowait()
                self._fw_log.insert("end", s)
                self._fw_log.see("end")
        except queue.Empty:
            pass
        win.after(80, self._fw_drain)

    def _fw_free_port(self):
        """Release the serial port (and reader) so esptool can own it."""
        if self.dev:
            self._fw_out("Disconnecting GUI to free the port for esptool…\n")
            self._disconnect()

    def _detect_current_fw_version(self):
        """Best-effort installed version, read from the device's boot/serial text."""
        try:
            txt = self.console.get("1.0", "end")
        except Exception:
            txt = ""
        return marauder_flash.parse_device_version(txt)

    def _fw_version_line(self):
        cur = self._detect_current_fw_version()
        tgt = marauder_flash.version_from_filename(self._fw_file.get().strip())
        s = f"Installed: {marauder_flash.version_str(cur)}    •    To flash: {marauder_flash.version_str(tgt)}"
        if cur and tgt:
            if tgt > cur:
                s += "   (newer ✓)"
            elif tgt == cur:
                s += "   (same version)"
            else:
                s += "   (OLDER — downgrade)"
        return s

    def _fw_browse(self):
        p = filedialog.askopenfilename(title="Select firmware .bin",
                                       filetypes=[("Firmware", "*.bin"), ("All files", "*.*")])
        if p:
            self._fw_file.set(p)

    def _fw_fetch(self):
        if self._fw_busy:
            return
        fwdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "firmware")

        def work():
            try:
                self._fw_out("Fetching latest release from GitHub…\n")
                rel = marauder_flash.fetch_latest_release()
                asset = marauder_flash.pick_asset(rel["assets"], "v8")
                if not asset:
                    self._fw_out("No `_v8` asset found in the latest release.\n")
                    return
                self._fw_out(f"Latest: {rel['tag']}  ->  {asset['name']} "
                             f"({asset['size'] // 1024} KB)\nDownloading…\n")
                os.makedirs(fwdir, exist_ok=True)
                dest = os.path.join(fwdir, asset["name"])
                marauder_flash.download_asset(asset["url"], dest)
                self._fw_out(f"Saved: {dest}\n")
                win = getattr(self, "_fw_win", None)
                if win and win.winfo_exists():
                    win.after(0, lambda: self._fw_file.set(dest))
            except Exception as e:  # noqa: BLE001
                self._fw_out(f"[fetch error] {e}\n")
        threading.Thread(target=work, daemon=True).start()

    def _fw_chipinfo(self):
        if self._fw_busy or not self._fw_port:
            if not self._fw_port:
                self._fw_out("No port available — connect or select a port first.\n")
            return
        self._fw_free_port()
        port = self._fw_port

        def work():
            marauder_flash.run_esptool(marauder_flash.chipinfo_args(port), self._fw_out)
        threading.Thread(target=work, daemon=True).start()

    def _fw_flash(self):
        if self._fw_busy:
            return
        port = self._fw_port
        path = self._fw_file.get().strip()
        if not port:
            messagebox.showwarning("No port", "Connect or select a port first.")
            return
        if not path or not os.path.isfile(path):
            messagebox.showwarning("No firmware", "Fetch the latest firmware or Browse to a .bin first.")
            return
        # Version comparison: warn on a downgrade / same-version re-flash.
        cur = self._detect_current_fw_version()
        tgt = marauder_flash.version_from_filename(path)
        if cur and tgt and tgt <= cur:
            rel = "the same as" if tgt == cur else "OLDER than"
            if not messagebox.askyesno(
                    "Not a newer version",
                    f"The firmware you're about to flash (v{marauder_flash.version_str(tgt)}) is "
                    f"{rel} the installed version (v{marauder_flash.version_str(cur)}).\n\n"
                    "Flash it anyway?"):
                return
        ver_note = (f"  (v{marauder_flash.version_str(tgt)} over v{marauder_flash.version_str(cur)})"
                    if (cur or tgt) else "")
        if not messagebox.askyesno(
                "Flash firmware",
                f"Write this firmware to the Marauder on {port}?\n\n{os.path.basename(path)}{ver_note}\n\n"
                "The chip is auto-detected. Do NOT unplug the device while flashing. Continue?"):
            return
        self._fw_free_port()
        self._fw_busy = True
        self._fw_flash_btn.configure(state="disabled")
        baud = int(self._fw_baud.get())

        def work():
            ok = marauder_flash.run_esptool(
                marauder_flash.flash_args(port, path, baud=baud), self._fw_out)
            self._fw_out("\n✓ Flash complete. The device should reboot into the new firmware.\n"
                         if ok else "\n✗ Flash failed — see the output above.\n")
            self._fw_busy = False
            win = getattr(self, "_fw_win", None)
            if win and win.winfo_exists():
                win.after(0, lambda: self._fw_flash_btn.configure(state="normal"))
        threading.Thread(target=work, daemon=True).start()

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
