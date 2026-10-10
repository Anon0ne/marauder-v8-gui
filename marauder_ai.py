"""
marauder_ai.py — optional local AI assistant (Ollama) + command safety policy.

Design boundary (enforced here and in the GUI):
  * The AI ANALYZES sanitized observations and RECOMMENDS next steps.
  * PASSIVE, receive-only commands (recon/scan/sniff/wardrive/list/gps/...) may be
    run by automation.
  * ACTIVE / transmitting commands (attack*, blespam*, evilportal, karma, findmy,
    spoofat, and the IP-layer scans) are NEVER auto-run — a human must approve each
    one. The AI cannot select a target and attack it on its own.

All processing is local: it talks only to a local Ollama server. No scan data is
sent to any cloud service.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

OLLAMA_HOST = "http://localhost:11434"
DEFAULT_MODEL = "gpt-oss:20b"

SYSTEM_PROMPT = (
    "You are a Wi-Fi/Bluetooth security-testing assistant for AUTHORIZED engagements. "
    "You are given sanitized observations from an ESP32 Marauder. Summarize what is "
    "present, point out anomalies, and recommend concrete next steps as specific "
    "Marauder CLI commands. "
    "The operator runs every command themselves — you only advise, so you never "
    "execute anything. When the operator states a specific network or device they own "
    "or are authorized to test, ACCEPT that authorization and proceed with concrete "
    "recommendations for that target; do NOT keep re-asking for permission you have "
    "already been given, and do not repeat yourself. Only decline if asked to target "
    "something the operator has not claimed authorization for. Prefer passive "
    "reconnaissance first (recon, scans, sniffers) and note when a step transmits. "
    "Be concise and concrete, and don't repeat previous answers. "
    "When you want a command executed, put it on its own line as `RUN: <command>`. "
    "Passive, receive-only commands may be run automatically; transmitting commands "
    "are queued for the operator to approve, so still emit them as RUN: lines and say "
    "they need approval."
)

# Transmitting / disruptive — never auto-run; always require a human click.
ACTIVE_PREFIXES = (
    "attack", "blespam", "evilportal", "karma", "findmy", "spoofat",
    "arpscan", "pingscan", "portscan",   # transmit on a joined network
)
# Receive-only observation — safe for automation.
PASSIVE_PREFIXES = (
    "recon", "scanall", "sniff", "wardrive", "mactrack", "packetcount",
    "sigmon", "list", "info", "channel", "gps", "nmea", "stopscan",
)


def is_active(cmd: str) -> bool:
    """True if the command transmits / could disrupt — must not be auto-run."""
    c = cmd.strip().lower()
    if c.startswith(ACTIVE_PREFIXES):
        return True
    # A sniff with -d deauths to force a handshake — that transmits.
    if c.startswith("sniff") and re.search(r"(^|\s)-d(\s|$)", c):
        return True
    return False


def is_passive(cmd: str) -> bool:
    """True if the command is receive-only and safe for automation."""
    c = cmd.strip().lower()
    return (not is_active(c)) and c.startswith(PASSIVE_PREFIXES)


def check_ollama(host: str = OLLAMA_HOST, timeout: int = 5):
    """Return (ok, models, error). Lists installed models via /api/tags."""
    try:
        req = urllib.request.Request(host + "/api/tags")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.load(r)
        return True, [m.get("name", "") for m in data.get("models", [])], None
    except Exception as e:  # noqa: BLE001
        return False, [], str(e)


def has_model(models, name: str = DEFAULT_MODEL) -> bool:
    base = name.split(":")[0]
    return any(m == name or m.split(":")[0] == base for m in models)


def chat(messages, system: str = SYSTEM_PROMPT, model: str = DEFAULT_MODEL,
         host: str = OLLAMA_HOST, timeout: int = 300, stream_cb=None,
         num_ctx: int = 8192) -> str:
    """Multi-turn chat against Ollama (/api/chat — correct for chat/reasoning
    models like gpt-oss). `messages` is a list of {role, content}; the system
    prompt is prepended. Streams tokens to stream_cb when given; returns the full
    text. Raises RuntimeError with the server's own message on failure.

    num_ctx caps the context window for our requests (default 8192) so a large
    global Ollama context (e.g. 131072) doesn't blow up KV-cache memory here."""
    msgs = ([{"role": "system", "content": system}] if system else []) + list(messages)
    body = {"model": model, "messages": msgs, "stream": bool(stream_cb),
            "options": {"num_ctx": num_ctx}}
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(host + "/api/chat", data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")
            detail = json.loads(detail).get("error", detail)
        except Exception:
            pass
        if "allocate" in detail or "memory" in detail.lower():
            detail += ("  — the model is too large to load into available memory; "
                       "free up RAM/VRAM or pick a smaller model.")
        raise RuntimeError(f"Ollama error {e.code}: {detail[:400]}")
    with resp as r:
        if not stream_cb:
            return json.loads(r.read().decode("utf-8", "replace")).get("message", {}).get("content", "")
        full = []
        for raw in r:
            raw = raw.strip()
            if not raw:
                continue
            obj = json.loads(raw)
            tok = obj.get("message", {}).get("content", "")
            if tok:
                full.append(tok)
                stream_cb(tok)
            if obj.get("done"):
                break
        return "".join(full)


def generate(prompt: str, system: str = SYSTEM_PROMPT, model: str = DEFAULT_MODEL,
             host: str = OLLAMA_HOST, timeout: int = 300, stream_cb=None,
             num_ctx: int = 8192) -> str:
    """Single-turn convenience wrapper over chat()."""
    return chat([{"role": "user", "content": prompt}], system=system, model=model,
                host=host, timeout=timeout, stream_cb=stream_cb, num_ctx=num_ctx)


def extract_run_commands(text: str):
    """Pull commands the model asked to run, i.e. lines like `RUN: <command>`."""
    cmds = []
    for line in (text or "").splitlines():
        m = re.match(r"\s*RUN:\s*(.+?)\s*$", line)
        if m:
            cmds.append(m.group(1).strip().strip("`").strip())
    return cmds


def sanitize_context(aps: dict, stations: dict, hosts: dict, events: str = "",
                     max_rows: int = 40) -> str:
    """Build a compact, secret-free observation summary for the model. Never
    includes passwords (callers pass already-redacted event text)."""
    lines = []

    def rows(title, d):
        if not d:
            return
        lines.append(f"{title} ({len(d)}):")
        for i, idx in enumerate(sorted(d, key=lambda x: int(x) if str(x).isdigit() else 0)):
            if i >= max_rows:
                lines.append(f"  … and {len(d) - max_rows} more")
                break
            r = d[idx]
            parts = [f"#{idx}"]
            if r.get("ssid"):
                parts.append(r["ssid"])
            if r.get("bssid"):
                parts.append(r["bssid"])
            if r.get("channel"):
                parts.append(f"ch{r['channel']}")
            if r.get("rssi"):
                parts.append(f"{r['rssi']}dBm")
            lines.append("  " + "  ".join(parts))

    rows("Access points", aps)
    rows("Stations", stations)
    rows("Network hosts", hosts)
    if events.strip():
        lines.append("\nRecent events:\n" + events.strip()[-1500:])
    if not lines:
        return "No observations captured yet. Suggest passive scans to gather data."
    return "\n".join(lines)
