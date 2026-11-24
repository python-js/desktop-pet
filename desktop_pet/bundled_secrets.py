"""Packaged/default secrets that are not entered by end users.

Place a real key in ``bundled_tavily.key`` next to this module (gitignored).
``bundled_tavily.key.example`` documents the format for local/release builds.
"""
from pathlib import Path

_TAVILY_FILE = Path(__file__).with_name('bundled_tavily.key')


def bundled_tavily_key():
    """Return the packaged Tavily key, or empty string when absent.

    File may keep the example header comments; the first non-empty,
    non-comment line is used as the key.
    """
    try:
        if not _TAVILY_FILE.is_file():
            return ''
        lines = _TAVILY_FILE.read_text(encoding='utf-8').splitlines()
    except OSError:
        return ''
    for raw in lines:
        key = raw.strip()
        if not key or key.startswith('#'):
            continue
        if key.startswith('tvly-REPLACE'):
            return ''
        return key
    return ''
