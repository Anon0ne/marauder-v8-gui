"""
marauder_flash.py — firmware fetch + flash helpers (esptool, in-process).

Kept separate from the GUI so the logic is testable on its own. Flashing runs
esptool as a library (works both from source and from the bundled .exe, as long
as esptool is importable), streaming its output to a callback.

Standard ESP32 (Arduino) flash layout is used:
    0x1000  bootloader   0x8000  partitions   0xE000 boot_app0   0x10000 app

The release .bin on the Marauder repo is the application image (0x10000); that
alone is a safe *update* for a board that already runs Marauder. A *full* flash
also writes the three support images (for a fresh or bricked board).
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # don't flash a console on Windows

MARAUDER_REPO = "justcallmekoko/ESP32Marauder"
API_LATEST = f"https://api.github.com/repos/{MARAUDER_REPO}/releases/latest"

OFFSET_BOOTLOADER = 0x1000
OFFSET_PARTITIONS = 0x8000
OFFSET_BOOT_APP0 = 0xE000
OFFSET_APP = 0x10000


def fetch_latest_release(timeout: int = 20) -> dict:
    """Return {'tag': str, 'assets': [{'name','url','size'}, ...]} for the latest release."""
    req = urllib.request.Request(
        API_LATEST,
        headers={"User-Agent": "marauder-v8-gui", "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.load(r)
    assets = [
        {"name": a["name"], "url": a["browser_download_url"], "size": a.get("size", 0)}
        for a in data.get("assets", [])
        if a.get("name", "").lower().endswith(".bin")
    ]
    return {"tag": data.get("tag_name", ""), "assets": assets}


def pick_asset(assets: list, keyword: str):
    """Best asset match for a board keyword, e.g. 'v8'. Prefers a `_<kw>.bin` suffix."""
    kw = keyword.lower().strip()
    if not kw:
        return None
    exact = [a for a in assets if a["name"].lower().endswith(f"_{kw}.bin")]
    if exact:
        return exact[0]
    cand = [a for a in assets if kw in a["name"].lower()]
    return cand[0] if cand else None


def download_asset(url: str, dest_path: str, progress_cb=None, timeout: int = 60) -> str:
    """Download a release asset to dest_path, calling progress_cb(got, total) as it goes."""
    req = urllib.request.Request(url, headers={"User-Agent": "marauder-v8-gui"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        total = int(r.headers.get("Content-Length") or 0)
        got = 0
        with open(dest_path, "wb") as f:
            while True:
                chunk = r.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                if progress_cb:
                    progress_cb(got, total)
    return dest_path


def esptool_command() -> list | None:
    """Locate a runnable esptool: the installed console script, else `-m esptool`
    when running from source. Returns None if unavailable (e.g. a frozen build
    without esptool on PATH)."""
    exe = shutil.which("esptool") or shutil.which("esptool.py")
    if exe:
        return [exe]
    if not getattr(sys, "frozen", False):
        return [sys.executable, "-m", "esptool"]
    return None


def run_esptool(args: list, out_cb, stop_flag=None) -> bool:
    """Run esptool as a subprocess, streaming combined output to out_cb line by
    line. `stop_flag()` (optional) returning True aborts. Returns True on success;
    never raises — problems are reported through out_cb."""
    base = esptool_command()
    if not base:
        # No external esptool (e.g. the frozen .exe) — run the bundled module
        # in-process instead.
        return _run_esptool_inproc(args, out_cb)
    cmd = base + args
    out_cb("$ esptool " + " ".join(args) + "\n")
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, bufsize=1, creationflags=_NO_WINDOW)
    except Exception as e:  # noqa: BLE001
        out_cb(f"[failed to launch esptool] {e}\n")
        return False
    try:
        for line in proc.stdout:
            out_cb(line)
            if stop_flag and stop_flag():
                proc.terminate()
                out_cb("\n[aborted]\n")
                break
    finally:
        proc.wait()
    return proc.returncode == 0


class _Writer(io.TextIOBase):
    """Stream esptool/rich output to a callback, with the attributes rich checks."""
    def __init__(self, cb):
        self.cb = cb

    def write(self, s):
        if s:
            self.cb(s)
        return len(s)

    def isatty(self):
        return False

    @property
    def encoding(self):
        return "utf-8"

    def flush(self):
        pass


def _run_esptool_inproc(args: list, out_cb) -> bool:
    """Run esptool as an imported module (used by the frozen .exe). Output is
    captured by redirecting stdout/stderr; never raises."""
    try:
        import esptool
    except ImportError:
        out_cb("esptool not available. Install it with:  pip install esptool\n")
        return False
    out_cb("esptool " + " ".join(args) + "\n")
    old_out, old_err = sys.stdout, sys.stderr
    w = _Writer(out_cb)
    sys.stdout = sys.stderr = w
    try:
        esptool.main(args)
        return True
    except SystemExit as e:
        return e.code in (0, None)
    except Exception as e:  # noqa: BLE001
        out_cb(f"\n[esptool error] {e}\n")
        return False
    finally:
        sys.stdout, sys.stderr = old_out, old_err


def flash_args(port: str, app_bin: str, baud: int = 921600, full: bool = False,
               support: dict | None = None, boot_offset: int = OFFSET_BOOTLOADER) -> list:
    """Build esptool write-flash args for an *update* (app only) or *full* flash.

    The chip is intentionally NOT specified — esptool auto-detects it, so the same
    code is correct for classic ESP32 (Xtensa) and the C-series (RISC-V). Flash
    mode/freq are left at the image's own header values (esptool default "keep").

    Full flash needs `support` mapping 'bootloader'/'partitions'/'boot_app0' to
    paths, and the right `boot_offset` for the family (0x1000 for esp32/s2/s3,
    0x0 for the C-series). The app image itself must match the detected chip.
    """
    a = ["--port", port, "--baud", str(baud),
         "--before", "default-reset", "--after", "hard-reset",
         "write-flash", "-z", "--flash-size", "detect"]
    if full and support:
        a += [hex(boot_offset), support["bootloader"],
              hex(OFFSET_PARTITIONS), support["partitions"],
              hex(OFFSET_BOOT_APP0), support["boot_app0"]]
    a += [hex(OFFSET_APP), app_bin]
    return a


def version_tuple(s: str):
    """Extract a (major, minor, patch) version from text, or None. Accepts '.' or
    '_' separators, e.g. 'v1.18.0' or '..._v1_18_0_...'."""
    m = re.search(r"(\d+)[._](\d+)[._](\d+)", s or "")
    return tuple(int(x) for x in m.groups()) if m else None


def version_str(vt) -> str:
    return ".".join(str(x) for x in vt) if vt else "unknown"


def version_from_filename(path: str):
    """Target version parsed from a firmware filename (release names carry it)."""
    return version_tuple(os.path.basename(path or ""))


def parse_device_version(text: str):
    """Best-effort current firmware version from serial/boot text. Prefers a line
    that mentions 'marauder'; falls back to any version-looking token."""
    for line in (text or "").splitlines():
        if "marauder" in line.lower():
            vt = version_tuple(line)
            if vt:
                return vt
    return version_tuple(text)


def chipinfo_args(port: str, baud: int = 115200) -> list:
    return ["--port", port, "--baud", str(baud), "flash-id"]


def erase_args(port: str, baud: int = 115200) -> list:
    return ["--port", port, "--baud", str(baud), "erase-flash"]
