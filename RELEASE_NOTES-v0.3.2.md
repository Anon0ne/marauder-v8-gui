Fixes the Windows Auto Dependency script and adds manual and automated installation instructions.

## Fixes
- Keeps winget output separate from Python detection, preventing installer messages from being executed as commands.
- Detects Python 3.10-3.13 in standard per-user installation folders, including when PATH has not refreshed.
- Fixes Windows PowerShell quoting in dependency import verification.

## Installation
- **Windows:** extract `MarauderV8-v0.3.2-Windows.zip` and run the standalone EXE manually, or run `BUILD_AND_INSTALL.cmd` to install missing Python/dependencies, build from source, and create shortcuts. See `WINDOWS_INSTALL.txt` for manual source setup and build commands.
- **Linux:** extract `MarauderV8-v0.3.2-Linux.zip` and run `bash INSTALL_AND_RUN.sh`, or follow the manual steps in `LINUX_INSTALL.txt`. Linux uses Python source; missing system prerequisites can be installed automatically on Debian/Ubuntu.

The application code and prebuilt Windows executable are unchanged from v0.3.0. This release fixes installation and build tooling.

Made by Justin Funderburk - justin@bizhostnc.com
