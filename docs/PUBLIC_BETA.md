# Public beta review candidate

Status: **review-only; not approved for public distribution**. Repository visibility
has not been changed. No device was flashed for this review.

## Scope

Marauder V8 / ESP32-C5 only, V8 TFT/touch setup, PSRAM and the 8 MB partition
layout. The companion GUI excludes Heatmap, Premium navigation/upgrade screens
and private Pro plugin loading. Heatmap remains a separate premium membership
purchased directly from Anon0ne; the README describes that availability.
MITM experiments and the proposed portal credential-validation patch are absent.
No private license server, signing keys or Pro implementation belongs in this kit.

## Release gates

- [ ] Owner reviews the private release-readiness audit and approves distribution.
- [ ] Second-start client DHCP is verified on hardware, without rebooting the V8.
- [ ] Repeated start/stop cycles show no unexplained internal-heap loss.
- [ ] Exact candidate Windows executable passes frozen/install checks on Windows.
- [ ] Combined candidate firmware and GUI pass a physical Windows COM-port test.
- [ ] Dependency/source provenance and binary-distribution notices are reviewed.
- [ ] Owner decides the treatment of historic third-party token-like data before
      publishing a repository with its complete history.
- [ ] Documented SD submission logging behavior and handling of private test data
      are approved for the intended beta scope. No real submitted values should
      be attached to issues or included in public artifacts.

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
   Stop/restart failures remain blocking even if reboot temporarily helps.

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

The security contact is listed in SECURITY.md. This document records gates and
limits; it is not a declaration that all modules are hardware-validated.
