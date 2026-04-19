from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from itertools import count


_id_counters: dict[str, count] = {}


def next_id(prefix: str) -> str:
    counter = _id_counters.setdefault(prefix, count(1))
    return f"{prefix}-{next(counter):03d}"


def iso_at_minute(start_iso: str, minute: int) -> str:
    start = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
    return (start + timedelta(minutes=minute)).astimezone(UTC).isoformat().replace("+00:00", "Z")


def gini(values: list[float]) -> float:
    if not values:
        return 0.0
    if all(value == 0 for value in values):
        return 0.0
    ordered = sorted(values)
    n = len(ordered)
    cumulative = sum((index + 1) * value for index, value in enumerate(ordered))
    total = sum(ordered)
    return (2 * cumulative) / (n * total) - (n + 1) / n


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def haversine_minutes(lat1: float, lon1: float, lat2: float, lon2: float, mph: float = 28.0) -> int:
    radius_miles = 3958.8
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    distance = 2 * radius_miles * math.asin(math.sqrt(a))
    return max(4, int(round((distance / mph) * 60)))


def now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")

