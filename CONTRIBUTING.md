# Contributing to Marauder V8 Control GUI

Thanks for helping improve the project. The maintainer is [Anon0ne](https://github.com/Anon0ne).

## Before opening an issue

Read [SUPPORT.md](SUPPORT.md) and search existing issues. Report security problems privately using [SECURITY.md](SECURITY.md). Follow the [code of conduct](CODE_OF_CONDUCT.md).

Use the bug report form for errors and the feature request form for ideas. Include the application version, OS, firmware version, and whether you run from source or an EXE. Remove passwords, personal details, real network names, MAC addresses, and IP addresses from shared logs and captures.

## Development setup

Use Python 3.10–3.13 with Tkinter installed. Work in a feature branch; development for the next release belongs on the 0.4.0 development branch rather than directly on `main`.

```powershell
git switch -c fix/short-description
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe marauder_workspace.py
```

On Linux, use `python3`, `.venv/bin/python`, and install Tkinter using your distribution's package manager. NPU support is optional; see [NPU_SETUP.md](NPU_SETUP.md).

## Change guidelines

- Keep pull requests focused and describe the user-visible problem and resulting behavior.
- Preserve existing command syntax unless a documented firmware change requires an update.
- Validate device output, model output, paths, and imported recordings as untrusted input.
- Automatic execution must use an explicit passive allowlist. Unknown commands and transmitting commands must require manual review.
- Keep long-running operations off the GUI thread. Perform Tkinter widget updates on the GUI thread.
- Keep optional AI dependencies optional. Do not send observations to external services without a clear, deliberate user choice.
- Keep keyboard navigation, readable contrast, and usable window resizing intact.
- Do not commit virtual environments, downloaded models, compiled executables, firmware downloads, session logs, credentials, or private captures.

## Verification

Run the security regression checks and verify dependency compatibility:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip check
```

For UI changes, provide before/after images and test resizing and keyboard access. For serial changes, distinguish mocked tests from physical-board tests and record the board/firmware used. For NPU changes, report the runtime, driver, model revision, and actual execution device. Do not claim hardware testing you did not perform.

## Pull requests and licensing

Use the PR template, link the relevant issue, and document important limitations. Maintainer review is required before merging. Contributions are submitted under the project's [MIT license](LICENSE); retain existing license notices and third-party attributions. The maintainer decides release scope and timing.
