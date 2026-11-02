# Specter / Marauder V8 Pro integration

Development branch: `specter/pro-integration` in `marauder-v8-gui`.
Companion firmware: `specter/ble-touchscreen` in `Specter`.

## Run the test build

```sh
bash run-pro.sh --no-autoconnect
```

The launcher loads an existing sibling `MarauderGUIPro/marauder_pro` add-on.
Set `MARAUDER_PRO_DIR` when it is elsewhere, and `PYTHON` to select your Python.
The existing heatmap license checks are unchanged. New Specter controls are
available without new host entitlement checks while validation continues;
firmware Blue/Red Team and BT arming remain in force. Windows binaries have
not been rebuilt by this change.

## SD files

The GUI needs the firmware's `sd` serial file-manager protocol. The previous
Specter build lacked that handler, so listing parser changes alone could not
fix the empty/timing-out browser. The companion firmware restores the earlier
MIT SD manager, including CRC-checked base64 transfer and modified dates in
listings. SD transactions pause the background reader, block other GUI sends,
and refuse to start while a GUI-managed radio job is running.

Open **SD files → Refresh**. The browser supports navigation, upload/download,
new folders, rename/move, copy, delete and disk usage. Stop scans first.

## Rian's templates already on SD

1. Open **Portal templates**.
2. Leave SD folder at `/`, or enter Rian's directory.
3. Click **Find SD templates**; subdirectories are searched.
4. Filter by a word in the path and select a row.
5. **View source** downloads and CRC-checks the file into a temporary cache.
6. **Preview** opens a temporary offline browser preview with scripts, form
   submission and embedded network resources disabled. It does not run the portal.
7. **Use SD template** sends the nested path to `evilportal -c sethtml`;
   it does not start an AP or change team mode.

Local folders and explicit local-to-SD upload are also supported. Selecting a
local file does not upload it automatically. Preview has a 512 KiB bound; the
firmware's portal HTML-size limit is separate. External assets disabled in a
preview may also be unavailable on a captive network.

## Specter options

**Specter firmware** provides status/help, session and clock queries, UTC sync,
Stop BLE and a live reply pane. **Command catalog → Specter** contains 54 forms:

- Device Sessions, UTC clock and known file dates.
- Team mode, Guardian, Probe to Portal and IoT Recon.
- BT status/help/logs and explicit arm/confirm/disarm.
- Tracker, Predator, Whisper, KARR and Skimmer discovery/list/assessment handlers.
- Existing Phantom, Beacon, Spoofer, SkeletonKey and Predator honeypot handlers.

The GUI sends existing firmware commands; it does not implement new radio
payloads. BT+ Stop routes to `stopble`, not WiFi-only `stopscan`. Automation jobs
use their own stop commands. BT+ device indices differ from legacy BLE indices.
Newer-pack Airoha is not in the installed firmware and is not advertised here.

## Validation — 2026-11-02

- 65 GUI tests run: 64 passed; Windows DPAPI test skipped on Linux.
- Tests include Pro availability without a new license gate, worker-thread file
  operations, template selection/preview, serial ownership and stop routing.
- Firmware compiled at 65% program storage and 30% global RAM and flashed with
  upload hash verification.
- Live SD test: 78 root entries; 549 HTML templates found in Rian's directories.
- A real nested 18,013-byte template downloaded with CRC verification and its
  selection was acknowledged. The portal was not started.
- A uniquely named test folder verified list/tree/stat/df, dates, upload/download,
  CRC, copy/move/delete; the folder was removed.
- The actual Pro add-on loaded in the GUI and its threaded template browser
  independently displayed all 549 SD templates. Serial closed after testing.

Most active BLE assessment modules still need appropriate owned-target hardware
validation. Their presence in the catalog is not a claim of interoperability or
a confirmed vulnerability. Lockout/entitlement expansion remains deferred.

## Portal setup and path fix

The template page now keeps the chosen SD path visible, offers AP-list refresh,
scanned-AP configuration and a scan shortcut, and has Start/Stop controls. Start
checks that the chosen file exists and sends its complete quoted path. Selecting
a new template does not itself start the portal. Stop the current job before
changing setup or starting another portal.

The catalog's optional template override is now quoted, so directories containing
spaces remain one argument. Leave that override blank to use the firmware's
current selection. This avoids overwriting a correct selection with a stale,
truncated manual path.

The exact reported Coffee Shops template was stat'ed and downloaded with CRC
verification (3,135 bytes). No portal was started during that hardware check;
Start/Stop command dispatch is exercised with mocked radio commands.
