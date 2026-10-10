# Repository audit and implementation plan

Baseline GUI: d81750475017927d4e543b5402c82afa148778a8 (published 0.4.0b Beta). Firmware: d3ceb28afeda1196ca27c13adeaa69ada52383f3. Reviewed Python transport, command catalog, GUI/Workspace, firmware download/flash, PCAP, local AI/NPU/Hybrid, setup/build scripts, portal assets and community configuration. This is a source audit; physical RF behavior and NPU driver stability require hardware verification.

## Findings before changes

| Priority | Finding | Action |
|---|---|---|
| High | recon ble classified passive, but official BT_SCAN_ALL calls setActiveScan(true) | Remove from AI allowlist; retain clearly labeled manual BLE |
| High | _ai_suggest directly places unvalidated model output into Raw | Use shared validated dispatch; regression test |
| High | Serial write/flush lacks finite write timeout | Set write timeout, verify complete writes; remove unbounded flush |
| Medium | Disconnect leaves survey flags; reader failure leaves connected GUI | Cancel survey callbacks, stop acquisition, update state on main thread |
| Medium | Replay synchronous, unlimited; json arrays trigger AttributeError | Bounded schema-checked iterator and scheduled batches |
| Medium | Recording I/O failure interrupts parsing and is swallowed | Disable failed recording and keep receiving, report failure |
| Medium | ls lacks required directory | Request ls / |
| Medium | Firmware download writes partial final file, no size bounds, untrusted filename | Validate exact board suffix, bounded atomic download, safe path |
| Medium | Firmware/AI suggestion workers call Tk directly | Queue UI callbacks for main thread |
| Medium | PCAP sanity ceiling expands with attacker-controlled snaplen | Fixed ceiling, validate version/timestamps/record lengths |
| Medium | Build dependencies unpinned | Locked Windows build environment and CI build/test recipe |
| Medium | Model verification accepts a different tag of same model family | Require exact model name or explicit latest alias |
| Low | Survey Seen count increments per refresh instead of observation | Use observation identity/version when accumulating |
| Low | Human-readable inventories and AI history grow indefinitely | Bound display/history; preserve complete session files |

## Command comparison

95 catalog entries compared to official dispatch tokens. Eight unmatched entries are retained as legacy/unverified: sigmon, sniffesp, randapmac, randstamac, cloneapmac, clonestamac, btwardrive, gpstracker. Seven uncatalogued firmware tokens need version-aware integration; see COMMAND_COMPARISON.md and the machine-readable comparison. Token matches do not prove complete argument or hardware support. Installed device help remains authoritative.

## Implementation order

1. Correct autonomous RF policy and AI dispatch; finite serial writes and disconnect recovery.
2. Robust recording/replay and download/PCAP input handling.
3. Continuous passive Wi-Fi surveys with session logging. Preserve BLE observation parsing and manual active scan; do not invent receive-only BLE firmware support.
4. Optional local diagnostic reports, bounded history and observable errors. Preserve manual active commands and existing embedded pages.
5. Pin Windows build dependencies, run unit/GUI/build smoke tests, provide development EXE and source ZIP with changelog and validation limits. No new release is requested in this turn.

## Limits

No claim of vulnerability-free software. Current firmware master may differ from installed V8 binary. Linux and physical unplug/replug behavior need platform/device testing. NPU/Hybrid remains experimental after the prior device-lost error.

## Implementation status

The highest-priority fixes are implemented in this development snapshot. CSV formula injection was also found and fixed during export review. See CHANGELOG-development.md and VALIDATION.md for final behavior and test results.

Bandit identified no high-severity issues. The remaining medium alerts are two generic URL-open warnings (fixed official HTTPS metadata endpoint and explicit HTTPS/host validation for assets), plus a false-positive interface-binding warning on the literal 0.0.0.0 used to filter invalid observed IPs; the GUI does not bind a listener. Lower-severity subprocess and exception-handler alerts require ongoing review; subprocess calls use argument lists and shell=False. In-process esptool still redirects process stdout/stderr and lacks forced cancellation. It is serialized by the firmware busy guard; cancellation/isolation is follow-up work.

The 43 pinned application/build/NPU packages have no known reported vulnerabilities in the completed PyPI advisory scan. This does not prove that undisclosed vulnerabilities are absent. The comparison covers all catalog tokens; flags, compile-time macros and exact installed firmware behavior still require device validation. Autonomous passive BLE remains blocked by official firmware's active scan behavior.
