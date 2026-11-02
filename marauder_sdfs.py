"""
marauder_sdfs.py — SD card file manager client for the Marauder `sd` command.

Needs firmware with the `sd` serial command (ls/tree/stat/df/cat/crc/mkdir/rm/
mv/cp/get/put). Every firmware reply ends in one result line:

    @SD:OK <subcommand> [detail]
    @SD:ERR <subcommand> <reason>

Downloads and uploads move base64 lines and are checked with a zlib CRC32, so a
corrupted transfer is reported instead of silently saved. An upload is written
to "<path>.part" on the card and only renamed into place when the CRC matches.

The caller must own the serial port while a call runs: stop any background
reader first (the GUI pauses its reader thread around these calls).
"""

from __future__ import annotations

import base64
import datetime as _dt
import os
import re
import time
import zlib
from dataclasses import dataclass
from typing import Callable, Optional

LINE_TIMEOUT = 10.0
Progress = Optional[Callable[[int, int], None]]

_INT_RE = re.compile(r"^\d+$")


class SDError(Exception):
    """The firmware rejected an SD operation, or the transfer failed."""


@dataclass
class SDEntry:
    name: str
    is_dir: bool
    size: int = 0
    mtime: str = ""


def _format_mtime(raw: str) -> str:
    """Render a listing's modified-time field for display.

    The firmware's `ls` output may carry a per-entry timestamp as either a bare
    epoch-seconds integer or a preformatted date string. A known device bug
    leaves many files stamped at the unix epoch (1970-01-01); we hide that
    sentinel rather than show a misleading date, and never fail on it. Fixing
    the stamp itself is a firmware concern — here we only parse/display.
    """
    raw = raw.strip()
    if not raw:
        return ""
    if _INT_RE.match(raw):
        secs = int(raw)
        if secs <= 0:
            return ""
        try:
            parsed = _dt.datetime.fromtimestamp(secs, _dt.timezone.utc)
        except (OverflowError, OSError, ValueError):
            return ""
        if parsed.year <= 1970:
            return ""
        return parsed.strftime("%Y-%m-%d %H:%M")
    # Preformatted string straight from the device; drop the epoch sentinel.
    if raw.startswith(("1970-01-01", "1969-12-31")):
        return ""
    return raw


def parse_entry(line: str) -> "Optional[SDEntry]":
    """Parse one `ls`/`tree` line into an SDEntry, or None if it isn't one.

    Lines are tab-separated: a type marker ("D"/"F"), the name, then zero or
    more trailing fields. Historically that was just the byte size for files;
    newer firmware may also append a modified-time column. We take the first
    bare-integer trailing field as the size and treat any other trailing text
    as the timestamp, so an added (or reordered) date column never causes an
    entry to be dropped — the old failure that left the browser empty.
    """
    fields = [f.strip() for f in line.split("\t")]
    if len(fields) < 2 or fields[0] not in ("D", "F"):
        return None
    is_dir = fields[0] == "D"
    name = fields[1]
    if not name:
        return None
    size, size_set, extra = 0, False, []
    for field in fields[2:]:
        if not field:
            continue
        if not is_dir and not size_set and _INT_RE.match(field):
            size, size_set = int(field), True
        else:
            extra.append(field)
    return SDEntry(name, is_dir, size, _format_mtime(" ".join(extra)))


def _quote(path: str) -> str:
    if '"' in path or any(ord(ch) < 0x20 for ch in path):
        raise SDError(f"unsupported character in path: {path!r}")
    return f'"{path}"'


def join(parent: str, name: str) -> str:
    return (parent.rstrip("/") + "/" + name) if parent != "/" else "/" + name


