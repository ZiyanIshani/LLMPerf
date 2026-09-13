import math

from stats import aggregate_level, inter_token_diffs, mean, percentile


def test_mean_basic():
    assert mean([1, 2, 3]) == 2


def test_mean_empty_is_none():
    assert mean([]) is None


def test_percentile_empty_is_none():
    assert percentile([], 50) is None


def test_percentile_single_value():
    assert percentile([42], 95) == 42


def test_percentile_known_values():
    values = [1, 2, 3, 4, 5]
    assert percentile(values, 50) == 3
    assert percentile(values, 0) == 1
    assert percentile(values, 100) == 5


def test_inter_token_diffs_values():
    diffs = inter_token_diffs([1.0, 1.25, 1.5])
    assert diffs == [0.25, 0.25]


def test_inter_token_diffs_fewer_than_two_points():
    assert inter_token_diffs([]) == []
    assert inter_token_diffs([1.0]) == []


def _request(ttft=None, generation_time=None, output_tokens=0, error=None, token_times=None):
    return {
        "ttft": ttft,
        "generation_time": generation_time,
        "output_tokens": output_tokens,
        "error": error,
        "token_times": token_times or [],
    }


def test_aggregate_level_empty_requests():
    stats = aggregate_level([], wall_time_sec=1.0)
    assert stats["total_requests"] == 0
    assert stats["error_count"] == 0
    assert stats["error_rate"] is None
    assert stats["ttft_sec"]["mean"] is None
    assert stats["generation_time_sec"]["p99"] is None
    # Zero tokens over a real wall-clock window is a legitimate 0.0, not an
    # undefined value — undefined only when wall_time itself is missing/zero.
    assert stats["aggregate_output_tokens_per_sec"] == 0.0
    assert stats["inter_token_latency_mean_sec"] is None


def test_aggregate_level_excludes_nulls_not_zero():
    # A failed request contributes a null ttft/generation_time, which must
    # be excluded from the mean rather than counted as 0 (P0-class bug).
    requests = [
        _request(ttft=1.0, generation_time=2.0, output_tokens=10, token_times=[0.1, 0.2, 0.3]),
        _request(ttft=3.0, generation_time=4.0, output_tokens=20, token_times=[0.1, 0.3, 0.5]),
        _request(error="connection reset"),  # ttft/generation_time both None
    ]
    stats = aggregate_level(requests, wall_time_sec=10.0)

    assert stats["total_requests"] == 3
    assert stats["error_count"] == 1
    assert stats["error_rate"] == 1 / 3
    # mean of [1.0, 3.0], not [1.0, 3.0, 0] which would be 4/3
    assert stats["ttft_sec"]["mean"] == 2.0
    assert stats["generation_time_sec"]["mean"] == 3.0
    # total tokens (10 + 20 + 0 for the error) / wall time
    assert stats["aggregate_output_tokens_per_sec"] == 3.0


def test_aggregate_level_all_errors():
    requests = [_request(error="timeout"), _request(error="timeout")]
    stats = aggregate_level(requests, wall_time_sec=5.0)

    assert stats["error_rate"] == 1.0
    assert stats["ttft_sec"]["mean"] is None
    assert stats["generation_time_sec"]["mean"] is None
    assert stats["aggregate_output_tokens_per_sec"] == 0.0
    assert stats["inter_token_latency_mean_sec"] is None


def test_aggregate_level_inter_token_latency():
    requests = [
        _request(ttft=0.1, generation_time=1.0, output_tokens=3, token_times=[0.1, 0.3, 0.6]),
        _request(ttft=0.1, generation_time=1.0, output_tokens=2, token_times=[0.1, 0.2]),
    ]
    stats = aggregate_level(requests, wall_time_sec=2.0)
    # diffs: [0.2, 0.3] from request 1, [0.1] from request 2 -> mean of [0.2, 0.3, 0.1]
    assert math.isclose(stats["inter_token_latency_mean_sec"], 0.2)
