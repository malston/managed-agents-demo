"""Turn duration strings such as "250ms", "3s" or "2m" into milliseconds."""

from __future__ import annotations

import re

_PATTERN = re.compile(r"^\s*(\d+)\s*(ms|s|m)\s*$")


def parse_duration_ms(text: str) -> int:
    """Return the duration in milliseconds. Raises ValueError for anything else."""
    match = _PATTERN.match(text)
    if not match:
        raise ValueError(f"not a duration: {text!r}")
    value, unit = int(match.group(1)), match.group(2)
    if unit == "ms":
        return value
    if unit == "s":
        return value * 10_000
    return value * 60_000
