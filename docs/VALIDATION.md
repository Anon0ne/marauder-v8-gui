# 0.4.2b validation — 2026-10-10

- 35 regression tests passed, including embedded GUI pages, serial/session reliability, AI execution boundaries, GPS scan preservation, wardrive/POI dispatch, cloud consent/response checks and Windows DPAPI roundtrip.
- pip check passed in the isolated pinned build environment. Python 3.12.10 x64 and pinned PyInstaller/OpenVINO dependencies are used; optional model downloads remain separate. The clean-network reproducible-build script has not been run end-to-end here.
- Bandit: no high-severity findings, three medium findings reviewed (two firmware HTTPS URL-opening alerts, one address-filter false-positive binding alert). XML escape is used for writing, not parsing. Scan output is bandit.json. No scan proves absence of vulnerabilities.
- Cloud provider tests use mocks; no real authenticated API keys were supplied. Hosted-provider quotas, billing and privacy policies apply.
- User confirmed GPS works after correcting hardware. SD POI persistence and physical wardrive behavior remain unverified.
- Linux execution and physical flashing are untested. Official BLE scanning is active and excluded from autonomous passive acquisition.
- NPU/Hybrid remains experimental following a prior device-lost error; concurrent GPU/NPU operation is not validated by this release.
- Firmware token comparison covers 96 catalog entries, including eight legacy/unverified tokens; complete flag/board capability checks require device help.
- Build inputs are repeatable, not guaranteed byte-identical. Windows executable is unsigned.

- Current advisory check: zero known vulnerabilities across all 43 pinned packages (dependency-audit.json).
- Release standalone EXE opened as 0.4.2b and closed with exit code 0.
