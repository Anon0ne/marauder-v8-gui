# Specter V8 public beta

Status: **public testing prerelease**, published at the maintainer's request.
This is not a stable release or a claim that all features have hardware coverage.

**Firmware hardware restriction:** Specter firmware is only for the Marauder V8
with its ESP32-C5, V8 TFT/touch wiring, PSRAM and 8 MB partition layout. Do not
flash it onto another Marauder revision, ESP development board, CYD, S3 or other
hardware, even if the chip family looks similar.

**GUI support policy:** Marauder V8 is the only officially supported device.
Some other Marauder or ESP hardware may partially work over serial, but this is
untested, unsupported and not a compatibility promise. Device commands, response
formats, capabilities and flash layouts may differ. Possible GUI connectivity
never makes the V8 firmware safe for another board.

## Scope

The public beta excludes Heatmap, Premium navigation/upgrade screens and private
Pro plugin loading. Heatmap is available only through premium membership
purchased directly from [Anon0ne](https://github.com/Anon0ne). Contact Anon0ne
for pricing and access. No licensing server or premium implementation is bundled.
MITM feasibility experiments and the proposed portal input-validation pack are
not included.

## Known limitations and validation coverage

- **Portal client DHCP can fail on a later start.** HTTP listener restart checks
  do not establish that a client receives an IP. No DHCP repair is claimed.
  Restart the device if needed and report the cycle/client/console symptoms.
- Repeated operation cycles still require memory and on-device acceptance tests.
- A serial-open reset occurred with the tested USB adapter; reconnecting may
  clear an in-progress operation.
- Source tests and frozen Windows install/page checks are offline checks, not
  a physical Windows USB/COM or radio test of every operation.
- Optional AI/NPU and cloud integrations remain experimental; cloud requests
  are not hardware-tested and provider availability is outside this project.
- Existing portal submission logging can write entered values to SD. Use a
  static connectivity page for initial acceptance. Never upload private
  submissions, captures, tokens or licensing files with issues.

The clean public firmware snapshot omits legacy PCB assets and private Git
history. Library notices are retained in `docs/third-party`; original source
copyrights are preserved. This is not a legal or security certification.

## Hardware acceptance using the harmless connectivity page

Use a clearly labeled static page without input fields. For every cycle:

1. Start the test SSID, connect a client and record whether it receives an IPv4
   address, the gateway and DNS settings. Do not equate HTTP LISTEN with DHCP.
2. Open `http://172.0.0.1/` and verify page delivery.
3. Stop the AP, configure the SSID again (Stop clears the existing selection),
   restart, renew the client connection and repeat at least five times.
4. Repeat after BLE use and an AP scan; record reset reason, free internal heap
   and largest contiguous block where diagnostics are available. Test a second
   client to distinguish cached client leases from server state.
5. Record host OS, USB driver, both source commits and exact reproduction steps.
   Stop/restart failures remain a known beta limitation even if reboot temporarily helps.

The previous HTTP stack-size fix has user-confirmed page delivery, but does not
establish that second-start client DHCP works. No DHCP repair is claimed here.

## Installation boundaries

Use a matched kit's `flash_v8.py` helper for the firmware/support-image layout.
The GUI's online download is upstream Marauder, not a Specter beta updater. The
review GUI labels this distinction and explicitly targets ESP32-C5. Use 115200
for normal serial operation. Disconnect the GUI before a deliberate firmware
flash. A serial-open reset has occurred with this board/adapter and is a known
limitation, not evidence that a running test completed successfully.

## Data and network behavior

AP names, MAC addresses, captures, serial recordings, submission logs and reports
can identify people or networks. Review/sanitize files before sharing them. The
existing firmware can save portal submissions to SD; this review does not add
new validation or suppress that existing behavior. Optional cloud AI sends
operator-provided context to its selected provider; prefer offline tools for
private data. No live secrets or captures are supplied as test fixtures.

The security contact is listed in SECURITY.md. This document records known limits and
test coverage; it is not a declaration that all modules are hardware-validated.
