# Marauder V8 — Control GUI

A clean desktop GUI + CLI to drive an ESP32 Marauder (V8 fork) over USB serial.

> **Beta — testers and feature requests welcome.** This is an early (v0.1.0-beta)
> release. If you try it, I'd love your feedback: please
> [open an issue](https://github.com/Anon0ne/marauder-v8-gui/issues) for bugs,
> or use the **Feature request** template to suggest ideas. Pasting the output of
> your firmware's `help` command (or any command that renders oddly) is especially
> useful, since command syntax varies between Marauder builds.

## Download

- **Windows (no Python needed):** grab `MarauderV8-Control.exe` from the
  [latest release](https://github.com/Anon0ne/marauder-v8-gui/releases/latest).
- **From source:** see below.

## Install & run

```bash
pip install pyserial
python marauder_gui.py
```

Only `pyserial` is required; the GUI uses Python's built-in `tkinter`.

## Files

| File | Purpose |
|------|---------|
| `marauder_gui.py` | The GUI. Run this. |
| `marauder_commands.py` | The command catalog (grouped by radio). **Edit this to add/fix commands.** |
| `marauder.py` | Serial layer + a standalone CLI (`ports`, `fwhelp`, `send`, `monitor`, `scan`). |
| `marauder_pcap.py` | Zero-dependency `.pcap` inspector (also a CLI). |
| `logs/` | CSV scan logs are written here. |

## GUI quick tour

- **Top bar** — live port dropdown, baud, Connect, and **Auto-connect** (grabs the
  Marauder the moment it's plugged in; detects CP210x / CH340 / FTDI / native-USB).
- **Left tree** — every command, grouped like the on-device menu: WiFi, Bluetooth,
  Device. Attack commands are marked ⚠.
- **Builder** — pick a command, fill the parameters; the exact command string is shown
  and editable, with a **Send** button. The command's **Help** sits right underneath.
- **Target pickers** — index fields (Join AP, Select, Info, Clone AP/Station MAC,
  Remove SSID, Add Station) show a live list of scanned APs/stations/SSIDs below the
  field. **Double-click a row to fill it** (Select appends for multi-target). Hit
  **↻ Refresh** to pull the latest list from the device (`list -a/-s/-c`).
- **Stop** — a red Stop button appears on the builder page for any long-running
  command (scan/sniff/attack/spam/recon), and a persistent one sits in the toolbar.
  It sends `recon stop` after a recon, `stopscan` otherwise.
- **Console / Event Log** — two tabs. The console shows live serial output with a
  Raw send box and **Log scans → CSV** (parses AP/station rows into `logs/scan_*.csv`).
  The Event Log records every start/stop/connect with timestamps and mirrors them to
  `logs/events_*.log`.
- **Export** menu (console header):
  - **Nmap target list (-iL)** — host IPs discovered by ARP/ping/port scans are
    collected automatically; export them to `logs/nmap_targets_*.txt` and run
    `nmap -iL <file> -sV`.
  - **Console log (.txt)** — dump the raw serial session.
  - **Open capture in Wireshark** — same as the PCAP Inspector.
- **PCAP Inspector** — open a `.pcap` pulled from the SD card for a summary, and
  launch it in Wireshark if installed. (Wireshark reads the device's `.pcap`
  directly — scans are host lists, not packets, so they export to Nmap instead.)

## CLI (no GUI)

```bash
python marauder.py ports            # list serial ports
python marauder.py fwhelp           # dump the firmware's command list
python marauder.py monitor          # interactive console
python marauder.py send "list -a"   # one command
python marauder_pcap.py summary capture.pcap
```

## Captive portal

[`portals/default/index.html`](portals/) is the default captive-portal page for
the firmware's Evil Portal feature. It's an **awareness page, not a credential
trap** — it collects nothing, and instead shows anyone who connects why trusting
an unknown open network is risky. See [`portals/README.md`](portals/README.md).

## Firmware note

The catalog was built from *this* device's live `help` output. If you flash a
different build and syntax changes, run **Device → Firmware Help** and edit
`marauder_commands.py` to match.

## Authorized use only

Active commands (deauth, beacon/BLE spam, Evil Portal, Karma, CSA/SAE, etc.)
transmit and disrupt. Run them **only** against devices and networks you own or
have explicit written permission to test. You are responsible for compliance with
local law.
