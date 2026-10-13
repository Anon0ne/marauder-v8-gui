"""Bounded, receive-only session reader. No transport access."""
import json
from pathlib import Path

MAX_SESSION_BYTES = 128 * 1024 * 1024
MAX_LINE_BYTES = 512 * 1024
MAX_CHUNK_CHARS = 65536


def _session_file(path):
    """Resolve a user-chosen session path; only existing regular files replay."""
    if '..' in path:
        raise Exception('Invalid file path')
    resolved = Path(path).resolve(strict=True)
    if not resolved.is_file():
        raise ValueError('Session replay requires a regular file.')
    return resolved


def received_chunks(path):
    resolved = _session_file(path)
    if resolved.stat().st_size > MAX_SESSION_BYTES:
        raise ValueError('Session exceeds the 128 MiB replay limit.')
    total = 0
    with open(resolved, 'rb') as session:
        while True:
            line = session.readline(MAX_LINE_BYTES + 1)
            if not line:
                return
            total += len(line)
            if len(line) > MAX_LINE_BYTES or total > MAX_SESSION_BYTES:
                raise ValueError('Session replay size limit exceeded.')
            try:
                item = json.loads(line)
            except (ValueError, UnicodeError):
                continue
            if not isinstance(item, dict) or item.get('direction') != 'rx':
                continue
            data = item.get('data')
            if isinstance(data, str):
                if len(data) > MAX_CHUNK_CHARS:
                    raise ValueError('Recorded RX chunk exceeds 65536 characters.')
                yield data
