# Marauder V8 Control — 0.4.0b Beta

## Major GUI change — community beta testing

The GUI has changed substantially for 0.4.0 Beta. Please test navigation, serial connection, continuous surveys, capture/export tools and AI controls, and report usability feedback or regressions through GitHub issues. We are not yet sure whether we will keep this interface; community feedback will help decide its future.

![Newest Workspace GUI](docs/screenshots/workspace-beta.png)

The screenshot uses illustrative data with the device disconnected.


A desktop workspace for operating ESP32 Marauder V8 over USB serial, reviewing wireless observations, recording sessions, and using optional local AI analysis.

Project: https://github.com/Anon0ne/marauder-v8-gui

## Features

- Dark Workspace interface with persistent navigation, embedded tools, stable target selection and a side console.
- Live Wi-Fi and BLE inventories, RF dashboard, and continuous passive Wi-Fi survey. Start sends reconnaissance once; Stop ends it once. Inventory refresh does not restart capture.
- Read-only SD browsing, PCAP inspection, JSON/CSV inventory exports and GPS-based KML placemarks when a valid GPS fix exists.
- JSONL RX/TX session recording and receive-only offline replay.
- Firmware flashing with esptool and USB serial connection in a background worker.
- Local Ollama conversation, explicit Intel NPU inference, and optional Hybrid mode: NPU observation summaries run separately from Ollama GPU conversation.
- Bounded serial input, password redaction and a strict AI command allowlist. Unverified AI suggestions are never copied into Raw or executed.

## Windows

For the Windows portable ZIP, extract everything and launch MarauderV8-Control.exe. Python is not required for the executable. Optional AI models are separate downloads.

From source, automated setup/build: double-click BUILD_AND_INSTALL.cmd. Manual setup: install Python 3.10–3.13 with Tkinter, create a virtual environment, install requirements.txt, then run marauder_workspace.py.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe marauder_workspace.py
```

Optional NPU: double-click SETUP_NPU.cmd, then RUN_NPU.cmd. The wrapper permits its setup script for that process without changing system execution policy. See NPU_SETUP.md.

## Linux

The Linux ZIP contains source, not a Windows executable. Install Python, Tkinter and venv support through your distribution, then use `bash INSTALL_AND_RUN.sh`. For manual installation:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python marauder_workspace.py
```

Serial permissions may require membership in your distribution's serial-access group. Linux GUI and NPU hardware execution have not been validated on this Windows machine.

## AI and accelerator behavior

Intel NPU requires a supported Intel driver, OpenVINO dependencies, and the separate pinned Phi-3.5 Mini model download. There is no silent CPU fallback. Phi-3.5 is a small model: treat its conclusions as suggestions, verify against firmware help, and use Ollama for more demanding conversation.

Hybrid selects an Ollama model (default llama3.1:8b) and an NPU folder. Verify checks NPU loading and reported Ollama GPU memory use. NPU summaries refresh on questions, at most once per 30 seconds. An exact matching cached summary can reduce the observation context sent to the GPU; otherwise the original observations are used. Jobs can overlap; this does not split one model across both devices. Speed or power savings depend on workload.

AI output is untrusted. Only exact documented observation commands qualify for optional automatic execution. Unknown commands, transmitting commands and host utilities are shown as unverified text. Handshake capture alone does not prove network security.

Recordings and exports can contain private network observations. Review them before sharing. See SECURITY.md, CONTRIBUTING.md, CODE_OF_CONDUCT.md and SUPPORT.md.

Experimental NPU/Hybrid limitation: the latest NPU conversational retest returned a device-lost driver error. NPU answer quality and concurrent execution remain unverified for this beta; Ollama can be used independently.
