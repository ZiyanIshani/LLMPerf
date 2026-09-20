"""Pure aggregation/statistics helpers for turning a level's raw per-request
measurements into a summary. No I/O, no async — kept separate so it's cheap
to unit test without a live endpoint.
"""

from __future__ import annotations

import math
from collections.abc import Sequence


def mean(values: Sequence[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def stdev(values: Sequence[float]) -> float | None:
    """Sample standard deviation. None below two points — undefined, not 0."""
    if len(values) < 2:
        return None
    avg = sum(values) / len(values)
    variance = sum((v - avg) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(variance)


def percentile(values: Sequence[float], pct: float) -> float | None:
    """Linear-interpolated percentile (matches numpy's default 'linear'
    method). `pct` is 0-100. Returns None for an empty input."""
    if not values:
        return None
    sorted_values = sorted(values)
    if len(sorted_values) == 1:
        return sorted_values[0]

    rank = (len(sorted_values) - 1) * (pct / 100)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return sorted_values[int(rank)]

    lower_value = sorted_values[lower] * (upper - rank)
    upper_value = sorted_values[upper] * (rank - lower)
    return lower_value + upper_value


def _distribution(values: Sequence[float]) -> dict:
    return {
        "mean": mean(values),
        "p50": percentile(values, 50),
        "p95": percentile(values, 95),
        "p99": percentile(values, 99),
    }


def inter_token_diffs(token_times: Sequence[float]) -> list[float]:
    return [b - a for a, b in zip(token_times, token_times[1:])]


def aggregate_level(requests: list[dict], wall_time_sec: float) -> dict:
    """Compute a per-concurrency-level stats summary from the raw per-request
    dicts (as produced by RequestMeasurement.to_dict()).

    Fields are excluded from mean/percentile calculations when null (e.g. a
    failed request's ttft) rather than treated as 0 — a failed request should
    not silently drag down the aggregate for survivors, which is why
    error_rate is reported separately instead of being folded in.
    """
    total = len(requests)
    error_count = sum(1 for r in requests if r.get("error") is not None)
    error_rate = (error_count / total) if total else None

    ttft_values = [r["ttft"] for r in requests if r.get("ttft") is not None]
    generation_values = [
        r["generation_time"] for r in requests if r.get("generation_time") is not None
    ]
    # Actual generation length only makes sense as a distribution over
    # requests that actually completed — a failed request's 0 tokens is a
    # failure artifact, not a short generation, so it's excluded here the
    # same way a null ttft/generation_time is excluded above.
    actual_tokens_values = [r["actual_tokens"] for r in requests if r.get("error") is None]

    total_output_tokens = sum(r.get("actual_tokens") or 0 for r in requests)
    aggregate_output_tokens_per_sec = (
        total_output_tokens / wall_time_sec if wall_time_sec and wall_time_sec > 0 else None
    )

    all_inter_token_diffs: list[float] = []
    for r in requests:
        all_inter_token_diffs.extend(inter_token_diffs(r.get("token_times") or []))

    return {
        "total_requests": total,
        "error_count": error_count,
        "error_rate": error_rate,
        "wall_time_sec": wall_time_sec,
        "ttft_sec": _distribution(ttft_values),
        "generation_time_sec": _distribution(generation_values),
        "aggregate_output_tokens_per_sec": aggregate_output_tokens_per_sec,
        "mean_actual_output_tokens": mean(actual_tokens_values),
        "stdev_actual_output_tokens": stdev(actual_tokens_values),
        "inter_token_latency_mean_sec": mean(all_inter_token_diffs),
    }
