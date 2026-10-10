#!/usr/bin/env python3
"""
marauder.py — host-side interface for the ESP32 Marauder (V8 hardware).

The Marauder firmware exposes a serial CLI at 115200 baud. This tool opens that
port, lets you send any firmware command, and gives convenience wrappers for the
common read-only / scanning commands plus live output streaming.

It sends only commands the firmware already implements — it is a transport layer,
not an attack generator. Use it for authorized testing of networks you own or are
explicitly permitted to assess.

Requires: pyserial  (pip install pyserial)
"""

from __future__ import annotations

import argparse
import sys
import time
import threading
import codecs

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    sys.exit("pyserial is required.  Install it with:  pip install pyserial")


BAUD = 115200
DEFAULT_READ_TIMEOUT = 0.2


class Marauder:
    """Thin serial wrapper around the Marauder CLI."""

    def __init__(self, port: str, baud: int = BAUD, timeout: float = DEFAULT_READ_TIMEOUT):
        self.port = port
        self.baud = baud
        self._write_lock = threading.Lock()
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self.ser = serial.Serial(port, baud, timeout=timeout, write_timeout=1.0)
        # Give the ESP32 a moment after the port opens (it may reset).
        time.sleep(1.5)
        self.ser.reset_input_buffer()

    # ---- low-level -------------------------------------------------------

    def send(self, command: str) -> None:
        """Send a single CLI command (the trailing newline is added for you).

        Embedded control characters (CR/LF/tab/etc.) are rejected so one call
        can never smuggle multiple commands onto the wire.
        """
        if any(ord(ch) < 0x20 or ord(ch) == 0x7f for ch in command):
            raise ValueError("command contains control characters")
        cmd = command.strip()
        if len(cmd) > 4096:
            raise ValueError('command exceeds 4096 characters')
        if any(ord(ch) < 0x20 or ord(ch) == 0x7f for ch in cmd):
            raise ValueError("command contains control characters (possible injection)")
        payload = (cmd + "\n").encode("utf-8", "strict")
        with getattr(self, "_write_lock", threading.Lock()):
            written = self.ser.write(payload)
            if written != len(payload):
                raise serial.SerialTimeoutException("Incomplete command write; reconnect before retrying")

    def read_available(self) -> str:
        """Drain whatever is currently in the input buffer."""
        chunks = []
        remaining = 65536
        deadline = time.monotonic() + 0.15
        while remaining and time.monotonic() < deadline and self.ser.in_waiting:
            chunk = self.ser.read(min(self.ser.in_waiting, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
            time.sleep(0.02)
        data = b"".join(chunks)
        decoder = getattr(self, "_decoder", None)
        return decoder.decode(data) if decoder else data.decode("utf-8", "replace")

    def command(self, command: str, settle: float = 0.6) -> str:
        """Send a command and collect the reply for `settle` seconds."""
        self.ser.reset_input_buffer()
        self.send(command)
        time.sleep(settle)
        return self.read_available()

    def stream(self, duration: float | None = None) -> None:
        """Print live serial output until Ctrl-C (or `duration` seconds)."""
        end = None if duration is None else time.time() + duration
        try:
            while end is None or time.time() < end:
                data = self.read_available()
                if data:
                    sys.stdout.write(data)
                    sys.stdout.flush()
                else:
                    time.sleep(0.05)
        except KeyboardInterrupt:
            pass

    def close(self) -> None:
        try:
            self.ser.close()
        except Exception:
            pass

    # ---- convenience wrappers (map to firmware commands) -----------------

    def help(self) -> str:
        return self.command("help", settle=1.0)

    def scan_aps(self) -> None:
        """Start WiFi recon (fills AP + station lists). Stop with stopscan."""
        self.send("recon wifi")

    def scan_stations(self) -> None:
        """WiFi recon also discovers stations; BLE recon is 'recon ble'."""
        self.send("recon wifi")

    def list_aps(self) -> str:
        return self.command("list -a", settle=1.0)

    def list_stations(self) -> str:
        return self.command("list -s", settle=1.0)

    def stop(self) -> str:
        return self.command("stopscan")

    def clear_list(self) -> str:
        return self.command("clearlist -a")

    def reboot(self) -> str:
        return self.command("reboot")

    def channel(self, ch: int | None = None) -> str:
        return self.command("channel" if ch is None else f"channel -s {ch}")

    def settings(self) -> str:
        return self.command("settings -s", settle=1.0)


def autodetect_port() -> str | None:
    """Best-effort guess at the Marauder's serial port by USB-UART VID/PID."""
    # Common USB-UART bridges on ESP32 boards: CP210x (SiLabs), CH9102/CH340 (WCH), FTDI.
    known_vids = {0x10C4, 0x1A86, 0x0403, 0x303A}
    for p in list_ports.comports():
        if p.vid in known_vids:
            return p.device
    ports = list(list_ports.comports())
    return ports[0].device if len(ports) == 1 else None


def cmd_ports(_args) -> int:
    ports = list(list_ports.comports())
    if not ports:
        print("No serial ports found.")
        return 1
    for p in ports:
        vid = f"{p.vid:04X}" if p.vid else "----"
        pid = f"{p.pid:04X}" if p.pid else "----"
        print(f"{p.device:12}  VID:PID={vid}:{pid}  {p.description}")
    return 0


def resolve_port(args) -> str:
    if args.port:
        return args.port
    guess = autodetect_port()
    if not guess:
        sys.exit("Could not auto-detect a port. Use --port, or run `ports` to list them.")
    print(f"[auto-detected] {guess}", file=sys.stderr)
    return guess


def cmd_send(args) -> int:
    m = Marauder(resolve_port(args), args.baud)
    try:
        out = m.command(args.command_text, settle=args.settle)
        sys.stdout.write(out)
        if not out.endswith("\n"):
            print()
    finally:
        m.close()
    return 0


def cmd_monitor(args) -> int:
    """Open an interactive REPL: type commands, see live output."""
    m = Marauder(resolve_port(args), args.baud)
    stop = threading.Event()

    def reader():
        while not stop.is_set():
            data = m.read_available()
            if data:
                sys.stdout.write(data)
                sys.stdout.flush()
            else:
                time.sleep(0.05)

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    print("Interactive Marauder console. Type a command, or 'exit' to quit.")
    print("Tip: 'help' lists firmware commands; 'stopscan' halts a running scan.\n")
    try:
        while True:
            try:
                line = input()
            except EOFError:
                break
            if line.strip().lower() in {"exit", "quit"}:
                break
            m.send(line)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        t.join(timeout=1.0)
        m.close()
    return 0


def cmd_scan(args) -> int:
    m = Marauder(resolve_port(args), args.baud)
    try:
        m.send("recon ble" if args.ble else "recon wifi")
        print(f"Scanning for {args.duration}s... (Ctrl-C to stop early)\n", file=sys.stderr)
        m.stream(duration=args.duration)
        m.stop()
        time.sleep(0.3)
        print("\n--- Captured list ---")
        print(m.command("list -b", settle=1.0) if args.ble else
              m.list_stations() if args.stations else m.list_aps())
    finally:
        m.close()
    return 0


def cmd_help_fw(args) -> int:
    m = Marauder(resolve_port(args), args.baud)
    try:
        print(m.help())
    finally:
        m.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Host interface for the ESP32 Marauder (V8).")
    p.add_argument("--port", help="Serial port (e.g. COM5 or /dev/ttyUSB0). Auto-detected if omitted.")
    p.add_argument("--baud", type=int, default=BAUD, help=f"Baud rate (default {BAUD}).")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("ports", help="List available serial ports.")
    sp.set_defaults(func=cmd_ports)

    sp = sub.add_parser("fwhelp", help="Ask the firmware to print its command list.")
    sp.set_defaults(func=cmd_help_fw)

    sp = sub.add_parser("send", help="Send one raw firmware command and print the reply.")
    sp.add_argument("command_text", help="The command, e.g. 'list -a' (quote it).")
    sp.add_argument("--settle", type=float, default=0.8, help="Seconds to collect the reply.")
    sp.set_defaults(func=cmd_send)

    sp = sub.add_parser("monitor", help="Interactive console (type commands, see live output).")
    sp.set_defaults(func=cmd_monitor)

    sp = sub.add_parser("scan", help="Run WiFi/BLE recon and print the resulting list.")
    sp.add_argument("--stations", action="store_true", help="Print the station list afterward.")
    sp.add_argument("--ble", action="store_true", help="Use BLE recon instead of WiFi.")
    sp.add_argument("--duration", type=float, default=15.0, help="Scan seconds (default 15).")
    sp.set_defaults(func=cmd_scan)

    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
