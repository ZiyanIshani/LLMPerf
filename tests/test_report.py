from report import extract_series, render_report


def _stats(ttft_p50, ttft_p95, tokens_per_sec, error_rate):
    return {
        "ttft_sec": {"mean": None, "p50": ttft_p50, "p95": ttft_p95, "p99": None},
        "aggregate_output_tokens_per_sec": tokens_per_sec,
        "error_rate": error_rate,
    }


def _results():
    return {
        "config": {"model": "llama3.2", "endpoint": "http://localhost:11434/v1"},
        "levels": {
            "4": {"stats": _stats(0.5, 0.6, 30.0, 0.0)},
            "1": {"stats": _stats(0.1, 0.12, 10.0, 0.0)},
            "2": {"stats": _stats(0.2, 0.25, 20.0, 0.5)},
        },
    }


def test_extract_series_orders_by_concurrency_ascending():
    series = extract_series(_results())
    assert series["concurrency"] == [1, 2, 4]
    assert series["ttft_p50"] == [0.1, 0.2, 0.5]
    assert series["ttft_p95"] == [0.12, 0.25, 0.6]
    assert series["tokens_per_sec"] == [10.0, 20.0, 30.0]
    assert series["error_rate"] == [0.0, 0.5, 0.0]


def test_render_report_writes_a_file(tmp_path):
    output_path = tmp_path / "report.png"
    render_report(_results(), str(output_path))
    assert output_path.exists()
    assert output_path.stat().st_size > 0


def _v1_results():
    """A results JSON as V1 would have written it: no
    mean_actual_output_tokens/stdev_actual_output_tokens keys in stats at
    all (those were added in V2)."""
    return {
        "config": {"model": "llama3.2", "endpoint": "http://localhost:11434/v1"},
        "levels": {
            "1": {"stats": _stats(0.1, 0.12, 10.0, 0.0)},
            "2": {"stats": _stats(0.2, 0.25, 20.0, 0.0)},
        },
    }


def test_extract_series_handles_missing_v2_keys_gracefully():
    # A pre-V2 results file lacks mean_actual_output_tokens/
    # stdev_actual_output_tokens entirely — must not raise KeyError.
    series = extract_series(_v1_results())
    assert series["mean_actual_output_tokens"] == [None, None]
    assert series["stdev_actual_output_tokens"] == [None, None]


def test_render_report_handles_pre_v2_results_file(tmp_path):
    output_path = tmp_path / "report.png"
    render_report(_v1_results(), str(output_path))
    assert output_path.exists()
    assert output_path.stat().st_size > 0


def test_render_report_with_token_spread_data(tmp_path):
    results = _results()
    for level_stats in results["levels"].values():
        level_stats["stats"]["mean_actual_output_tokens"] = 200.0
        level_stats["stats"]["stdev_actual_output_tokens"] = 15.0

    series = extract_series(results)
    assert series["mean_actual_output_tokens"] == [200.0, 200.0, 200.0]
    assert series["stdev_actual_output_tokens"] == [15.0, 15.0, 15.0]

    output_path = tmp_path / "report.png"
    render_report(results, str(output_path))
    assert output_path.exists()
    assert output_path.stat().st_size > 0
