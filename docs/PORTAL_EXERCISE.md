# Guided employee portal exercise

## Workflow

Open **Portal exercise**, find your existing SD templates, choose a page, enter
or select the WiFi name, and click **Review & Start**. Configuration validates
the quoted SD path and SSID and waits for firmware acknowledgment before Start.
No page is generated or replaced by this workflow.

The GUI displays device-confirmed readiness, portal address, SD log path and saved
submission count. **Stop exercise** ends the AP and drains/closes its submission log.

The default name is `Specter Lab`. Editable reference SSIDs were checked against
publisher documentation on 2026-11-02:

| SSID | Primary source |
| --- | --- |
| `xfinitywifi` | [Xfinity](https://www.xfinity.com/support/articles/android-device-xfinity-wifi) |
| `Amtrak_WiFi` | [Amtrak](https://www.amtrak.com/journey-with-wi-fi-train-station) |
| `#SFO FREE WIFI` | [San Francisco International Airport](https://www.flysfo.com/faqs) |
| `DEN Airport Free WiFi` | [Denver International Airport](https://www.flydenver.com/at-the-airport/services-and-amenities/wifi-and-technology/) |

These are documented names, not live discovery or a guarantee about every location.
Selecting a reference does not start WiFi. The actual employee test used `Specter Lab`.

## Firmware protocol

`evilportal -c configure -s "<SSID>" -w "<relative SD path>"` checks the setup
and returns `@PORTAL:CONFIGURED` or an explicit `@PORTAL:ERROR`. The GUI sends
Start only after acknowledgment. `evilportal -c status` returns metadata including
state, SSID, template, IP address, evidence path and saved count. Existing firmware
team-mode gates apply to Start; no new host entitlement lockout was introduced.

## SD submissions

The portal requires an available SD evidence log before it starts. Logging is
independent of SavePCAP and uses a unique JSONL file in `/portal_loot/`, or the
active Specter Session's `captures/` directory with an output-index entry.
Each record includes UTC, received uptime, submitted username/password fields,
field-presence flags and a truncation flag. Each field is bounded to 512 UTF-8
bytes, preserving a valid truncation boundary. Oversized input is explicitly marked.

The existing `/get` endpoint accepts GET/query and POST/form fields using common
email/username/user/login and password/pass names. It queues each request as its
own record; fields from different clients/requests are not combined. The four-record
queue returns HTTP 503 when it cannot accept a submission. Empty/partial requests
are represented with field-presence flags, not inferred as a completed login.

Records are written and flushed from the main loop. Serial and the handheld show
counts/errors rather than the submitted password. JSONL contains the submitted
values on SD. Template-specific endpoints or JSON request bodies beyond this form
contract have not been added; the existing selected template uses `/get`.

## Validation — 2026-11-02

- 66 GUI tests run: 65 passed, one Windows-only test skipped.
- Host submission-record checks passed with ASan/UBSan, including request separation,
  bounded fields and UTF-8 truncation.
- V8/C5 compile: 2,206,644 bytes program storage (66%); 101,572 globals (30%).
- Firmware uploaded with hash verification. The live GUI received device-confirmed
  readiness on `Specter Lab`, address `172.0.0.1`, with the pre-existing Coffee Shops
  HTML template selected from SD.
- The user completed a manual login and confirmed it was theirs. The device reported
  one successful SD submission write/flush and the GUI displayed that count.
- No real submission values were printed by the host validation process or committed.
  Independent SD readback of that live record remains a follow-up after stopping
  the exercise. Do not infer testing of all 549 templates from this one exercise.
