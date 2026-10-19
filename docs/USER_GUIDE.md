# Marauder V8 Control — User Guide

A desktop control panel for the **ESP32 Marauder (V8 / ESP32‑C5)** over USB serial.
It groups every firmware command by radio (WiFi / Bluetooth / Device), builds the
exact command string for you with inline help, and adds live dashboards, passive
surveys, capture/export tools, and an optional local/cloud AI assistant.

> For authorized security testing only — use it against devices and networks you
> own or have explicit written permission to test.

---

## Quick start

**Windows (no Python):** download the release ZIP, extract, run `MarauderV8-Control.exe`.

**From source (Windows / Linux / macOS):**
```bash
pip install -r requirements.txt
python marauder_workspace.py      # Workspace GUI (0.4.x)
```
Linux serial access usually needs: `sudo usermod -a -G dialout $USER` (re-login), and
Tkinter may be a separate package (`sudo apt install python3-tk`). `./run.sh` and
`INSTALL_AND_RUN.sh` automate the source setup.

Plug in the V8; with **Auto‑connect** on, the app grabs the CH340/C5 serial port
automatically (115200 baud). Opening the port resets the ESP32, so expect a short
boot delay and, on some boards, a changed COM number (auto‑connect follows it).

---

## The Workspace

- **Command catalog** — the left navigation mirrors the on‑device menu. Pick a
  command; fill its parameters; the exact command string builds live with per‑command
  help beneath it. **Send** runs it; long‑running commands show an in‑place **Stop**.
- **Target pickers** — index fields (Join AP, Select, Clone MAC, …) show a live list
  of scanned APs / stations / SSIDs / ARP hosts; **double‑click a row to fill it**.
- **Serial console + Event log** — live device output, a Raw send box, and a
  timestamped start/stop/connect event log (mirrored to `logs/`).
- **Live RF Dashboard** — AP/station/host/channel tiles, a per‑channel bar chart, a
  signal‑sorted AP table, 2.4/5 GHz split, and a GPS readout.
- **BLE Devices** — Bluetooth inventory with first/last‑seen history (BLE discovery is
  a manual operator action because the firmware scans actively).
- **Automated Survey** — passive WiFi recon that starts once and collects until Stop,
  deduping devices over time, with privacy controls (mask MACs / omit SSIDs) and
  **JSON / CSV / KML** export. GPS‑tagged placemarks when a fix is present.
- **SD files** — a file manager for the device's SD card: browse folders (double‑click
  to open), **Download** files to the PC, **Upload** files from the PC, **New folder**,
  **Rename / move**, **Copy**, **Delete** (with confirmation) and **Disk usage**.
  Transfers are CRC‑checked; a failed upload never replaces the old file. Needs firmware
  with the `sd` serial command; on older firmware the buttons report an error. The same
  operations work from the command line:
  `python marauder.py sd ls /`, `sd get /pcaps/x.pcap`, `sd put notes.txt /notes.txt`,
  `sd cp`, `sd mv`, `sd rm [-r]`, `sd mkdir`, `sd df`, `sd tree`.
- **Firmware updater** — fetch/flash the official `_v8` build; the chip is
  auto‑detected and the installed‑vs‑target version is compared before flashing.
- **Session record / replay** — record the console to a file and replay it (receive‑only).
- **AI Assistant** — optional; see below.

---

## Serial console & CLI

Everything the GUI does rides on a simple serial CLI (115200 baud, newline‑terminated).
Type commands directly into the **Raw** box, or use the standalone CLI:

```bash
python marauder.py ports            # list serial ports
python marauder.py fwhelp           # dump the firmware's own command list (ground truth)
python marauder.py monitor          # interactive console
python marauder.py send "list -a"   # one command
python marauder_pcap.py summary capture.pcap   # inspect a capture pulled from the SD card
```

Tip: your firmware's `help` output is the definitive command list for your exact
build. If a command here is rejected, run **Device → Firmware Help** and compare.

---

## Exports & analysis

