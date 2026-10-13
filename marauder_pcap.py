"""
marauder_pcap.py — zero-dependency inspection of .pcap files.

The Marauder writes capture files (.pcap) to its SD card while sniffing
(sniffraw, sniffpmkid, beacon/probe sniffs, etc.). Pull those files off the
card, then use this to summarize them or hand them to Wireshark/tshark.

Supports classic libpcap (both byte orders, microsecond and nanosecond).
pcapng files are detected but not parsed here — open those in Wireshark.

CLI:
    python marauder_pcap.py summary capture.pcap
    python marauder_pcap.py open capture.pcap      # launch Wireshark if found
"""

from __future__ import annotations

import os
import shutil
import struct
import subprocess
import sys
import datetime as _dt


# A few link-layer types the Marauder commonly produces.
LINKTYPES = {
    0: "NULL",
    1: "ETHERNET",
    105: "IEEE802_11",
    127: "IEEE802_11_RADIOTAP",
    147: "USER0",
}

_PCAPNG_MAGIC = b"\x0a\x0d\x0d\x0a"
_MAGICS = {
    0xA1B2C3D4: ("<", 1_000_000),   # little-endian, microsecond
    0xD4C3B2A1: (">", 1_000_000),   # big-endian, microsecond
    0xA1B23C4D: ("<", 1_000_000_000),  # little-endian, nanosecond
    0x4D3CB2A1: (">", 1_000_000_000),  # big-endian, nanosecond
}


class PcapError(Exception):
    pass


def _capture_file(path) -> str:
    """Resolve a capture path and require it to be an existing regular file.

    The path is always one the user picked (file dialog or CLI argument), so
    there is no base directory to confine it to. Resolving it and refusing
    directories, FIFOs and device nodes keeps the reader from blocking on or
    reading something that is not a capture file.
    """
    raw = os.fspath(path)
    if ".." in raw.replace("\\", "/").split("/"):
        raise PcapError("Invalid file path")
    resolved = os.path.realpath(raw)
    if not os.path.isfile(resolved):
        raise PcapError(f"Not a regular file: {os.path.basename(resolved)}")
    return resolved


def summarize(path: str, max_packets: int | None = None) -> dict:
    """Return a dict summarizing a .pcap file without external libraries."""
    resolved = _capture_file(path)
    size = os.path.getsize(resolved)
    with open(resolved, "rb") as f:
        head = f.read(4)
        if head == _PCAPNG_MAGIC:
            return {
                "path": path, "format": "pcapng", "bytes": size,
                "note": "pcapng format — open in Wireshark; this reader handles "
                        "classic libpcap only.",
            }

        f.seek(0)
        gh = f.read(24)
        if len(gh) < 24:
            raise PcapError("File too short to be a pcap.")
        magic = struct.unpack("<I", gh[:4])[0]
        if magic not in _MAGICS:
            magic_be = struct.unpack(">I", gh[:4])[0]
            if magic_be not in _MAGICS:
                raise PcapError(f"Not a libpcap file (magic 0x{magic:08x}).")
            magic = magic_be
        endian, ts_div = _MAGICS[magic]

        (_ver_maj, _ver_min, _tz, _sig, snaplen, linktype) = struct.unpack(
            endian + "HHiIII", gh[4:24]
        )

        if (_ver_maj, _ver_min) != (2, 4) or not 0 < snaplen <= 262144:
            raise PcapError("Unsupported PCAP version or invalid snap length")
        count = 0
        first_ts = last_ts = None
        total_orig = 0
        truncated = False
        corrupt = False
        sane_max = 262144   # never trust a record bigger than this
        rec_hdr = struct.Struct(endian + "IIII")
        while True:
            if max_packets is not None and count >= max_packets:
                truncated = True
                break
            rh = f.read(16)
            if not rh:
                break
            if len(rh) < 16:
                truncated = True       # dangling partial record header
                break
            ts_sec, ts_frac, incl_len, orig_len = rec_hdr.unpack(rh)
            # Validate the capture length against sanity and the file size before
            # trusting it to advance the cursor.
            if incl_len > sane_max or incl_len > snaplen or incl_len > orig_len or ts_frac >= ts_div:
                corrupt = True
                break
            if incl_len > (size - f.tell()):
                truncated = True       # record claims more bytes than remain
                break
            ts = ts_sec + ts_frac / ts_div
            if first_ts is None:
                first_ts = ts
            last_ts = ts
            total_orig += orig_len
            count += 1
            if incl_len:
                f.seek(incl_len, os.SEEK_CUR)

    duration = (last_ts - first_ts) if (first_ts is not None and last_ts is not None) else 0.0
    return {
        "path": path,
        "format": "pcap",
        "bytes": size,
        "linktype": LINKTYPES.get(linktype, f"#{linktype}"),
        "linktype_num": linktype,
        "snaplen": snaplen,
        "packets": count,
        "truncated": truncated,
        "corrupt": corrupt,
        "first_ts": first_ts,
        "last_ts": last_ts,
        "duration_s": round(duration, 3),
        "avg_pkt_bytes": round(total_orig / count, 1) if count else 0,
    }


def format_summary(info: dict) -> str:
    lines = [f"File      : {os.path.basename(info['path'])}",
             f"Format    : {info['format']}",
             f"Size      : {info['bytes']:,} bytes"]
    if info["format"] != "pcap":
        if "note" in info:
            lines.append(f"Note      : {info['note']}")
        return "\n".join(lines)
    ts = info.get("first_ts")
    when = _dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S") if ts else "n/a"
    lines += [
        f"Link type : {info['linktype']} ({info['linktype_num']})",
        f"Snap len  : {info['snaplen']}",
        f"Packets   : {info['packets']:,}"
        + (" (stopped early — corrupt record length)" if info.get("corrupt")
           else " (file truncated / incomplete)" if info["truncated"] else ""),
        f"Duration  : {info['duration_s']} s",
        f"Avg packet: {info['avg_pkt_bytes']} bytes",
        f"Start time: {when}",
    ]
    return "\n".join(lines)


def find_wireshark() -> str | None:
    """Locate Wireshark or tshark on PATH or common Windows install dirs."""
    for name in ("wireshark", "Wireshark", "tshark"):
        found = shutil.which(name)
        if found:
            return found
    for candidate in (
        r"C:\Program Files\Wireshark\Wireshark.exe",
        r"C:\Program Files (x86)\Wireshark\Wireshark.exe",
        r"C:\Program Files\Wireshark\tshark.exe",
    ):
        if os.path.exists(candidate):
            return candidate
    return None


def open_in_wireshark(path: str) -> bool:
    """Open the capture in Wireshark if available. Returns True on launch."""
    exe = find_wireshark()
    if not exe:
        return False
    try:
        subprocess.Popen([exe, "-r", path] if "tshark" in exe.lower() else [exe, path])
        return True
    except Exception:
        return False


def _main(argv) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 1
    action, path = argv[0], argv[1]
    if action == "summary":
        try:
            print(format_summary(summarize(path)))
        except (PcapError, OSError) as e:
            print(f"Error: {e}")
            return 1
    elif action == "open":
        if not open_in_wireshark(path):
            print("Wireshark/tshark not found. Install it or open the file manually.")
            return 1
        print("Launched Wireshark.")
    else:
        print(f"Unknown action '{action}'. Use 'summary' or 'open'.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
