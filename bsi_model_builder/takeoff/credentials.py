"""
API key storage — Windows Credential Manager (via keyring) under service "BSI Model Builder"; falls back to
the ANTHROPIC_API_KEY environment variable, then to a plain-text file in the settings folder only if the user
explicitly chose that (the UI warns).
"""
from __future__ import annotations
import os

SERVICE = "BSI Model Builder"
ACCOUNT = "anthropic_api_key"


def get_api_key() -> str | None:
    try:
        import keyring
        v = keyring.get_password(SERVICE, ACCOUNT)
        if v:
            return v
    except Exception:
        pass
    v = os.environ.get("ANTHROPIC_API_KEY")
    if v:
        return v
    try:
        from ..ui import settings
        p = os.path.join(os.path.dirname(settings.path()), "api_key.txt")
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as fh:
                return fh.read().strip() or None
    except Exception:
        pass
    return None


def set_api_key(value: str, plain_file_fallback: bool = False) -> str:
    """returns where it was stored: 'keyring' | 'file'"""
    value = (value or "").strip()
    try:
        import keyring
        if value:
            keyring.set_password(SERVICE, ACCOUNT, value)
        else:
            try:
                keyring.delete_password(SERVICE, ACCOUNT)
            except Exception:
                pass
        return "keyring"
    except Exception:
        if not plain_file_fallback:
            raise
    from ..ui import settings
    p = os.path.join(os.path.dirname(settings.path()), "api_key.txt")
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(value)
    return "file"


def key_source() -> str:
    try:
        import keyring
        if keyring.get_password(SERVICE, ACCOUNT):
            return "Windows Credential Manager"
    except Exception:
        pass
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "ANTHROPIC_API_KEY environment variable"
    try:
        from ..ui import settings
        if os.path.isfile(os.path.join(os.path.dirname(settings.path()), "api_key.txt")):
            return "plain file in the settings folder"
    except Exception:
        pass
    return "not set"