- **CSV scan log** — toggle "Log scans → CSV"; AP/station rows land in `logs/scan_*.csv`.
- **Nmap targets** — after Join + ARP/Ping scan, export discovered host IPs as an
  `-iL` target list (paste‑safe forward‑slash command, or inline targets).
- **PCAP inspector** — summarize a `.pcap` and open it in Wireshark if installed.
- **Survey inventory** — JSON / CSV / KML (KML carries coordinates when GPS has a fix).
- **Report** — a Markdown assessment report from the current observations.

---

## AI Assistant (optional)

Local **Ollama** on loopback, or (for GPU‑less PCs) **Cloud: OpenRouter Free / Gemini**
with explicit consent and Windows‑encrypted key storage. The assistant analyzes
observations and recommends next steps; it can run **passive** commands when you allow
it, but any **transmitting** command is queued for your one‑click approval — it never
selects targets or fires attacks on its own. Report generation never executes commands.

---

## Safety

Active commands (deauth, beacon/BLE spam, Evil Portal, Karma, CSA/SAE, firmware flashing)
transmit and can disrupt. Run them only against devices and networks you own or are
explicitly authorized to test. You are responsible for compliance with local law.

---

## Command reference

Generated from the command catalog (`marauder_commands.py`). Parameters are shown in
brackets; a leading `-x` is the flag the GUI adds for you.

### WiFi

**Recon & Scan**

- `recon wifi` - Starts WiFi reconnaissance — discovers APs and stations and fills the target lists. View them under 'Lists & Targets'. Stop with 'Recon Stop' or Stop Scan.
- `recon status` - Prints the current recon state.
- `scanall` - Hops all channels logging every AP/station seen. Good for a full sweep before selecting targets.
- `packetcount` - Live packets-per-second meter on the current channel.
- `mactrack` - Tracks selected MAC(s) by presence and signal strength over time.
- `sigmon` - Compatibility unverified in current official firmware. Check device help before sending. Live signal monitor — graphs RSSI / packet activity on the current channel. Runs until stopped.
- `wardrive` - Logs APs with GPS coordinates to the SD card (Wigle-compatible). Requires a GPS fix.
- `wardrivepoi [Label]` - Tags a GPS point-of-interest during a wardrive.

**Sniffers**

- `sniffbeacon` - Captures 802.11 beacon frames from nearby APs.
- `sniffprobe` - Captures probe-request frames — the networks nearby devices seek.
- `sniffdeauth` - Listens for deauth/disassoc frames in the air (detect attacks).
- `sniffpmkid [-c Channel] [-d Force (deauth)] [-l Loop]` - Captures WPA PMKID / EAPOL handshake material to the SD card for offline analysis. Optionally force with deauth or loop channels.
- `sniffsae` - Captures WPA3 SAE commit frames.
- `sniffesp` - Compatibility unverified in current official firmware. Check device help before sending. Detects other ESP-based devices broadcasting nearby.
- `sniffpwn` - Detects nearby Pwnagotchi devices by their beacon signature.
- `sniffpinescan` - Detects WiFi Pineapple rogue-AP devices nearby.
- `sniffmultissid` - Detects APs broadcasting many SSIDs (Karma / MultiSSID behaviour).
- `sniffraw` - Dumps raw 802.11 frames. High volume.

**Attacks**

