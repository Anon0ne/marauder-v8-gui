# Windows package verification

The Windows workflow on `specter/pro-integration` uses Windows x64 and
Python 3.12.10. Installer checks run under Windows PowerShell 5.1, matching
the `.cmd` launchers. Check its result and download the `MarauderV8-Windows-beta`
artifact from [GitHub Actions](https://github.com/Anon0ne/marauder-v8-gui/actions/workflows/windows-build.yml).
Extract the complete downloaded ZIP; run `INSTALL_WINDOWS.cmd`, or launch
`MarauderV8-Control.exe` directly for portable use. Python is not needed for
the prebuilt package. Installation targets the current user's Programs folder.

## Checks performed by the workflow

1. Install pinned build dependencies, check their compatibility and run regressions.
2. Execute `Build-And-Install-Windows.ps1` with the known Python executable,
   producing and installing the actual EXE into a directory with spaces.
3. Verify the installed file's SHA-256 and both shortcut targets/working directories.
4. Launch the installed, frozen EXE in offline smoke-test mode. Verify all eleven
   GUI pages, Specter catalog forms, esptool/serial imports and bundled assets.
5. Assemble the prebuilt package and install it using `Install-Windows.ps1`.
6. Repeat installed-file, shortcut and frozen EXE checks for that package.

The ZIP includes `SHA256SUMS.txt` and JSON reports under `verification/`.
Both reports must have `result: pass`, `frozen: true`, `connected: false`,
`autoconnect: false` and eleven opened pages. The smoke test never starts a
radio job, portal, script or network exercise. Heatmap shows the normal locked
page when the separately licensed Pro add-on is absent; it is not bundled in
the public artifact. Existing entitlement checks are unchanged.

The bundled default asset is read from PyInstaller's extraction directory.
An external local `portals` folder beside the executable takes precedence when
present. The large optional Rian library is not bundled; existing SD libraries
are discovered from the connected device.

## Remaining physical acceptance

Actual Windows COM-port enumeration, USB drivers, firmware upload, SD I/O and
RF operations need the V8 attached to the user's Windows computer. Clean-machine
automatic Python bootstrap is separate: CI supplies Python already and therefore
does not exercise winget/download/install. Code signing/SmartScreen reputation
is not established by a successful build. Optional NPU acceleration and the
private Pro add-on are outside this public package's verification.

The `.cmd` launchers return PowerShell's error status instead of hiding a failed
build or install. PowerShell parsing is also checked locally before publishing.
