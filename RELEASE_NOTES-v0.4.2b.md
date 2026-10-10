# Marauder V8 Control 0.4.2b Beta

Reliability and diagnostics update to the experimental Workspace GUI. The GUI has changed substantially since the older interface; please test it and share feedback. We have not decided whether to retain this design.

- Non-interrupting GPS status queries, corrected toolbox syntax and missing-response diagnostics.
- Manual wardrive and labeled GPS POI controls, with SD GPX storage and acknowledgement distinguished from verified writes.
- Automated Wi-Fi survey starts once until stopped, with session recording and bounded replay. BLE acquisition remains manual because firmware uses active scanning.
- Serial timeouts, partial-write handling, decoding, disconnect cleanup and bounded inventory/log views.
- Stricter AI command validation and diagnostic reports that do not execute commands; local Ollama remains available.
- Optional OpenRouter Free and Gemini diagnostics for PCs without a GPU, explicit consent, optional aggregate sharing and Windows-encrypted key storage. Bring your own API key; quotas/account billing apply.
- Safer firmware downloads, PCAP validation, CSV escaping, pinned build dependencies, regression tests and audit documentation.

## Downloads

**Windows:** MarauderV8-v0.4.2b-Windows.zip includes a standalone x64 EXE plus source, manual setup and automated build/install scripts. Extract before running.

**Linux:** MarauderV8-v0.4.2b-Linux.zip contains Python source and manual/automated setup. It is not a native Linux executable; Linux execution has not been tested here.

Optional NPU runtime is bundled in the Windows EXE; models are separate downloads. NPU/Hybrid remains experimental after a prior device-lost error.

GPS was confirmed working by the user after correcting hardware; this is not claimed as a software fix. Wardrive/POI persistence, physical RF behavior and real authenticated cloud requests remain unverified. Security checks cannot establish absence of vulnerabilities.

[Project and support](https://github.com/Anon0ne/marauder-v8-gui)
