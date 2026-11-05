# AP clone, template selection and Stop controls

## What Clone does

Clone creates an open portal AP using a discovered AP's WiFi name. It does not
copy the router's authentication configuration or create a webpage. Select an
existing SD portal first; that template is carried explicitly through Clone.

If no portal has been chosen, Clone opens Portal exercise with the AP name filled
in so a page can be selected before Review & Start. Only one clone target may be
selected because one portal AP runs at a time.

## Current AP identity

AP indices are volatile: rebooting and starting a new scan replace the device
list. The GUI now clears those cached lists on connection/reset and new discovery.
Before Clone it reads the firmware's authoritative `aplist` snapshot, resolves the
selection by BSSID, displays the current name/address, and sends the current index
with an expected BSSID and the quoted SD template path.

The firmware checks the expected BSSID again and validates the template before
starting. A stale/missing AP or missing/oversized template produces an error,
rather than silently using another AP or default page. Raw CLI syntax:

```text
aplist
apclone -a <current-index> [-b <expected-bssid>] [-w "<SD template path>"]
```

## Stop controls

- Stop active job is always visible in the Workspace header.
- Specter firmware has its own Stop active job control.
- Parameterized job forms such as IoT Recon and Probe to Portal now show Stop
  even before arguments are entered.
- Routing uses `stopble` for BT+, the relevant automation stop verb for automation,
  and `stopscan` for WiFi/portal jobs. If no current job is known, it stops BT+
  and WiFi. SD transactions remain serialized; Stop is a radio-job control.

## Validation — 2026-11-02

70 GUI tests run: 69 passed, Windows DPAPI skipped. Tests cover index remapping by
BSSID, missing/stale targets, incomplete snapshots, quoted template carryover,
cache reset, Stop visibility and parameterized-job routing. Clone dispatch tests
use mocked radio commands; no nearby AP is automatically cloned by the agent.
The V8 build compiled at 66% program storage and 30% global RAM and was flashed
with upload hash verification. Device guard/snapshot results are recorded below.

Hardware check: 20 AP records returned by the new snapshot endpoint; stale BSSID
and out-of-range indices rejected while portal status remained stopped. The
original employee test log was downloaded with CRC verification and contained
one record with both username/password presence flags. Values were not displayed.
