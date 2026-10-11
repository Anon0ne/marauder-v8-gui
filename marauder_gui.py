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
from app_paths import APP_DIR

import os
import re
import csv
import sys
import queue
import serial
import threading
import time
import webbrowser
import datetime as _dt

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

__version__ = "0.4.2"
AUTHOR = "Justin Funderburk"
CONTACT = "justin@bizhostnc.com"

# Make companion modules importable regardless of the launch directory.
sys.path.insert(0, str(APP_DIR))

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
    return re.sub(r'''(?<!\S)(-p\s+)(?:"[^"]*"|'[^']*'|\S+)''', r"\1***", cmd)


def command_runs(base: str) -> bool:
    """True if `base` starts a long-running operation that needs a Stop."""
    toks = base.strip().split()
    if toks[:1] == ["recon"] and toks[1:2] in (["wifi"], ["ble"]):
        return True
    return base.strip() in {"gpsdata", "gps -t"} or base.strip().startswith(RUNNING_PREFIXES)



def spreadsheet_cell(value):
    """Keep untrusted network names from becoming spreadsheet formulas."""
    if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')):
        return "'" + value
    return value

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
        self.rx_queue: queue.Queue[str] = queue.Queue(maxsize=256)
        self._rx_dropped = 0
        self._ui_queue = queue.Queue()
        self._replay_iter = None
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
        self._lists = {"ap": {}, "sta": {}, "ssid": {}, "host": {}, "ble": {}}
        self._ble_history = {}
        self._sd_rows = []
        self._record_fp = None
        self._survey_record_owned = False
        self._gps_fix = None
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
        tools.add_command(label="BLE Devices…", command=self.open_ble_devices)
        tools.add_command(label="SD Files…", command=self.open_sd_browser)
        tools.add_command(label="Export inventory report…", command=self.export_inventory_report)
        tools.add_separator()
        tools.add_command(label="Start / stop recording…", command=self.toggle_recording)
        tools.add_command(label="Replay session…", command=self.replay_session)
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
            detail = f"{port} @ {baud}: {e}"
            self._emit(f"[connection failed: {detail}]\n", "sys")
            self.log_event("ERROR", f"connection failed: {detail}")
            self.status.configure(text=f"● Connection failed  {port}", foreground=PALETTE["muted"])
            if not silent_fail:
                messagebox.showerror("Connection failed", detail)
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
        self._cancel_surveys()
        self._line_buf = ""
        self._parse_mode = None
        self.reader_stop.set()
        if self.reader_thread:
            self.reader_thread.join(timeout=1.0)
        if self.dev:
            self.dev.close()
        self.dev = None
        self._connected_port = None
        self.running = False
        self._gps_fix = None
        self._gps_parts = {}
        self._gps_valid = None
        while True:
            try:
                self.rx_queue.get_nowait()
            except queue.Empty:
                break
        self.connect_btn.configure(text="Connect")
        self.status.configure(text="● Disconnected", foreground=PALETTE["muted"])
        self._emit("[disconnected]\n", "sys")
        self.log_event("DISCONNECT", port or "")

    def _finish_survey_recording(self):
        if getattr(self, '_survey_record_owned', False):
            if self._record_fp:
                try:
                    self._record_fp.close()
                except OSError as error:
                    self._emit(f"[recording close failed: {error}]\n", 'sys')
                self._record_fp = None
            self._survey_record_owned = False

    def _cancel_surveys(self):
        self._finish_survey_recording()
        self._survey_on = False
        self._ai_survey_on = False
        job = getattr(self, '_survey_job', None)
        if job is not None:
            self.after_cancel(job)
            self._survey_job = None
        for name, text in [('_survey_btn', '▶ Start survey'), ('_ai_survey_btn', '▶ Passive survey')]:
            widget = getattr(self, name, None)
            if widget and widget.winfo_exists():
                widget.configure(text=text)

    def _reader_loop(self):
        device = self.dev
        while not self.reader_stop.is_set() and device:
            try:
                data = device.read_available()
            except Exception as error:
                self._ui_queue.put(lambda d=device, e=str(error): self._serial_failed(d, e))
                break
            if data:
                try:
                    self.rx_queue.put(data, timeout=0.1)
                except queue.Full:
                    self._rx_dropped += 1
            else:
                self.reader_stop.wait(0.05)

    def _serial_failed(self, device, error):
        if self.dev is device:
            self._disconnect()
            self._emit(f"[serial disconnected: {error}]\n", 'sys')

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
            self._record_event("tx", redact(cmd))
            self._emit(f">> {shown}\n", "tx")
        except Exception as e:
            self._emit(f"[send failed: {e}]\n", "sys")
            self.log_event("ERROR", f"send failed: {shown}")
            if isinstance(e, (serial.SerialException, OSError)):
                self._disconnect()
            return
        kind = event_kind or ("START" if command_runs(cmd) else "SEND")
        if kind == "START":
            self.running = True
            self._last_running_base = cmd
        self.log_event(kind, shown)
        if kind == "STOP":
            self.running = False
            self._last_running_base = ""

    def stop_running(self):
        """Stop the running op and record it. Safe to press any time.

        Recon has its own stop verb; everything else halts with `stopscan`.
        """
        if not self.dev:
            messagebox.showinfo("Not connected", "Connect to the Marauder first.")
            return
        if getattr(self, '_survey_on', False):
            self._survey_toggle()
            self.running = False
            self._last_running_base = ""
            return
        if getattr(self, '_ai_survey_on', False):
            self._ai_survey_toggle()
            self.running = False
            self._last_running_base = ""
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
                logs = os.path.join(str(APP_DIR), "logs")
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
            for _ in range(32):
                try:
                    callback = self._ui_queue.get_nowait()
                except queue.Empty:
                    break
                callback()

            if self._rx_dropped:
                dropped, self._rx_dropped = self._rx_dropped, 0
                self._emit(f'[receive buffer full: dropped {dropped} chunks]\n', 'sys')
            for _ in range(16):
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
        self._record_event("rx", chunk)
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
                self._track_gps(line)
                if self._track_list_line(line):
                    picker_dirty = True
            except Exception:
                pass
        for inventory in [*self._lists.values(), self._ble_history]:
            while len(inventory) > 4096:
                inventory.pop(next(iter(inventory)))
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
        relation = re.match(r'^\d+:\s*(ap|sta):\s*([0-9a-f:]{17})\s*->\s*(ap|sta):\s*([0-9a-f:]{17})', low)
        if relation and relation.group(1) != relation.group(3):
            station = relation.group(2) if relation.group(1) == 'sta' else relation.group(4)
            ap_mac = relation.group(4) if relation.group(1) == 'sta' else relation.group(2)
            if int(station[:2], 16) & 1:
                return False
            data = self._lists['sta']
            index = next((i for i, row in data.items() if row.get('bssid') == station), str(len(data)))
            data[index] = {'index': index, 'ssid': station, 'bssid': station,
                           'ap_bssid': ap_mac, 'channel': '', 'rssi': '', '_observed_at': time.monotonic()}
            return True
        if low.startswith("#"):
            cmd = low[1:].strip()
            if cmd.startswith("list -a"):
                mode = "ap"
            elif cmd.startswith("list -s"):
                mode = "sta"
            elif cmd.startswith("list -b"):
                mode = "ble"
            elif cmd.startswith("ls"):
                mode = "sd"
            elif cmd.startswith("list -c"):
                mode = "ssid"
            elif cmd.startswith(("arpscan", "pingscan")):
                mode = "host"
            else:
                mode = None
            self._parse_mode = mode
            if mode:
                if mode == "sd":
                    self._sd_rows = []
                else:
                    self._lists[mode] = {}     # fresh capture
                self._host_n = 0
                return True
            return False
        if not low:
            return False
        if self._parse_mode == "sd":
            fields = raw.split("\t")
            if len(fields) >= 2 and fields[-1].strip().isdigit():
                name = "\t".join(fields[:-1]).strip()
                if name and name not in (".", ".."):
                    self._sd_rows.append((name, int(fields[-1])))
                    return True
            return False
        if self._parse_mode == "ble":
            return self._parse_ble(raw)
        if not self._parse_mode:
            if self._parse_ble(raw, recon_only=True):
                return True
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
                           "rssi": parsed.get("rssi", ""), "_observed_at": time.monotonic()}
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
                row["index"], spreadsheet_cell(row["ssid"]), row["bssid"],
                row["channel"], row["rssi"],
            ])
            self.csv_file.flush()
            n = len(self.csv_seen)
            self.csv_status.configure(text=f"{n} row(s) logged")

    def _toggle_csv(self):
        if self.csv_logging.get():
            logs = os.path.join(str(APP_DIR), "logs")
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
        if int(self.console.count("1.0", "end", "chars")[0]) > 250000:
            self.console.delete("1.0", "end-200000c")
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
        d = os.path.join(str(APP_DIR), "logs")
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
        win.geometry("600x510")
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
        ttk.Label(win, text="Marauder V8 Control is a desktop workspace for operating an ESP32 "
                  "Marauder over USB serial, reviewing wireless observations, and recording "
                  "sessions. It brings radio inventories, capture tools, firmware updates, "
                  "and optional local AI analysis together in one interface.",
                  style="CardMuted.TLabel", wraplength=550, justify="left").pack(
                      anchor="w", padx=22, pady=(14, 8))
        ttk.Label(win, text="• Wi-Fi surveys, manual BLE inventory and RF dashboard\n"
                  "• SD browser, PCAP tools, JSON/CSV exports and GPS-based KML\n"
                  "• Session recording and receive-only offline replay\n"
                  "• Local Ollama/NPU AI and optional hosted AI without a GPU\n"
                  "• Firmware flashing and manual or automated setup",
                  style="Card.TLabel", wraplength=550, justify="left").pack(anchor="w", padx=22)
        github = "https://github.com/Anon0ne/marauder-v8-gui"
        project = ttk.Label(win, text=github, style="Card.TLabel",
                            foreground=PALETTE["accent"], cursor="hand2", takefocus=True)
        project.pack(anchor="w", padx=22, pady=(12, 0))
        project.bind("<Button-1>", lambda e: webbrowser.open(github))
        project.bind("<Return>", lambda e: webbrowser.open(github))

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

    def _new_tool_window(self):
        return tk.Toplevel(self)

    def open_dashboard(self):
        win = self._new_tool_window()
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
        drive = ttk.Frame(win, style="Card.TFrame")
        drive.pack(fill="x", pady=6, **pad)
        ttk.Button(drive, text="Start Wardrive", command=self._dash_start_wardrive).pack(side="left")
        ttk.Button(drive, text="Stop", command=self.stop_running).pack(side="left", padx=4)
        self._poi_label = tk.StringVar()
        ttk.Entry(drive, textvariable=self._poi_label, width=22).pack(side="left", padx=4)
        ttk.Button(drive, text="Mark POI", command=self._dash_mark_poi).pack(side="left")
        self._wardrive_status = ttk.Label(win, text="Manual wardrive: GPS module and SD card required. POIs require a GPS fix.", style="CardMuted.TLabel", wraplength=850)
        self._wardrive_status.pack(anchor="w", **pad)


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

    def _dash_start_wardrive(self):
        if not self.dev or self.running:
            self._wardrive_status.configure(text="Connect first and stop the current operation before starting wardrive.")
            return
        self._wardrive_reply = False
        self._do_send("wardrive")
        self._wardrive_status.configure(text="Wardrive requested. Waiting for device output; the GUI cannot confirm SD writes.")
        self.after(3500, self._dash_wardrive_timeout)

    def _dash_wardrive_timeout(self):
        if not getattr(self, '_wardrive_reply', False):
            self._wardrive_status.configure(text="No wardrive confirmation. Check startup GPS detection, firmware GPS/SD support, and SD card. Stop before retrying.")

    def _dash_mark_poi(self):
        if not self.dev or not self.running or getattr(self, '_last_running_base', '').strip() != 'wardrive':
            self._wardrive_status.configure(text="Start wardrive before marking a POI.")
            return
        label = self._poi_label.get().strip()
        if len(label) > 80 or any(ord(c) < 32 or c in '<>&' for c in label):
            self._wardrive_status.configure(text="Use a label of up to 80 characters without control characters or < > &.")
            return
        self._poi_reply = False
        self._do_send('wardrivepoi' + (' ' + label if label else ''))
        self._wardrive_status.configure(text="POI requested at the device's current GPS location. Waiting for acknowledgement.")
        self.after(3500, self._dash_poi_timeout)

    def _dash_poi_timeout(self):
        if not getattr(self, '_poi_reply', False):
            self._wardrive_status.configure(text="No POI acknowledgement. Firmware requires active wardrive, a GPS fix and an opened SD POI file.")

    def _dash_read_gps(self):
        if not self.dev:
            self._dash_gps.configure(text="GPS: connect first")
            return
        self._dash_gps_values = {}
        self._dash_gps.configure(text="GPS: requesting status without changing scan mode…")
        for field in ('fix', 'sat', 'lat', 'lon', 'alt'):
            if not self.dev:
                return
            self._do_send('gps -g ' + field)
        job = getattr(self, '_dash_gps_job', None)
        if job is not None:
            self.after_cancel(job)
        self._dash_gps_job = self.after(2200, self._dash_parse_gps)

    def _dash_parse_gps(self):
        self._dash_gps_job = None
        values = getattr(self, '_dash_gps_values', {})
        win = getattr(self, '_dash_win', None)
        if win and win.winfo_exists():
            if not values:
                self._dash_gps.configure(text="GPS: no status reply. Check device help, firmware target and startup GPS Not Found message.")
            else:
                self._dash_gps.configure(text='GPS  ' + '  '.join(
                    key + ':' + values.get(key, '?') for key in ('Fix', 'Sats', 'Lat', 'Lon', 'Alt')))

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
        win = self._new_tool_window()
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
        self._survey_log = tk.BooleanVar(value=True)
        pad = dict(padx=16)

        ttk.Label(win, text="Automated Survey", style="Title.TLabel").pack(anchor="w", pady=(14, 2), **pad)
        ttk.Label(win, text="Continuous receive-only Wi-Fi reconnaissance. Deduplicates devices over time "
                  "and accumulates an inventory you can export. Nothing transmits.",
                  style="CardMuted.TLabel", wraplength=740, justify="left").pack(anchor="w", **pad)

        row = ttk.Frame(win, style="Card.TFrame")
        row.pack(fill="x", pady=(10, 4), **pad)
        self._survey_btn = ttk.Button(row, text="▶ Start survey", style="Accent.TButton",
                                      command=self._survey_toggle)
        self._survey_btn.pack(side="left")
        self._survey_status = ttk.Label(row, text="0 devices", style="CardMuted.TLabel")
        self._survey_status.pack(side="left", padx=12)
        ttk.Checkbutton(row, text="Record session", variable=self._survey_log,
                        style="Card.TCheckbutton").pack(side="left")
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

    def _survey_toggle(self):
        if self._survey_on:
            self._survey_on = False
            job = getattr(self, '_survey_job', None)
            if job is not None:
                self.after_cancel(job)
                self._survey_job = None
            self._survey_btn.configure(text="▶ Start survey")
            if self.dev:
                self._do_send("stopscan", event_kind="STOP")
            self._finish_survey_recording()
            return
        if not self.dev:
            messagebox.showinfo("Not connected", "Connect to the Marauder first.")
            return
        if getattr(self, '_ai_survey_on', False):
            messagebox.showinfo("Survey running", "Stop the AI survey before starting another survey.")
            return
        if self.running:
            messagebox.showinfo("Operation running", "Stop the current operation before starting a survey.")
            return
        setting = getattr(self, '_survey_log', None)
        if setting is not None and setting.get() and self._record_fp is None:
            try:
                path = os.path.join(self._logs_dir(), 'survey_' + _dt.datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.jsonl')
                self._record_fp = open(path, 'x', encoding='utf-8')
                self._survey_record_owned = True
                self._record_event('meta', 'Continuous passive Wi-Fi survey; BLE acquisition is manual active scanning.')
                self.log_event('RECORD', path)
            except OSError as error:
                messagebox.showerror("Recording failed", str(error))
                return
        self._survey_on = True
        self._survey_btn.configure(text="■ Stop survey")
        self._do_send("recon wifi")
        self._survey_step()

    def _survey_step(self):
        self._survey_job = None
        if not self._survey_on or not self.dev:
            self._survey_on = False
            self._finish_survey_recording()
            self._survey_btn.configure(text="▶ Start survey")
            return
        self._survey_merge("ap")
        self._survey_merge("sta")
        self._survey_merge("ble")
        self._survey_job = self.after(1200, self._survey_step)

    def _survey_merge(self, kind):
        now = _dt.datetime.now().isoformat(timespec="seconds")
        for r in self._lists.get(kind, {}).values():
            key = r.get("bssid") or f"{kind}:{r.get('ssid','')}:{r.get('channel','')}"
            if not key:
                continue
            e = self._survey_inv.get(key)
            if e is None:
                self._survey_inv[key] = {
                    "kind": kind, "bssid": r.get("bssid", ""), "ssid": r.get("ssid", ""),
                    "channel": r.get("channel", ""), "band": self._band(r.get("channel", "")),
                    "rssi": r.get("rssi", ""), "first_seen": now, "last_seen": now, "count": 1, "gps": self._gps_fix, "_observation": r.get("_observed_at")}
            else:
                observed = r.get("_observed_at")
                if observed == e.get("_observation"):
                    continue
                e["_observation"] = observed
                e["last_seen"] = now
                if self._gps_fix:
                    e["gps"] = self._gps_fix
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
        while len(self._survey_inv) > 4096:
            self._survey_inv.pop(next(iter(self._survey_inv)))
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
                         "count": e["count"], "first_seen": e["first_seen"], "last_seen": e["last_seen"], "gps": e.get("gps")})
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
                w.writerows({key: spreadsheet_cell(value) for key, value in row.items()} for row in rows)
        else:  # kml
            fn = os.path.join(d, f"survey_{stamp}.kml")
            with open(fn, "w", encoding="utf-8") as f:
                f.write('<?xml version="1.0" encoding="UTF-8"?>\n'
                        '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>\n')
                from xml.sax.saxutils import escape
                for r in rows:
                    if not r.get("gps"):
                        continue
                    lat, lon = r["gps"]
                    title = escape(str(r["ssid"] or r["bssid"]))
                    desc = escape(f"ch {r['channel']} {r['band']} rssi {r['rssi']}")
                    f.write(f"<Placemark><name>{title}</name><description>{desc}</description>"
                            f"<Point><coordinates>{lon},{lat},0</coordinates></Point></Placemark>\n")
                f.write("</Document></kml>\n")
        self.log_event("EXPORT", f"survey {fmt} -> {os.path.basename(fn)} ({len(rows)} devices)")
        messagebox.showinfo("Survey exported", f"Saved {len(rows)} device(s):\n{fn}")

    # ---- AI assistant (local Ollama) ------------------------------------
    def open_ai_dialog(self):
        existing = getattr(self, '_ai_win', None)
        if existing is not None and existing.winfo_exists():
            existing.lift()
            return
        win = self._new_tool_window()
        win.title("AI Assistant — local inference")
        win.configure(bg=PALETTE["panel2"])
        win.geometry("850x680")
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
        ttk.Label(win, text="Choose local AI or an optional cloud provider; cloud AI needs no GPU. Automatic commands are limited "
                  "to an explicit passive allowlist; all other suggestions need manual review. "
                  "Intel NPU uses a separate OpenVINO model folder.",
                  style="CardMuted.TLabel", wraplength=680, justify="left").pack(anchor="w", **pad)

        backend_row = ttk.Frame(win, style='Card.TFrame')
        backend_row.pack(fill='x', pady=(12, 0), **pad)
        ttk.Label(backend_row, text='Engine', style='CardMuted.TLabel').pack(side='left')
        self._ai_backend = ttk.Combobox(backend_row, state='readonly', width=26,
                                       values=['Ollama', 'Intel NPU (OpenVINO)', 'Hybrid (NPU + GPU)', 'Cloud: OpenRouter Free', 'Cloud: Gemini'])
        self._ai_backend.set('Ollama')
        self._ai_choice = 'Ollama'
        self._ai_backend.pack(side='left', padx=8)
        self._ai_backend.bind('<<ComboboxSelected>>', self._ai_backend_changed)
        ttk.Button(backend_row, text='Select NPU model folder...',
                   command=self._ai_browse_npu).pack(side='left')
        self._cloud_config = {}
        ttk.Button(backend_row, text='Cloud settings...', command=self._ai_cloud_settings).pack(side='left', padx=8)
        self._ai_verified = None
        self._ai_npu_folder = str(APP_DIR / 'models' / 'phi35-npu')
        self._hybrid = None
        row1 = ttk.Frame(win, style="Card.TFrame")
        row1.pack(fill="x", pady=(12, 4), **pad)
        ttk.Label(row1, text="Model", style="CardMuted.TLabel").pack(side="left")
        self._ai_model = ttk.Entry(row1, width=40, font=MONO)
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
        ttk.Button(row2, text="Save diagnostic report", command=self._ai_report).pack(side="left", padx=8)
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
                if callable(s):
                    s()
                    continue
                self._ai_out_txt.insert("end", s)
                if int(self._ai_out_txt.count("1.0", "end", "chars")[0]) > 250000:
                    self._ai_out_txt.delete("1.0", "end-200000c")
                self._ai_out_txt.see("end")
        except queue.Empty:
            pass
        win.after(80, self._ai_drain)

    def _ai_backend_changed(self, event=None):
        if self._ai_busy:
            self._ai_backend.set(self._ai_choice)
            self._ai_out('Wait for the current AI request before switching engines.\n')
            return
        self._ai_choice = self._ai_backend.get()
        self._ai_ready = False
        self._ai_verified = None
        self._ai_history = []
        self._ai_model.delete(0, 'end')
        if self._ai_backend.get().startswith('Cloud: '):
            import marauder_cloud
            provider = self._ai_backend.get()[7:]
            self._ai_model.insert(0, marauder_cloud.PROVIDERS[provider][1])
        elif self._ai_backend.get() == 'Intel NPU (OpenVINO)':
            self._ai_model.insert(0, os.path.join(str(APP_DIR),
                                               'models', 'phi35-npu'))
        else:
            self._ai_model.insert(0, 'llama3.1:8b' if self._ai_backend.get().startswith('Hybrid') else marauder_ai.DEFAULT_MODEL)
        self._ai_set_status('Verify the selected engine', PALETTE['muted'])

    def _ai_cloud_settings(self):
        if self._ai_busy:
            self._ai_out('Wait for the current AI request before changing cloud settings.\n')
            return
        import marauder_cloud
        import marauder_secrets
        provider = self._ai_backend.get()[7:] if self._ai_backend.get().startswith('Cloud: ') else 'OpenRouter Free'
        saved = self._cloud_config.get(provider, {})
        key = saved.get('key', '')
        if not key:
            try:
                key = marauder_secrets.load(APP_DIR, provider)
            except Exception:
                key = ''
        dialog = tk.Toplevel(self)
        dialog.title('Cloud AI — ' + provider)
        dialog.configure(bg=PALETTE['panel2'])
        dialog.transient(self)
        body = ttk.Frame(dialog, padding=20, style='Card.TFrame')
        body.pack(fill='both', expand=True)
        ttk.Label(body, text=provider, style='Title.TLabel').pack(anchor='w')
        notice = ('Questions and replies are sent to this provider. Free quotas and availability vary. '
                  'OpenRouter Free uses only free models, with no paid fallback. Gemini may charge '
                  'on billed accounts and free-tier prompts may be used for product improvement. '
                  'Review your provider account and avoid sensitive text in questions.')
        ttk.Label(body, text=notice, wraplength=620, style='CardMuted.TLabel', justify='left').pack(anchor='w', pady=10)
        ttk.Label(body, text='Your API key', style='Card.TLabel').pack(anchor='w')
        key_var = tk.StringVar(value=key)
        ttk.Entry(body, textvariable=key_var, show='•', width=65).pack(fill='x', pady=6)
        consent = tk.BooleanVar(value=saved.get('consent', False))
        share = tk.BooleanVar(value=saved.get('share', False))
        remember = tk.BooleanVar(value=False)
        ttk.Checkbutton(body, text='Allow sending my questions and conversation to this cloud provider', variable=consent).pack(anchor='w')
        ttk.Checkbutton(body, text='Include observation counts, channels and RSSI summaries (no identifiers or raw logs)', variable=share).pack(anchor='w', pady=6)
        ttk.Checkbutton(body, text='Remember key encrypted for this Windows user', variable=remember).pack(anchor='w')
        row = ttk.Frame(body, style='Card.TFrame')
        row.pack(fill='x', pady=(14,0))
        def apply():
            if self._ai_busy:
                messagebox.showinfo('AI busy', 'Wait for the current request first.', parent=dialog)
                return
            entered = key_var.get().strip()
            try:
                marauder_cloud.validate(provider, marauder_cloud.PROVIDERS[provider][1], entered)
                if remember.get():
                    marauder_secrets.save(APP_DIR, provider, entered)
                self._cloud_config[provider] = {'key': entered, 'consent': consent.get(), 'share': share.get()}
                self._ai_backend.set('Cloud: ' + provider)
                self._ai_backend_changed()
                dialog.destroy()
            except Exception as error:
                messagebox.showerror('Cloud settings', str(error), parent=dialog)
        def forget():
            if self._ai_busy:
                messagebox.showinfo('AI busy', 'Wait for the current request first.', parent=dialog)
                return
            try:
                marauder_secrets.forget(APP_DIR, provider)
                self._cloud_config.pop(provider, None)
                key_var.set('')
                self._ai_ready = False
                self._ai_verified = None
            except Exception:
                messagebox.showerror('API key', 'Could not remove the stored key.', parent=dialog)
        ttk.Button(row, text='Apply', style='Accent.TButton', command=apply).pack(side='right')
        ttk.Button(row, text='Forget key', command=forget).pack(side='left')
        url = 'https://openrouter.ai/keys' if provider == 'OpenRouter Free' else 'https://aistudio.google.com/apikey'
        ttk.Button(row, text='Get an API key', command=lambda: webbrowser.open(url)).pack(side='left', padx=8)

    def _ai_browse_npu(self):
        if self._ai_busy:
            return
        folder = filedialog.askdirectory(title='Select an OpenVINO NPU model folder')
        if folder:
            self._ai_npu_folder = folder
            if self._ai_backend.get().startswith('Hybrid'):
                self._ai_ready = False
                self._ai_verified = None
                return
            self._ai_backend.set('Intel NPU (OpenVINO)')
            self._ai_model.delete(0, 'end')
            self._ai_model.insert(0, folder)
            self._ai_ready = False
            self._ai_verified = None

    def _ai_enable(self):
        if self._ai_busy:
            return
        model = self._ai_model.get().strip()
        backend = self._ai_backend.get()
        npu_folder = self._ai_npu_folder
        cloud = dict(self._cloud_config.get(backend[7:], {})) if backend.startswith('Cloud: ') else None
        self._ai_ready = False
        self._ai_verified = None
        self._ai_busy = True
        self._ai_set_status('Loading model...', PALETTE['muted'])
        def work():
            if backend.startswith('Cloud: '):
                try:
                    import marauder_cloud
                    marauder_cloud.chat([{'role': 'user', 'content': 'Reply Ready.'}], backend[7:], model,
                                        cloud.get('key', ''), consent=cloud.get('consent', False))
                    self._ai_q.put(lambda: self._ai_mark_ready(backend, model))
                    self._ai_set_status('Cloud ready · no local GPU needed', PALETTE['ok'])
                    self._ai_out('Cloud verified. Only aggregate observations are shared if enabled. Questions are sent as typed.\n')
                except Exception as error:
                    self._ai_out(f'[Cloud error] {error}\n')
                    self._ai_set_status('Cloud unavailable', PALETTE['warn'])
                finally:
                    self._ai_busy = False
                return
            if backend.startswith('Hybrid'):
                try:
                    import marauder_hybrid
                    import json
                    import urllib.request
                    marauder_hybrid.marauder_npu.load(npu_folder)
                    marauder_ai.chat([{'role': 'user', 'content': 'Reply OK.'}], model=model, num_ctx=4096)
                    with marauder_ai._local_request(urllib.request.Request(marauder_ai.OLLAMA_HOST + '/api/ps'), timeout=10) as response:
                        loaded = json.load(response).get('models', [])
                    if not any(item.get('name') == model and item.get('size_vram', 0) > 0 for item in loaded):
                        raise RuntimeError('Ollama did not report GPU memory use for this model.')
                    self._hybrid = marauder_hybrid.HybridEngine(npu_folder)
                    self._ai_q.put(lambda: self._ai_mark_ready(backend, model))
                    self._ai_set_status('NPU + Ollama GPU ready', PALETTE['ok'])
                    self._ai_out('Hybrid: NPU summarizes observations; Ollama GPU answers questions.\n')
                except Exception as error:
                    self._ai_out(f'[Hybrid error] {error}\n')
                    self._ai_set_status('Hybrid unavailable', PALETTE['warn'])
                finally:
                    self._ai_busy = False
                return
            if backend == 'Intel NPU (OpenVINO)':
                try:
                    import marauder_npu
                    device = marauder_npu.load(model)
                    self._ai_out(f'OpenVINO loaded on {device}. Model: {model}\n')
                    self._ai_q.put(lambda: self._ai_mark_ready(backend, model))
                    self._ai_set_status('Ready on Intel NPU', PALETTE['ok'])
                except Exception as error:
                    self._ai_out(f'[NPU error] {error}\nNo CPU fallback was used. '
                                 'Run SETUP_NPU.ps1 if the runtime or model is missing.\n')
                    self._ai_set_status('NPU unavailable', PALETTE['warn'])
                finally:
                    self._ai_busy = False
                return
            ok, models, err = marauder_ai.check_ollama()
            self._ai_busy = False
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
            self._ai_q.put(lambda: self._ai_mark_ready(backend, model))
            self._ai_out(f"Connected to Ollama — model '{model}' is available. Ready.\n")
            self._ai_set_status("● ready", PALETTE["ok"])
        threading.Thread(target=work, daemon=True).start()

    def _ai_set_status(self, text, color):
        self._ai_q.put(lambda: self._ai_status.configure(text=text, foreground=color))

    def _ai_mark_ready(self, backend, model):
        if (self._ai_backend.get(), self._ai_model.get().strip()) == (backend, model):
            self._ai_verified = (backend, model)
            self._ai_ready = True

    def _ai_generate(self, messages, model, backend, stream_cb=None):
        if backend.startswith('Cloud: '):
            import marauder_cloud
            config = self._cloud_config.get(backend[7:], {})
            return marauder_cloud.chat(messages, backend[7:], model, config.get('key', ''),
                                       consent=config.get('consent', False), stream_cb=stream_cb)
        if backend.startswith('Hybrid'):
            return self._hybrid.chat(messages, model, stream_cb)
        if backend == 'Intel NPU (OpenVINO)':
            import marauder_npu
            return marauder_npu.chat(messages, system=marauder_ai.SYSTEM_PROMPT,
                                     model=model, stream_cb=stream_cb)
        return marauder_ai.chat(messages, model=model, stream_cb=stream_cb)

    def _ai_context(self):
        if self._ai_backend.get().startswith('Cloud: '):
            import marauder_cloud
            config = self._cloud_config.get(self._ai_backend.get()[7:], {})
            return marauder_cloud.aggregate_context(self._lists) if config.get('share', False) else 'Observation sharing is disabled.'
        try:
            events = self.eventlog.get("1.0", "end")  # already redacted
        except Exception:
            events = ""
        return marauder_ai.sanitize_context(self._lists.get("ap", {}),
                                            self._lists.get("sta", {}),
                                            self._lists.get("host", {}), events)

    def _ai_newchat(self):
        if self._ai_busy:
            self._ai_out("Wait for the current response before clearing history.\n")
            return
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
        backend = self._ai_backend.get()
        model = self._ai_model.get().strip()
        if self._ai_verified != (backend, model):
            self._ai_out('Model selection changed. Enable / verify it again.\n')
            return
        self._ai_busy = True
        model = self._ai_model.get().strip() or marauder_ai.DEFAULT_MODEL
        context = self._ai_context()
        if backend.startswith('Hybrid'):
            self._hybrid.refresh(context)
            context = self._hybrid.context(context)
        content = f"{user_text}\n\n[Current observations]\n{context}"
        self._ai_history = self._ai_history[-6:]
        self._ai_history.append({"role": "user", "content": content})
        messages = [dict(turn) for turn in self._ai_history]

        def work():
            acc = []
            try:
                self._ai_generate(messages, model=model, backend=backend,
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
        self._ai_q.put(lambda: self._ai_dispatch_main(cmd))

    def _ai_dispatch_main(self, cmd):
        """Main-thread dispatch; only exact receive-only commands may be queued."""
        if not marauder_ai.is_passive(cmd):
            self._ai_out(f"[unverified suggestion] {cmd} → not loaded or executed.\n")
            return
        if getattr(self, 'running', False) and (command_runs(cmd) or cmd in {'stopscan', 'recon stop'}):
            self._ai_out(f"[manual review] {cmd} would change the running operation; not queued.\n")
            return
        if self._ai_autorun.get() and self.dev:
            self._do_send(cmd)
            self._ai_out(f"[auto-run passive] {cmd}\n")
        else:
            self.raw_var.set(cmd)
            self._ai_out(f"[suggested passive] {cmd} → review in Raw and Send.\n")

    def _ai_report(self):
        if not self._ai_ready or self._ai_busy:
            self._ai_out("Enable a model and wait for the current response first.\n")
            return
        model, backend = self._ai_model.get().strip(), self._ai_backend.get()
        if self._ai_verified != (backend, model):
            self._ai_out("Verify the selected model first.\n")
            return
        path = filedialog.asksaveasfilename(defaultextension='.md', filetypes=[('Markdown report', '*.md')])
        if not path:
            return
        observations = self._ai_context()
        self._ai_busy = True
        def work():
            try:
                response = self._ai_generate([{'role': 'user', 'content':
                    'Write a concise diagnostic report: observations, limitations, and recommended '
                    'manual checks. Do not emit RUN commands. Never conclude a network is secure '
                    'from discovery or handshake capture alone.\n\n' + observations}], model, backend)
                with open(path, 'w', encoding='utf-8') as output:
                    output.write('# Marauder V8 diagnostic report\n\n'
                        'Model-generated analysis; verify conclusions.\n\n' + response +
                        '\n\n## Observation snapshot\n\n```text\n' + observations.replace('```', '~~~') + '\n```\n')
                self._ai_out(f"[report saved] {path}\n")
            except Exception as error:
                self._ai_out(f"[report failed] {error}\n")
            finally:
                self._ai_busy = False
        threading.Thread(target=work, daemon=True).start()

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
        if self._ai_verified != (self._ai_backend.get(), self._ai_model.get().strip()):
            self._ai_out("Verify the selected model first.\n")
            return
        self._ai_busy = True
        model = self._ai_model.get().strip() or marauder_ai.DEFAULT_MODEL
        backend = self._ai_backend.get()
        prompt = ("Given these observations, recommend the single most useful NEXT Marauder "
                  "command (prefer passive reconnaissance). Reply with ONLY the command on one "
                  "line, nothing else.\n\n" + self._ai_context())

        def work():
            try:
                out = self._ai_generate([{'role': 'user', 'content': prompt}], model, backend)
                cmd = out.strip().splitlines()[0].strip().strip("`").strip() if out.strip() else ""
                if not cmd:
                    self._ai_out("\n[no suggestion]\n")
                    return
                self._ai_dispatch(cmd)
            except Exception as e:  # noqa: BLE001
                self._ai_out(f"\n[AI error] {e}\n")
            finally:
                self._ai_busy = False
        threading.Thread(target=work, daemon=True).start()

    def _ai_survey_toggle(self):
        if self._ai_survey_on:
            self._ai_survey_on = False
            self._ai_survey_btn.configure(text="▶ Passive survey")
            self._ai_out("[passive survey stopped]\n")
            if self.dev:
                self._do_send("stopscan", event_kind="STOP")
            return
        if not self.dev:
            self._ai_out("Connect to the Marauder first.\n")
            return
        if getattr(self, '_survey_on', False):
            self._ai_out("Stop Automated Survey before starting another survey.\n")
            return
        if self.running:
            self._ai_out("Stop the current operation before starting a survey.\n")
            return
        self._ai_survey_on = True
        self._ai_survey_btn.configure(text="■ Stop survey")
        self._ai_out("[continuous passive Wi-Fi survey started]\n")
        self._do_send("recon wifi")

    # ---- firmware flasher (V8 / ESP32-C5) --------------------------------
    def open_firmware_dialog(self):
        win = self._new_tool_window()
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
                if callable(s):
                    s()
                    continue
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
        self._fw_busy = True
        fwdir = os.path.join(str(APP_DIR), "firmware")

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
                dest = marauder_flash.safe_asset_path(fwdir, asset["name"])
                marauder_flash.download_asset(asset["url"], dest, expected_size=asset["size"])
                self._fw_out(f"Saved: {dest}\n")
                self._fw_q.put(lambda: self._fw_file.set(dest))
            except Exception as e:  # noqa: BLE001
                self._fw_out(f"[fetch error] {e}\n")
            finally:
                self._fw_busy = False
        threading.Thread(target=work, daemon=True).start()

    def _fw_chipinfo(self):
        if self._fw_busy or not self._fw_port:
            if not self._fw_port:
                self._fw_out("No port available — connect or select a port first.\n")
            return
        self._fw_free_port()
        self._fw_busy = True
        port = self._fw_port

        def work():
            try:
                marauder_flash.run_esptool(marauder_flash.chipinfo_args(port), self._fw_out)
            finally:
                self._fw_busy = False
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
            self._fw_q.put(lambda: self._fw_flash_btn.configure(state="normal"))
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


    def _parse_ble(self, raw, recon_only=False):
        """Capture BLE scan rows; no active probing or device connections."""
        match = re.match(r"^\[(\d+)\]\[RSSI:\s*(-?\d+)\]\s*(.+)$", raw, re.I)
        live = re.match(r"^(-?\d+)\s+Device:\s*(.+)$", raw, re.I)
        if recon_only and not live:
            return False
        if not match and not live:
            return False
        idx, rssi, name = (match.group(1), match.group(2), match.group(3)) if match else (None, live.group(1), live.group(2))
        name = name.strip()
        mac = _MAC_RE.search(name)
        addr = mac.group(1).lower() if mac else ""
        key = addr or name.casefold()
        if not key:
            return False
        now = _dt.datetime.now().isoformat(timespec="seconds")
        entry = self._ble_history.get(key)
        if entry is None:
            entry = {"name": name, "mac": addr, "rssi": rssi, "first_seen": now, "last_seen": now, "count": 0}
            self._ble_history[key] = entry
        entry.update(name=name, rssi=rssi, last_seen=now, count=entry["count"] + 1)
        if idx is None:
            idx = next((i for i, row in self._lists["ble"].items() if row.get("key") == key), str(len(self._lists["ble"])))
        self._lists["ble"][idx] = {"key": key, "index": idx, "ssid": name, "bssid": addr, "rssi": rssi, "channel": "", "_observed_at": time.monotonic()}
        return True

    def _track_gps(self, line):
        if hasattr(self, '_wardrive_status'):
            if 'POI tagged:' in line:
                self._poi_reply = True
                self._wardrive_status.configure(text="Firmware acknowledged POI. Verify /wardrive_poi_*.gpx on the SD card; acknowledgement does not prove the write succeeded.")
            elif 'GPS Not Found' in line or 'GPS not supported' in line:
                self._wardrive_status.configure(text="Device reports GPS unavailable. Check GPS wiring, startup detection and firmware target.")
            elif re.match(r'^\s*\d+ \| ', line):
                self._wardrive_reply = True
                self._wardrive_status.configure(text="Wardrive observations received. Device stores wardrive logs and POIs on its SD card when available.")

        values = re.findall(r'\b(Fix|Sats|Lat(?:itude)?|Lon(?:gitude)?|Alt)\s*[:=]\s*([^\s,]+)', line, re.I)
        if not hasattr(self, '_gps_parts'):
            self._gps_parts = {}
        for name, value in values:
            key = {'latitude': 'Lat', 'longitude': 'Lon'}.get(name.lower(), name.title())
            if hasattr(self, '_dash_gps_values'):
                self._dash_gps_values[key] = value
            if key == 'Fix':
                self._gps_valid = value.lower() in {'yes', 'true', '1', '3d', '2d'}
                if not self._gps_valid:
                    self._gps_fix = None
                    self._gps_parts.clear()
            if key in {'Lat', 'Lon'}:
                try:
                    self._gps_parts[key] = (float(value), time.monotonic())
                except ValueError:
                    pass
        if 'Lat' in self._gps_parts and 'Lon' in self._gps_parts:
            lat, t_lat = self._gps_parts['Lat']
            lon, t_lon = self._gps_parts['Lon']
            if getattr(self, '_gps_valid', None) is not False and abs(t_lat-t_lon) <= 10:
                if -90 <= lat <= 90 and -180 <= lon <= 180 and (lat or lon):
                    self._gps_fix = (lat, lon)

    def open_ble_devices(self):
        win = self._new_tool_window()
        win.title("BLE inventory — manual scan may transmit")
        cols = ("name", "mac", "rssi", "first_seen", "last_seen", "count")
        tree = ttk.Treeview(win, columns=cols, show="headings")
        for col in cols:
            tree.heading(col, text=col.replace("_", " ").title())
            tree.column(col, width=155)
        tree.pack(fill="both", expand=True)
        def refresh():
            tree.delete(*tree.get_children())
            for e in self._ble_history.values():
                tree.insert("", "end", values=tuple(e[k] for k in cols))
        bar = ttk.Frame(win)
        bar.pack(fill="x")
        ttk.Button(bar, text="Refresh view", command=refresh).pack(side="left")
        ttk.Button(bar, text="List BLE (device)", command=lambda: self._do_send("list -b")).pack(side="left")
        refresh()

    def open_sd_browser(self):
        win = self._new_tool_window()
        win.title("SD listing — read-only")
        tree = ttk.Treeview(win, columns=("name", "size"), show="headings")
        tree.heading("name", text="File / directory")
        tree.heading("size", text="Size (bytes; 0 may indicate directory)")
        tree.column("name", width=450)
        tree.column("size", width=210)
        tree.pack(fill="both", expand=True)
        def refresh():
            tree.delete(*tree.get_children())
            for row in self._sd_rows:
                tree.insert("", "end", values=row)
        bar = ttk.Frame(win)
        bar.pack(fill="x")
        ttk.Button(bar, text="Refresh view", command=refresh).pack(side="left")
        ttk.Button(bar, text="Request ls", command=lambda: self._do_send("ls /")).pack(side="left")
        refresh()

    def export_inventory_report(self):
        import json
        from tkinter import filedialog
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")])
        if not path:
            return
        data = {"generated": _dt.datetime.now().isoformat(), "wifi": list(self._lists["ap"].values()),
                "ble": list(self._ble_history.values()), "sd_listing": self._sd_rows,
                "gps_last_fix": self._gps_fix, "battery": "not exposed by observed firmware serial interface"}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        self.log_event("EXPORT", "inventory report")

    def _record_event(self, direction, payload):
        if self._record_fp:
            import json
            try:
                self._record_fp.write(json.dumps({"time": _dt.datetime.now().isoformat(),
                    "direction": direction, "data": payload}, ensure_ascii=False) + "\n")
                self._record_fp.flush()
            except (OSError, ValueError) as error:
                try:
                    self._record_fp.close()
                except OSError:
                    pass
                self._record_fp = None
                self._emit(f"[session recording stopped: {error}]\n", 'sys')

    def toggle_recording(self):
        from tkinter import filedialog
        if self._record_fp:
            self._record_fp.close()
            self._record_fp = None
            messagebox.showinfo("Recording", "Session recording stopped")
            return
        path = filedialog.asksaveasfilename(defaultextension=".jsonl", filetypes=[("Session JSONL", "*.jsonl")])
        if path:
            self._record_fp = open(path, "w", encoding="utf-8")
            messagebox.showinfo("Recording", "Recording serial traffic; credentials may appear in received data")

    def replay_session(self):
        from marauder_sessions import received_chunks
        if self.dev or getattr(self, '_connecting', False):
            messagebox.showwarning("Replay", "Disconnect hardware before replay.")
            return
        if self._replay_iter is not None:
            messagebox.showinfo("Replay", "A replay is already running.")
            return
        path = filedialog.askopenfilename(filetypes=[("Session JSONL", "*.jsonl")])
        if not path:
            return
        self._line_buf = ""
        self._parse_mode = None
        self._replay_iter = received_chunks(path)
        self._replay_count = 0
        self._replay_step()

    def _replay_step(self):
        if self._replay_iter is None:
            return
        if self.dev:
            self._replay_iter.close()
            self._replay_iter = None
            return
        try:
            for _ in range(16):
                self._ingest(next(self._replay_iter))
                self._replay_count += 1
        except StopIteration:
            self._replay_iter = None
            messagebox.showinfo("Replay", f"Replayed {self._replay_count} RX chunks; no commands transmitted.")
            return
        except (OSError, ValueError) as error:
            self._replay_iter.close()
            self._replay_iter = None
            messagebox.showerror("Replay", str(error))
            return
        self.after(20, self._replay_step)

    # ---- shutdown --------------------------------------------------------
    def _on_close(self):
        self._cancel_surveys()
        if self._replay_iter is not None:
            self._replay_iter.close()
            self._replay_iter = None
        try:
            if self.dev:
                self._disconnect()
            if self.csv_file:
                self.csv_file.close()
            if self._events_file:
                self._events_file.close()
            if self._record_fp:
                self._record_fp.close()
        finally:
            self.destroy()


if __name__ == "__main__":
    from marauder_workspace import WorkspaceGUI
    WorkspaceGUI().mainloop()