class SDFiles:
    """Runs `sd` subcommands over an open `marauder.Marauder` connection."""

    def __init__(self, dev, line_timeout: float = LINE_TIMEOUT):
        self.dev = dev
        self.line_timeout = line_timeout
        self._buf = b""

    # ---- line transport --------------------------------------------------

    def _readline(self) -> str:
        deadline = time.monotonic() + self.line_timeout
        while b"\n" not in self._buf:
            if time.monotonic() > deadline:
                raise SDError("timed out waiting for the device")
            chunk = self.dev.ser.read(self.dev.ser.in_waiting or 1)
            if chunk:
                self._buf += chunk
                deadline = time.monotonic() + self.line_timeout
        line, self._buf = self._buf.split(b"\n", 1)
        text = line.decode("utf-8", "replace").rstrip("\r")
        # The CLI prompt "> " has no newline, so it prefixes the next line.
        while text.startswith("> "):
            text = text[2:]
        return text

    def _start(self, command: str) -> None:
        self._buf = b""
        self.dev.ser.reset_input_buffer()
        self.dev.send(command)

    def _result(self, sub: str, on_line: Optional[Callable[[str], None]] = None) -> str:
        """Read until this subcommand's @SD:OK / @SD:ERR line; return its detail."""
        ok, err = f"@SD:OK {sub}", f"@SD:ERR {sub}"
        while True:
            line = self._readline()
            if line == ok or line.startswith(ok + " "):
                return line[len(ok):].strip()
            if line.startswith(err):
                raise SDError(f"{sub}: {line[len(err):].strip() or 'failed'}")
            if on_line:
                on_line(line)

    def _run(self, sub: str, *args: str, on_line=None) -> str:
        self._start(" ".join(["sd", sub, *args]))
        return self._result(sub, on_line)

    # ---- file operations -------------------------------------------------

    def ls(self, path: str = "/") -> list[SDEntry]:
        entries: list[SDEntry] = []

        def parse(line):
            entry = parse_entry(line)
            if entry is not None:
                entries.append(entry)

        self._run("ls", _quote(path), on_line=parse)
        entries.sort(key=lambda e: (not e.is_dir, e.name.lower()))
        return entries

    def tree(self, path: str = "/") -> list[SDEntry]:
        """Every file and folder below `path`; names are full paths."""
        entries: list[SDEntry] = []

        def parse(line):
            entry = parse_entry(line)
            if entry is not None:
                entries.append(entry)

        self._run("tree", _quote(path), on_line=parse)
        return entries

    def df(self) -> tuple[int, int]:
        """(total bytes, used bytes)."""
        total, used = self._run("df").split()[:2]
        return int(total), int(used)

    def crc(self, path: str) -> tuple[int, int]:
        """(crc32, size) of a file on the card."""
        crc, size = self._run("crc", _quote(path)).split()[:2]
        return int(crc, 16), int(size)

    def mkdir(self, path: str) -> None:
        self._run("mkdir", _quote(path))

    def rm(self, path: str, recursive: bool = False) -> None:
        self._run("rm", *(["-r"] if recursive else []), _quote(path))

    def mv(self, src: str, dst: str) -> str:
        return self._run("mv", _quote(src), _quote(dst))

    def cp(self, src: str, dst: str, recursive: bool = False) -> str:
        return self._run("cp", *(["-r"] if recursive else []), _quote(src), _quote(dst))

    def cat(self, path: str) -> str:
        lines: list[str] = []
        self._run("cat", _quote(path), on_line=lines.append)
        return "\n".join(lines[1:] if lines and lines[0].startswith("#") else lines)

    # ---- transfers -------------------------------------------------------

    def download(self, remote: str, local: str, progress: Progress = None) -> int:
        """Copy a card file to `local`; returns the byte count."""
        self._start(f"sd get {_quote(remote)}")
        tmp = local + ".part"
        size, got, crc = None, 0, 0
        try:
            with open(tmp, "wb") as out:
                while True:
                    line = self._readline()
                    if line.startswith("@SD:ERR get"):
                        raise SDError(f"get: {line[11:].strip() or 'failed'}")
                    if line.startswith("@SD:GET "):
                        size = int(line.split()[1])
                    elif line.startswith("@SD:D ") and size is not None:
                        data = base64.b64decode(line[6:], validate=True)
                        out.write(data)
                        crc = zlib.crc32(data, crc)
                        got += len(data)
                        if progress:
                            progress(got, size)
                    elif line.startswith("@SD:OK get") and size is not None:
                        expected = int(line.split()[2], 16)
                        break
            if got != size or crc != expected:
                raise SDError("get: transfer corrupted (size or CRC mismatch)")
            os.replace(tmp, local)
        except BaseException:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise
        return got

    def upload(self, local: str, remote: str, progress: Progress = None) -> int:
        """Copy a PC file onto the card, replacing any file at `remote`."""
        with open(local, "rb") as f:
            data = f.read()
        size, crc = len(data), zlib.crc32(data)
        self._start(f"sd put {_quote(remote)} {size} {crc:08x}")
        while True:
            line = self._readline()
            if line.startswith("@SD:ERR put"):
                raise SDError(f"put: {line[11:].strip() or 'failed'}")
            if line.startswith("@SD:READY "):
                chunk = int(line.split()[1])
                break
        sent = 0
        try:
            while sent < size:
                piece = data[sent:sent + chunk]
                self.dev.send("@SD:P " + base64.b64encode(piece).decode("ascii"))
                while True:
                    line = self._readline()
                    if line.startswith("@SD:ERR put"):
                        raise SDError(f"put: {line[11:].strip() or 'failed'}")
                    if line.startswith("@SD:ACK "):
                        sent = int(line.split()[1])
                        break
                if progress:
                    progress(sent, size)
        except KeyboardInterrupt:
            self.dev.send("@SD:ABORT")
            raise
        self._result("put")
        if progress and size == 0:
            progress(0, 0)
        return size
