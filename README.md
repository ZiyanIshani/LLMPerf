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

**Done (V2):**

- Output-token standardization: `--force-output-tokens` sends
  backend-specific `extra_body={"ignore_eos": True}` (vLLM/SGLang) so
  generation runs to the requested length instead of stopping on EOS. Not
  all backends honor this (notably Ollama's OpenAI-compat layer doesn't),
  so it's opt-in, not silently probed for. Every request now records both
  `requested_output_tokens` and `actual_tokens`, and each level's `stats`
  adds `mean_actual_output_tokens` / `stdev_actual_output_tokens` so a
  reader can tell whether a throughput number came from uniform-length
  generations or a wide mix. The active mode is logged at run start.
- `report` command: renders TTFT (p50/p95), aggregate tokens/sec, and
  error rate vs. concurrency from a completed results JSON. Reads a past
  run from disk — decoupled from `benchmark`, works on any prior output.
- YAML config (`--config`) as an alternative to all-CLI-flags for
  repeatable suites — any option also passed explicitly on the command
  line still overrides the config file.
- `--header KEY:VALUE` (repeatable) for endpoints needing non-bearer auth
  beyond `--api-key`/`LLMPERF_API_KEY`. Header *names* are recorded in the
  output JSON for reproducibility; values never are.
- Console entry point: `pip install .` gives you the `bench` command
  (`bench benchmark ...` / `bench report ...`) instead of invoking
  `src/cli.py` directly.
- Minimal `Dockerfile` for pointing at a remote endpoint without local
  Python setup.
- GitHub Actions CI (`.github/workflows/ci.yml`): ruff, mypy, pytest on
  every push/PR.

**Still out of scope:** leaderboard, backend API, database,
auth-for-a-service, submission flow — those live in the separate
leaderboard-pivot direction, not this CLI.

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

This installs the `bench` console command (`pip install .` → `bench`).
`python src/cli.py ...` still works identically if you'd rather not install.

For running the test suite / lint / type-checking, also install dev deps:

```bash
pip install -e ".[dev]"
```

### Docker

```bash
docker build -t llmperf .
docker run --rm llmperf benchmark --endpoint http://host.docker.internal:11434/v1 --model llama3.2
```

## Usage

```bash
bench benchmark \
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
| `--config` | *(none)* | YAML file of defaults for the options below; an explicit CLI flag always wins |
| `--endpoint` | *(required)* | OpenAI-compatible base URL, unless set via `--config` |
| `--model` | *(required)* | unless set via `--config` |
| `--api-key` | `not-needed` | or set `LLMPERF_API_KEY` |
| `--input-tokens` | `1024` | ignored if `--prompt-file` is set |
| `--output-tokens` | `256` | max tokens generated per request |
| `--force-output-tokens` | off | force generation to `--output-tokens` via `ignore_eos` (vLLM/SGLang only) |
| `--concurrency` | `1,2,4,8,16,32` | comma-separated levels |
| `--requests-per-level` | `100` | |
| `--request-timeout` | `60.0` (sec) | per-request hard cap |
| `--warmup-requests` | `1` | discarded, not written to output |
| `--prompt-file` | *(none)* | newline-separated prompt pool, sampled per request |
| `--header` | *(none)* | `KEY:VALUE`, repeatable; non-bearer auth headers |
| `--verbose` | off | debug-level logging |

### Repeatable suites via YAML config

```yaml
# suite.yaml
endpoint: http://localhost:11434/v1
model: llama3.2
concurrency_levels: [1, 2, 4, 8]   # or: concurrency: "1,2,4,8"
requests_per_level: 20
input_tokens: 200
output_tokens: 128
prompt_file: prompts.txt
```

```bash
bench benchmark --config suite.yaml
# a flag passed here still overrides the file:
bench benchmark --config suite.yaml --requests-per-level 5
```

### Chart report

```bash
bench report results/run.json --output report.png
```

Reads a completed results JSON (no live endpoint involved) and renders TTFT
(p50/p95), aggregate tokens/sec, and error rate against concurrency as a
single PNG (or `.pdf`/`.svg`, inferred from `--output`'s extension).

## Output format

```json
{
  "config": {
    "config_file": null,
    "endpoint": "...", "model": "...",
    "force_output_tokens": false,
    "header_names": [],
    "prompt": { "...": "..." },
    "...": "..."
  },
  "levels": {
    "1": {
      "requests": [
        {
          "requested_output_tokens": 128,
          "actual_tokens": 128,
          "...": "... (ttft, generation_time, output_tokens_per_second, as before)"
        }
      ],
      "stats": {
        "total_requests": 8,
        "error_count": 0,
        "error_rate": 0.0,
        "wall_time_sec": 27.49,
        "ttft_sec": { "mean": 0.035, "p50": 0.035, "p95": 0.038, "p99": 0.038 },
        "generation_time_sec": { "mean": 3.40, "p50": 3.34, "p95": 3.66, "p99": 3.72 },
        "aggregate_output_tokens_per_sec": 37.25,
        "mean_actual_output_tokens": 128.0,
        "stdev_actual_output_tokens": 0.0,
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

`requested_output_tokens` (the `--output-tokens` cap sent with that request)
vs. `actual_tokens` (what the model actually generated) makes the
known V1 gap visible per request: with natural EOS-stop, `actual_tokens` can
vary by prompt/model behavior even at a fixed `requested_output_tokens`.
`mean_actual_output_tokens` / `stdev_actual_output_tokens` (excluding failed
requests, the same null-exclusion convention as the other stats) summarize
that spread per level — a `stdev` near 0 (as in the sample below, where every
request happened to hit the 128-token cap) means the throughput number came
from uniform-length generations; a wide `stdev` means it's a mix and should
be read with more caution. `--force-output-tokens` (vLLM/SGLang `ignore_eos`)
is one way to drive that spread toward 0 on backends that support it.

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
      "mean_actual_output_tokens": 128.0,
      "stdev_actual_output_tokens": 0.0,
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
      "mean_actual_output_tokens": 128.0,
      "stdev_actual_output_tokens": 0.0,
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

The `mean_actual_output_tokens`/`stdev_actual_output_tokens` values here
(`128.0` / `0.0`, run in natural-stop mode, no `--force-output-tokens`) are
computed from this same real run's per-request data — every request in it
happened to reach the 128-token cap rather than stopping early on EOS, so
there's no length spread to see in this particular sample. A run against a
model/prompt mix that stops early on some requests would show a non-zero
`stdev_actual_output_tokens`, which is exactly the visibility this field is
for.

## Testing

```bash
pytest        # tests
ruff check src tests
mypy src
```

All three run in CI (`.github/workflows/ci.yml`) on push/PR.

Covers the aggregation/statistics logic (`stats.py`) — including nulls
mixed into the data, empty input, and all-errored levels — the per-request
error/timeout/force-output-tokens path in `load_generator.py` (mid-stream
failures and timeouts must null out metrics uniformly, not leave partial
data), YAML config resolution and header/concurrency parsing (`cli.py`),
and chart data extraction (`report.py`). No live endpoint required for any
of it.