- `attack -t beacon -l` - Broadcasts beacons for every SSID in your SSID list. Authorized testing only — targets you own or have written permission to test.
- `attack -t beacon -r` - Broadcasts beacons with random SSIDs. Authorized testing only — targets you own or have written permission to test.
- `attack -t beacon -a` - Broadcasts beacons cloning your scanned AP list. Authorized testing only — targets you own or have written permission to test.
- `attack -t rickroll` - Broadcasts a set of joke SSIDs. Harmless demo.
- `attack -t probe` - Floods probe requests for SSIDs in your list. Authorized testing only — targets you own or have written permission to test.
- `attack -t deauth [-c Channel] [-s Source MAC] [-d Dest MAC]` - Sends deauth frames to selected AP(s)/station(s). Select targets first. Disrupts connectivity. Authorized testing only — targets you own or have written permission to test.
- `attack -t badmsg [-c Channel]` - Sends malformed management frames to selected target(s). Authorized testing only — targets you own or have written permission to test.
- `attack -t sae` - Floods WPA3 SAE commit frames at selected target(s). Authorized testing only — targets you own or have written permission to test.
- `attack -t csa` - Channel Switch Announcement attack against selected AP(s). Authorized testing only — targets you own or have written permission to test.
- `attack -t quiet` - Sends 802.11 Quiet elements to selected target(s). Authorized testing only — targets you own or have written permission to test.
- `attack -t sleep [-c Channel]` - Sends power-save/sleep frames to selected target(s). Authorized testing only — targets you own or have written permission to test.
- `evilportal -c start [-w HTML file]` - Starts a captive-portal AP serving an HTML page (credential harvesting demo). Strictly authorized testing / labs only. Authorized testing only — targets you own or have written permission to test.
- `evilportal -c sethtml [HTML file]` - Selects the HTML page the Evil Portal serves. Authorized testing only — targets you own or have written permission to test.
- `karma -p [Probe index]` - Responds to probe requests to lure clients (Karma). Pick the probe index from 'List'. Authorized testing only — targets you own or have written permission to test.

**IP / Network**

- `join [-a AP index] [-p Password]` - Joins a scanned AP so the IP-layer tools below can run.
- `join -s` - Shows current WiFi-join / IP status.
- `pingscan` - Pings the local subnet to find live hosts (after Join).
- `arpscan [-f Full]` - ARP-sweeps the local subnet for hosts (after Join).
- `portscan -a -t [Host index]` - Scans common ports on a host from the ARP/host list. Run ARP Scan first (or ↻ Refresh below), then double-click a host.
- `portscan -s [Service]` - Scans the subnet for a specific service.
- `protocolinfo` - Prints protocol/traffic info seen on the network.

**Lists & Targets**

- `list -a` - Prints scanned access points with indices.
- `list -s` - Prints scanned stations with indices.
- `list -c` - Prints your custom SSID list.
- `list [Flag]` - Prints another internal list. Flags from firmware: -t -i -p -b -f -x -m (type/identify/portal/BLE/findmy/etc. — see 'help').
- `info [-a AP index]` - Prints detailed info for an AP index (or current target).
- `select [List] [Index(es)]` - Selects targets by index from a list. Pick the list, then double-click rows below to add them (or type indices).
- `ssid -a [-n Name] [-g Random count]` - Adds an SSID to your custom list (name, or N random).
- `ssid -r [Index]` - Removes an SSID from your list by index.
- `add -a -b [MAC] [-ch Channel] [-e SSID]` - Manually adds an AP to the list by MAC.
- `add -c -b [MAC] [-ap AP index]` - Manually adds a station by MAC, tied to an AP index.
- `clearlist [Which]` - Empties a list.
- `save [Which]` - Saves a list to SD / flash.
- `load [Which]` - Loads a saved list.
- `upload [-d Destination]` - Uploads logged wardrive data.

**MAC Tools**

- `randapmac` - Compatibility unverified in current official firmware. Check device help before sending. Randomizes the AP (soft-AP) MAC.
- `randstamac` - Compatibility unverified in current official firmware. Check device help before sending. Randomizes the station MAC.
- `cloneapmac -a [AP index]` - Compatibility unverified in current official firmware. Check device help before sending. Sets the AP MAC to match a scanned AP's.
- `clonestamac -s [Station index]` - Compatibility unverified in current official firmware. Check device help before sending. Sets the station MAC to match a scanned station's.

**Channel**

- `channel` - Prints the current 802.11 channel.
- `channel -s [Channel]` - Sets the active 802.11 channel.

### Bluetooth

**Recon & Sniff**

