"""Per-user settings (last paths) — %APPDATA%\\BSI Model Builder\\settings.json on Windows, ~/.config elsewhere."""
from __future__ import annotations
import json, os


def _dir() -> str:
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    d = os.path.join(base, "BSI Model Builder")
    os.makedirs(d, exist_ok=True)
    return d


def path() -> str:
    return os.path.join(_dir(), "settings.json")


def load() -> dict:
    try:
        with open(path(), encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def save(d: dict) -> None:
    try:
        with open(path(), "w", encoding="utf-8") as fh:
            json.dump(d, fh, indent=1)
    except Exception:
        pass
