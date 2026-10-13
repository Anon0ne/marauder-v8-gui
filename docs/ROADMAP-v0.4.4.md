# Planned for v0.4.4

Approved during review. The new app icon is already added; the features below are
queued. (0.4.3 was a security patch; this is the next feature cut.)

## New app icon — DONE
Hooded skeleton (reaper) with a bone skull and WiFi arcs, on the app's dark+teal
theme. `marauder.ico` (16–256 px) is in the repo and wired into
`MarauderV8-Control.spec` (`icon='marauder.ico'`). Rebuild the EXE to apply.

## Features queued

### 1. Evil Portal chooser (on-device, over serial)
Browse the SD card (`ls`), list the `.html` portal files already on it, let the
operator pick one → `evilportal -c sethtml <file>` → Start / Stop. Optionally copy a
local `.html` onto the SD when the card is mounted as a PC drive.
- **Blocked on:** the firmware has **no serial command to write files to the SD**, so
  the app cannot *upload* portals over USB — operators place their own portals on the
  card. Need a live `ls` to confirm the exact SD portal folder/path.
- **Boundary (keep):** the app will not source, bundle, or craft credential-harvesting
  / brand-impersonation portal pages (e.g. third-party "evil portal" packs). Only the
  benign awareness portal ships by default; operators supply their own authorized
  portals. This matches the stance held throughout the project.

### 2. Full-flash recovery
Recover a bricked board by flashing bootloader + partitions + app (not just the app),
using the official installer assets, with chip auto-detect and strong confirmation.
Requires the device and the correct per-family offsets (C-series bootloader at 0x0).

### 3. Wardrive / GPX log viewer
Host-side viewer for the `.gpx` / wardrive `.log` files the device writes to its SD
card (open a file the operator pulled from the card via a reader; summarize points,
networks, and track). No serial file-read exists, so this reads local files.

### 4. Command favorites + history
Pin frequently used commands and recall recently sent ones for one-click re-run.
Pure host-side; lowest conflict risk — good first build.

## Notes
- Device-independent (buildable/verifiable without hardware): favorites+history, GPX
  viewer. Device-dependent (need the V8 connected): Evil Portal chooser, full-flash.
- Battery telemetry remains unavailable over serial on this firmware.
