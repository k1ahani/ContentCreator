"""Identifier generation.

All entities use short, URL-safe, lexicographically sortable identifiers.
The timestamp prefix keeps directory listings in creation order, which matters
because project workspaces are named after their id.
"""

from __future__ import annotations

import secrets
import time

_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"


def _base36(value: int, width: int) -> str:
    out: list[str] = []
    while value:
        value, rem = divmod(value, 36)
        out.append(_ALPHABET[rem])
    return "".join(reversed(out)).rjust(width, "0")


def new_id(prefix: str = "") -> str:
    """Return a sortable 16-character id, optionally prefixed.

    Format: ``<8 chars base36 seconds><8 chars base36 randomness>``.
    Safe as a Windows directory name and as a URL path segment.
    """
    stamp = _base36(int(time.time()), 8)
    rand = _base36(secrets.randbits(40), 8)
    core = f"{stamp}{rand}"
    return f"{prefix}{core}" if prefix else core