- `recon ble` - Starts manual BLE reconnaissance. Official firmware uses active scanning and may transmit scan requests; excluded from autonomous passive analysis.
- `sniffbt [-t Type]` - Sniffs BLE advertising traffic. Optionally filter to a device type.
- `sniffbt -t airtag` - Scans specifically for Apple AirTag / Find My beacons.
- `sniffbt -t flipper` - Scans specifically for Flipper Zero BLE advertisements.
- `sniffskim` - Scans for BLE signatures of known card-skimmer modules (defensive).
- `btwardrive` - Compatibility unverified in current official firmware. Check device help before sending. Logs nearby Bluetooth/BLE devices with GPS coordinates to the SD card. Requires a GPS fix. Runs until stopped.

**Attacks**

- `blespam -t sourapple` - Spams Apple proximity-pairing adverts (crash/popup flood). Authorized testing only — targets you own or have written permission to test.
- `blespam -t applejuice` - Apple BLE advert spam variant. Authorized testing only — targets you own or have written permission to test.
- `blespam -t google` - Spams Google Fast Pair adverts. Authorized testing only — targets you own or have written permission to test.
- `blespam -t samsung` - Spams Samsung pairing adverts. Authorized testing only — targets you own or have written permission to test.
- `blespam -t windows` - Spams Microsoft Swift Pair adverts. Authorized testing only — targets you own or have written permission to test.
- `blespam -t flipper` - Spams Flipper-style BLE adverts. Authorized testing only — targets you own or have written permission to test.
- `blespam -t all` - Cycles all of the above advert types. Authorized testing only — targets you own or have written permission to test.
- `findmy -t [Index]` - Spoofs a Find My / AirTag advert from a scanned index. Authorized testing only — targets you own or have written permission to test.
- `spoofat -t [Index]` - Spoofs a specific AirTag from a scanned index. Authorized testing only — targets you own or have written permission to test.

### Device

**System**

- `help` - Prints the firmware's full command list — ground truth for syntax.
- `settings` - Prints current settings (if the build supports a bare 'settings').
- `settings -s [Setting] [State]` - Enables or disables a named setting (see Show Settings for names).
- `settings -r` - Resets settings to defaults.
- `reboot` - Reboots the Marauder.
- `update -s` - Flashes firmware from the SD card.
- `update -w` - Starts a WiFi/OTA firmware update.

**Storage (SD)**

- `ls [Path]` - Lists a directory on the SD card.
- `sd ls|tree|stat|df|cat|crc|mkdir|rm [-r]|mv|cp [-r]|get|put` - SD file manager (newer firmware; see SD files above).
- `backupspiffs` - Copies internal SPIFFS to /spiffs on SD.
- `backupstatus` - Inspects the /spiffs backup on SD.
- `restorespiffs` - Restores SPIFFS from /spiffs on SD.

**LEDs & Display**

- `led -s [Hex color]` - Sets the LED to a hex color.
- `led -p rainbow` - Runs the rainbow LED effect.
- `brightness -s [Level]` - Sets display brightness (0-9).
- `brightness -c cycle` - Cycles through brightness levels.

**GPS**

- `gpsdata` - Starts GPS display/stream mode and may stop the current scan. Use GPS Query for non-invasive status reads.
- `gps [-g Field]` - Read a GPS field with gps -g <field>, without changing the radio scan mode. No reply can indicate firmware incompatibility or GPS Not Found at startup.
- `gps -t` - Starts GPS tracking and changes the scan mode. Stop Scan ends tracking.
- `nmea` - Streams raw NMEA sentences from the GPS.
- `gpspoi [Action]` - Start / mark / end a GPS point-of-interest capture.
- `gpstracker -c [Action]` - Compatibility unverified in current official firmware. Check device help before sending. Starts or stops GPS track logging.

**Hunt**

- `foxhunt [Mode] [Index / args]` - Signal-strength 'hot/cold' hunt toward a target. Pick a mode and give the index/args: -w <ap>, -s <ap> <station>, -b <ble>, -t <findmy>, -f <flipper>, -p <pineapple>, -m <multissid>.

_Total: 96 commands (catalog built from this firmware's `help`; syntax varies by build)._
