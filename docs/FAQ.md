# FAQ

Common questions about Marauder V8 Control. See the full **[User Guide](USER_GUIDE.md)**
for usage and the complete command reference.

### What is this?
A desktop control panel (Python/Tkinter) for the **ESP32 Marauder V8 (ESP32‑C5)** over
USB serial. It groups the firmware's commands by radio, builds command strings with
inline help, and adds dashboards, passive surveys, capture/export tools, and an optional
AI assistant. It is for **authorized security testing only**.

### What hardware do I need?
An ESP32 Marauder **V8** (ESP32‑C5) flashed with the Marauder firmware, connected over
USB. The app talks to the device's serial CLI at 115200 baud; it does not do radio work
itself — the firmware does.

### Do I need Python?
- **Windows:** no — download the release ZIP, extract, run `MarauderV8-Control.exe`.
- **Linux / macOS:** yes — it runs from source (`pip install -r requirements.txt` then
  `python marauder_workspace.py`, or `./run.sh`). There is no prebuilt Linux binary.

### Is there a Linux executable?
No. PyInstaller can't cross‑build a Linux binary from Windows, so Linux/macOS run from
source. The app is pure Python + Tkinter, so it runs the same everywhere.

### It won't connect / I don't see my COM port
Make sure the board is plugged in and no other program holds the port. Use
**Connection → Port, baud, auto‑connect**. The V8 uses a CH340/C5 USB‑serial bridge; the
app auto‑detects it. On Linux, add yourself to the serial group:
`sudo usermod -a -G dialout $USER` (then re‑login).

### Why does the COM number change / the device reboot when I connect?
Opening the serial port toggles DTR/RTS, which resets the ESP32 (and on some boards
re‑enumerates it to a new COM number). This is normal — **Auto‑connect** follows the new
port. Expect a brief boot delay before the `>` prompt.

### Where do my logs, captures and exports go?
Into the `logs/` folder next to the app (CSV scans, event log, session recordings, Nmap
target lists, survey JSON/CSV/KML, reports). PCAP captures are written by the device to
its **SD card** — pull the card to open them in Wireshark.

### Why is BLE scanning manual?
The official firmware's BLE recon uses **active** scanning. BLE discovery is therefore a
deliberate operator action; the app logs and inventories received BLE observations but is
not an autonomous receive‑only BLE scanner.

### Is firmware flashing safe?
The updater auto‑detects the chip (so the architecture can't be set wrong), compares the
installed vs target version, and flashes the official `_v8` build. It's an **app‑level
update** and expects an existing compatible V8 bootloader/partition layout — use the
official installer for a full install or partition migration. Don't unplug while flashing.

### Does the AI run attacks on its own?
No. The assistant analyzes observations and recommends steps. It can run **passive**
(receive‑only) commands when you enable that, but any **transmitting** command (deauth,
spam, Evil Portal, etc.) is queued for your one‑click approval. It never selects targets
or fires RF on its own, and report generation never executes commands.

### Local vs cloud AI, and privacy?
Local **Ollama** runs on loopback (nothing leaves your machine). Optional **cloud**
(OpenRouter Free / Gemini) is for GPU‑less PCs and requires explicit consent and your own
API key; prompts you send go to that provider. Aggregate sharing is off by default and,
when enabled, sends only counts/channels/RSSI ranges — never names, addresses, GPS or
serial logs.

### Is there battery telemetry?
Not in the app — the installed firmware doesn't expose a battery/voltage reading over the
serial CLI, so there's no gauge (we won't show a fake one). Battery shows on the device's
own screen.

### What's the NPU / Hybrid option?
Experimental Intel **NPU** (OpenVINO) acceleration for the local AI, plus an NPU/GPU
hybrid mode. It's unverified for this beta (a prior device‑lost driver error); Ollama and
cloud are the reliable AI routes.

### How do I use it without the GUI?
A serial CLI ships alongside it:
`python marauder.py ports | fwhelp | send "list -a" | monitor`, and
`python marauder_pcap.py summary capture.pcap`. See the User Guide.

### How do I report a bug or request a feature?
Open a [GitHub issue](https://github.com/Anon0ne/marauder-v8-gui/issues) — there are Bug
report and Feature request templates. Pasting your device's `fwhelp` output helps, since
command syntax varies by firmware build.

### Is this legal?
The tool itself is a serial front‑end. Running active/transmitting operations against
networks or devices you don't own or aren't authorized to test may be illegal. Use it only
within an authorized engagement, and follow your local laws and rules of engagement.
