"""Plain Python helpers that read the sample log format.

Demo 1 calls these directly to build facts for one model call. Demo 2 wraps
them as tools so Claude decides which ones to call. No model calls happen here,
so the tests can cover this file without any credentials.

Line format:
    2026-11-24T09:00:36Z ERROR orders-svc pq: too many connections ... req_id=r0002
"""

from __future__ import annotations

import re
import statistics
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

_DIGITS = re.compile(r"\d+")
_REQ_ID = re.compile(r"\s*req_id=\S+")


@dataclass(frozen=True)
class LogLine:
    number: int  # 1-based line number in the file
    timestamp: str  # ISO 8601, for example 2026-11-24T09:00:36Z
    level: str  # INFO, WARN, ERROR
    service: str
    message: str  # message text without the req_id

    @property
    def minute(self) -> str:
        """The timestamp cut to the minute, for example 2026-11-24T09:00."""
        return self.timestamp[:16]

    @property
    def pattern(self) -> str:
        """The message with every number replaced by N, so similar lines group together."""
        return _DIGITS.sub("N", self.message)


def parse(text: str) -> list[LogLine]:
    """Parse log text. Lines that don't match the format are skipped."""
    lines: list[LogLine] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        parts = raw.split(None, 3)
        if len(parts) < 4:
            continue
        timestamp, level, service, rest = parts
        lines.append(LogLine(number, timestamp, level, service, _REQ_ID.sub("", rest).strip()))
    return lines


def load(path: Path) -> list[LogLine]:
    return parse(path.read_text())


def overview(lines: list[LogLine]) -> dict[str, object]:
    """Line count, time range, and counts per level and per service."""
    if not lines:
        return {"lines": 0}
    return {
        "lines": len(lines),
        "first_timestamp": lines[0].timestamp,
        "last_timestamp": lines[-1].timestamp,
        "by_level": dict(Counter(line.level for line in lines).most_common()),
        "by_service": dict(Counter(line.service for line in lines).most_common()),
    }


def grep(lines: list[LogLine], pattern: str, limit: int = 50) -> list[str]:
    """Raw-looking lines whose level, service or message match a regex (case-insensitive)."""
    regex = re.compile(pattern, re.IGNORECASE)
    hits = [
        f"{line.number}: {line.timestamp} {line.level} {line.service} {line.message}"
        for line in lines
        if regex.search(f"{line.level} {line.service} {line.message}")
    ]
    return hits[:limit]


GROUP_FIELDS = ("level", "service", "minute", "pattern")


def count_by(lines: list[LogLine], field: str, level: str | None = None) -> dict[str, int]:
    """Count lines grouped by one field, optionally only for one level."""
    if field not in GROUP_FIELDS:
        raise ValueError(f"field must be one of {', '.join(GROUP_FIELDS)}")
    selected = [line for line in lines if level is None or line.level == level.upper()]
    return dict(Counter(str(getattr(line, field)) for line in selected).most_common())


def issues(lines: list[LogLine]) -> list[dict[str, object]]:
    """Every WARN and ERROR pattern with its service, count, first seen and last seen."""
    groups: dict[tuple[str, str, str], list[LogLine]] = {}
    for line in lines:
        if line.level in ("WARN", "ERROR"):
            groups.setdefault((line.level, line.service, line.pattern), []).append(line)
    rows = [
        {
            "level": level,
            "service": service,
            "pattern": pattern,
            "count": len(group),
            "first_seen": group[0].timestamp,
            "last_seen": group[-1].timestamp,
            "example": group[0].message,
        }
        for (level, service, pattern), group in groups.items()
    ]
    return sorted(rows, key=lambda row: -int(str(row["count"])))


def spikes(lines: list[LogLine]) -> list[dict[str, object]]:
    """Minutes where the ERROR count is more than two standard deviations above the mean."""
    per_minute = Counter(line.minute for line in lines if line.level == "ERROR")
    all_minutes = sorted({line.minute for line in lines})
    counts = [per_minute.get(minute, 0) for minute in all_minutes]
    if len(counts) < 2:
        return []
    threshold = statistics.mean(counts) + 2 * statistics.pstdev(counts)
    return [
        {"minute": minute, "errors": per_minute[minute], "threshold": round(threshold, 1)}
        for minute in all_minutes
        if per_minute.get(minute, 0) > threshold
    ]
