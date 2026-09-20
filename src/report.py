"""Renders latency-vs-concurrency charts from a completed results JSON
(as written by `cli.py benchmark`). Decoupled from run_sweep — reads a
results file from disk, never talks to a live endpoint — so it works on any
past run.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")  # headless: this is a CLI tool, no display to attach to

import matplotlib.pyplot as plt


def extract_series(results: dict) -> dict:
    """Flattens results['levels'] into per-metric lists ordered by ascending
    concurrency, for direct use as chart x/y series.

    `mean_actual_output_tokens`/`stdev_actual_output_tokens` were added in
    V2 — a results JSON written by V1 won't have them, so those two are
    read with `.get()` and come back as None rather than raising KeyError.
    Reports on pre-V2 files just won't show token-spread data.
    """
    levels = results.get("levels", {})
    concurrency = sorted(int(level) for level in levels)

    ttft_p50, ttft_p95, tokens_per_sec, error_rate = [], [], [], []
    mean_actual_tokens, stdev_actual_tokens = [], []
    for level in concurrency:
        stats = levels[str(level)]["stats"]
        ttft_p50.append(stats["ttft_sec"]["p50"])
        ttft_p95.append(stats["ttft_sec"]["p95"])
        tokens_per_sec.append(stats["aggregate_output_tokens_per_sec"])
        error_rate.append(stats["error_rate"])
        mean_actual_tokens.append(stats.get("mean_actual_output_tokens"))
        stdev_actual_tokens.append(stats.get("stdev_actual_output_tokens"))

    return {
        "concurrency": concurrency,
        "ttft_p50": ttft_p50,
        "ttft_p95": ttft_p95,
        "tokens_per_sec": tokens_per_sec,
        "error_rate": error_rate,
        "mean_actual_output_tokens": mean_actual_tokens,
        "stdev_actual_output_tokens": stdev_actual_tokens,
    }


def render_report(results: dict, output_path: str) -> None:
    """Renders TTFT (p50/p95), aggregate tokens/sec, actual-output-token
    spread, and error rate against concurrency as a single figure with four
    stacked subplots, and saves it to output_path (format inferred from the
    extension, e.g. .png/.pdf/.svg).

    The token-spread panel exists so a tokens/sec number is auditable at a
    glance: a high aggregate throughput next to a wide error bar means that
    number is being driven by a mix of generation lengths, not a uniform
    workload — the exact confound requested_output_tokens/actual_tokens
    were added to expose. Without this panel that only showed up if someone
    went and read the raw JSON.
    """
    series = extract_series(results)
    concurrency = series["concurrency"]

    config = results.get("config", {})
    title_bits = [str(config[k]) for k in ("model", "endpoint") if config.get(k)]
    title = " @ ".join(title_bits) if title_bits else "Benchmark report"

    fig, (ax_ttft, ax_throughput, ax_tokens, ax_errors) = plt.subplots(
        4, 1, figsize=(8, 13), sharex=True
    )
    fig.suptitle(title)

    ax_ttft.plot(concurrency, series["ttft_p50"], marker="o", label="p50")
    ax_ttft.plot(concurrency, series["ttft_p95"], marker="o", label="p95")
    ax_ttft.set_ylabel("TTFT (sec)")
    ax_ttft.legend()
    ax_ttft.grid(True, alpha=0.3)

    ax_throughput.plot(concurrency, series["tokens_per_sec"], marker="o", color="tab:green")
    ax_throughput.set_ylabel("Tokens/sec\n(aggregate)")
    ax_throughput.grid(True, alpha=0.3)

    _render_token_spread_panel(ax_tokens, concurrency, series)

    ax_errors.plot(concurrency, series["error_rate"], marker="o", color="tab:red")
    ax_errors.set_ylabel("Error rate")
    ax_errors.set_ylim(-0.05, 1.05)
    ax_errors.set_xlabel("Concurrency")
    ax_errors.set_xticks(concurrency)
    ax_errors.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(output_path)
    plt.close(fig)


def _render_token_spread_panel(ax, concurrency: list[int], series: dict) -> None:
    means = series["mean_actual_output_tokens"]
    stdevs = series["stdev_actual_output_tokens"]

    points = [(c, m, s) for c, m, s in zip(concurrency, means, stdevs) if m is not None]
    if not points:
        # Pre-V2 results file: stats block never had these keys.
        ax.text(
            0.5,
            0.5,
            "No actual-output-token data\n(pre-V2 results file)",
            ha="center",
            va="center",
            transform=ax.transAxes,
            color="gray",
        )
        ax.set_ylabel("Actual output\ntokens/request")
        ax.grid(True, alpha=0.3)
        return

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    yerr = [p[2] if p[2] is not None else 0.0 for p in points]

    ax.errorbar(xs, ys, yerr=yerr, marker="o", color="tab:purple", capsize=4)
    ax.set_ylabel("Actual output\ntokens/request\n(mean ± stdev)")
    ax.grid(True, alpha=0.3)
