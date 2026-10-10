# Security policy

## Supported versions

Security fixes are considered for the latest stable release and current development branch. Older versions may require upgrading. The 0.4.0b Beta is experimental and is not a substitute for a stable release. This is a volunteer-maintained project; response and patch deadlines are not guaranteed.

## Report a vulnerability privately

Email **justin@bizhostnc.com** with the subject `Marauder V8 GUI security report`. Do not put an unpatched vulnerability, exploit instructions, passwords, or private captures into a public issue.

Include the affected version/commit, OS, relevant module, reproducible steps, expected impact, and a minimal sanitized example. Use fabricated network identifiers and credentials. Coordinate disclosure with the maintainer so a fix can be evaluated before public details are released.

## Security boundaries

- Device serial output, AI recommendations, PCAP files, session recordings, and model data are untrusted input.
- Automatic model recommendations must match an explicit passive command allowlist. Unknown or transmitting commands require manual review.
- NPU inference is local and explicitly selects the NPU. Runtime/model downloads require network access; observation data is not part of those downloads.
- Firmware flashing is a privileged operation over the connected device and requires an operator decision. A GUI cannot guarantee that firmware or hardware is safe.
- Logs, recordings, exports, and model context can reveal network identifiers. Review them before sharing and store them appropriately.

A code review or successful test does not prove that a release has no vulnerabilities. Report unexpected behavior even if it is outside these examples.
