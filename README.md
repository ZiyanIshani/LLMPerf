# LLMPerf

A CLI load generator for benchmarking LLM inference endpoints (OpenAI-compatible
APIs — tested against local Ollama). Runs a concurrency sweep against a real
endpoint and records per-request latency/throughput metrics plus aggregated
per-level statistics.

## Status

**Done (P0 + V1):**

- Real sweep against a real OpenAI-compatible endpoint via `--endpoint`.
- `--model`, `--input-tokens`, `--output-tokens`, `--concurrency`,
  `--requests-per-level`, `--output` all flow through correctly.
- Failed requests are captured (`error` field set, metrics left `null`) —
  the sweep survives and never silently reports a `0` for a failed request's
  latency.
- Per-concurrency-level aggregated statistics (mean/p50/p95/p99 TTFT and
  generation time, aggregate output tokens/sec, mean inter-token latency,
  error rate), computed alongside — not instead of — the raw per-request
  list.
- Warm-up phase: throwaway request(s) fired before the timed sweep to absorb
  Ollama's cold-start model load, discarded entirely from output.
- Prompt sizing: `--input-tokens` generates a filler prompt sized to
  approximately that many tokens (word-repetition, not exact tokenization).
  `--prompt-file` is an alternative — a newline-separated file of real
  prompts, sampled per request. Either way, the actual prompt (or dataset
  summary) is recorded in the output JSON.
- Per-request timeout (`--request-timeout`, default 60s) — a hung or
  stalled request is capped and recorded as an ordinary error, not a special
  code path, and does not stall the rest of the concurrency level.
- `--api-key` / `LLMPERF_API_KEY` (no more hardcoded key).
- Logging via `logging` (`--verbose` for debug output) instead of `print()`.
- `pyproject.toml` with pinned dependencies; `pip install -e .` installs a
  known-good dependency set.
- Unit tests for the aggregation/statistics logic (null-exclusion,
  empty-input, all-error cases) and for the per-request error/timeout path.

**Explicitly out of scope for this pass** (P2+ / leaderboard-pivot
direction): leaderboard, backend API, database, auth-for-a-service,
submission flow, Dockerfile, CI, console entry point (`pip install .` →
`bench`), YAML config for repeatable suites, chart/report output.

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

For running the test suite, also install dev deps:

```bash
pip install -e ".[dev]"
```

## Usage

```bash
python src/cli.py benchmark \
  --endpoint http://localhost:11434/v1 \
  --model llama3.2 \
  --input-tokens 200 \
  --output-tokens 128 \
  --concurrency 1,2,4 \
  --requests-per-level 8 \
  --output results/run.json
```

Key options:

| Flag | Default | Notes |
|---|---|---|
| `--endpoint` | *(required)* | OpenAI-compatible base URL |
| `--model` | *(required)* | |
| `--api-key` | `not-needed` | or set `LLMPERF_API_KEY` |
| `--input-tokens` | `1024` | ignored if `--prompt-file` is set |
| `--output-tokens` | `256` | max tokens generated per request |
| `--concurrency` | `1,2,4,8,16,32` | comma-separated levels |
| `--requests-per-level` | `100` | |
| `--request-timeout` | `60.0` (sec) | per-request hard cap |
| `--warmup-requests` | `1` | discarded, not written to output |
| `--prompt-file` | *(none)* | newline-separated prompt pool, sampled per request |
| `--verbose` | off | debug-level logging |

## Output format

```json
{
  "config": { "endpoint": "...", "model": "...", "prompt": { "...": "..." }, "...": "..." },
  "levels": {
    "1": {
      "requests": [ /* raw per-request measurements, as before */ ],
      "stats": {
        "total_requests": 8,
        "error_count": 0,
        "error_rate": 0.0,
        "wall_time_sec": 27.49,
        "ttft_sec": { "mean": 0.035, "p50": 0.035, "p95": 0.038, "p99": 0.038 },
        "generation_time_sec": { "mean": 3.40, "p50": 3.34, "p95": 3.66, "p99": 3.72 },
        "aggregate_output_tokens_per_sec": 37.25,
        "inter_token_latency_mean_sec": 0.0268
      }
    }
  }
}
```

`aggregate_output_tokens_per_sec` is total output tokens across all requests
at that level divided by the level's wall-clock time — not an average of
per-request tokens/sec — since that's the number that reflects actual
throughput under concurrency.

### Sample output (real run)

Against a local Ollama instance (`llama3.2`, `--input-tokens 200
--output-tokens 128 --concurrency 1,2,4 --requests-per-level 8`). This is
the `stats` block only — the actual run also produced the full raw
per-request list alongside it, per level, as before (output is written to
whatever path `--output` names; not checked into the repo since it's
generated data):

```json
"levels": {
  "1": {
    "stats": {
      "total_requests": 8, "error_count": 0, "error_rate": 0.0,
      "wall_time_sec": 27.49,
      "ttft_sec": { "mean": 0.035, "p50": 0.035, "p95": 0.038, "p99": 0.038 },
      "generation_time_sec": { "mean": 3.40, "p50": 3.34, "p95": 3.66, "p99": 3.72 },
      "aggregate_output_tokens_per_sec": 37.25,
      "inter_token_latency_mean_sec": 0.0268
    }
  },
  "4": {
    "stats": {
      "total_requests": 8, "error_count": 0, "error_rate": 0.0,
      "wall_time_sec": 28.04,
      "ttft_sec": { "mean": 7.90, "p50": 10.44, "p95": 10.72, "p99": 10.73 },
      "generation_time_sec": { "mean": 3.47, "p50": 3.48, "p95": 3.59, "p99": 3.62 },
      "aggregate_output_tokens_per_sec": 36.53,
      "inter_token_latency_mean_sec": 0.0273
    }
  }
}
```

Note the level-1 TTFT (~0.035s) versus the ~3.8s cold-start TTFT that used
to show up on the very first request before the warm-up phase was added —
the warm-up now absorbs that. The rise in TTFT at concurrency 4 (~7.9s
mean) is real queuing contention on a single-instance local Ollama server
under load, not a warm-up artifact.

## Testing

```bash
pytest
```

Covers the aggregation/statistics logic (`stats.py`) — including nulls
mixed into the data, empty input, and all-errored levels — and the
per-request error/timeout path in `load_generator.py` (mid-stream failures
and timeouts must null out metrics uniformly, not leave partial data).
No live endpoint required.
