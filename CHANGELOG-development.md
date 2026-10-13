# Development changes after 0.4.0b Beta

## Security and autonomous analysis

- Removed `recon ble` from automatic execution: official firmware enables active BLE scanning. Manual BLE controls and inventories remain available, with clearer wording.
- Routed the separate next-command suggestion through the shared exact-command validator. Unknown and transmitting suggestions never populate Raw.
- Prevented AI from starting/stopping an existing running RF operation and deduplicated repeated RUN lines.
- Restricted Ollama to loopback endpoints, disabled proxies/redirects, bounded response size, and verified exact model tags.
- Escaped formula-like SSIDs in CSV exports. JSON retains original observations.
- Downloaded firmware into a bounded temporary file and replaced the destination only after length validation. Reject unsafe filenames and non-GitHub HTTPS endpoints; match the exact V8 suffix.
- Validated PCAP version, fixed maximum snapshot/record sizes, record lengths and fractional timestamps.
- Raised the NPU `huggingface-hub` floor to 1.32.0 so pip cannot resolve a version affected by the six Aikido-reported advisories (the NPU build lock already pins 2.2.0).

## Serial, sessions and GUI reliability

- Set a finite serial write timeout, rejected control characters before trimming, checked complete writes, removed unbounded flush and serialized writes.
- Preserved UTF-8 sequences across serial reads. Reader errors now queue a main-thread disconnect; disconnect cancels surveys, clears stale receive state and invalidates the GPS fix.
- Continuous Wi-Fi survey starts reconnaissance once and records a JSONL session by default. Stop cancels callbacks and closes only a recording owned by that survey. Existing manual recording is preserved.
- Recording failures disable the recorder and report an error without breaking reception.
- Replay validates RX-only JSON objects, limits file/line/chunk sizes and schedules small GUI batches; hardware connection and replay cannot overlap.
- Parse Wi-Fi station relationships and exclude multicast addresses from station inventory. Survey Seen counts reflect received observations rather than UI refreshes.
- SD browser sends `ls /`, as required by official firmware.
- Firmware workers queue UI updates; chip-info/download/flash operations share the busy guard. Connection completion closes an abandoned serial handle during shutdown.
- Bound console/chat text, chat history and live inventory size. Complete recording files remain separate from capped live displays.

## AI, build and documentation

- Added Save diagnostic report using optional local Ollama/NPU engines. Report generation never dispatches RF commands and labels model analysis as unverified.
- Retained all 95 catalog entries; eight unmatched official command names show compatibility warnings.
- Added pinned Windows dependency sets, Python 3.12.10 build script, isolated development installation, and a Windows CI workflow pinned to action commits.
- Added regression tests, complete command-token matrix, source audit and validation report.

This is a development snapshot; it does not change the published beta release. Linux, physical RF/serial behavior and NPU driver reliability still require hardware/platform testing. Receive-only BLE acquisition needs firmware support; it is not claimed here.
