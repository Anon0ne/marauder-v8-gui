"""Optional Windows-user DPAPI storage; never persist plaintext API keys."""
import ctypes
import os
from pathlib import Path


def _protect(data, decrypt=False):
    if os.name != 'nt':
        raise RuntimeError('Persistent key storage is Windows-only. Use a session key on this OS.')
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    destination = Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    fn = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                  ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    fn.restype = wintypes.BOOL
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(destination)):
        raise RuntimeError('Windows could not access the encrypted API key.')
    try:
        return ctypes.string_at(destination.data, destination.size)
    finally:
        kernel.LocalFree(ctypes.cast(destination.data, ctypes.c_void_p))


def key_path(folder, provider):
    names = {'OpenRouter Free': 'openrouter', 'Gemini': 'gemini'}
    return Path(folder) / '.cloud-keys' / (names[provider] + '.bin')


def save(folder, provider, key):
    encrypted = _protect(key.encode('utf-8'))
    path = key_path(folder, provider)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    try:
        temporary.write_bytes(encrypted)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def stored(folder, provider):
    return key_path(folder, provider).exists()


def load(folder, provider):
    path = key_path(folder, provider)
    if not path.exists():
        return ''
    if path.stat().st_size > 65536:
        raise RuntimeError('Invalid encrypted key file size.')
    return _protect(path.read_bytes(), decrypt=True).decode('utf-8')


def forget(folder, provider):
    # Remove the key and any leftover temporary copy from an interrupted save.
    path = key_path(folder, provider)
    path.with_suffix('.tmp').unlink(missing_ok=True)
    path.unlink(missing_ok=True)
