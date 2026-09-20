# V2 Changes

## Summary

Implemented all six V2 scope items from `CLAUDE.md`: output-token
standardization (P0), the `report` chart command, YAML config for
repeatable suites, a console entry point + Dockerfile, GitHub Actions CI,
and the auth-headers carry-over. 34 tests pass; `ruff check` and `mypy src`
are both clean.

## Files created

- `src/report.py` — pure-ish chart-rendering module (matplotlib, `Agg`
  backend so it runs headless). `extract_series()` flattens a results
  JSON's `levels` into per-metric lists ordered by ascending concurrency;
  `render_report()` draws TTFT p50/p95, aggregate tokens/sec, and error
  rate as three stacked subplots and saves to PNG/PDF/SVG. Reads a
  completed results file from disk only — no client, no live endpoint —
  mirroring the existing `stats.py` separation (I/O-free where practical,
  cheap to unit test).
- `tests/test_report.py` — `extract_series` ordering/correctness, and that
  `render_report` actually writes a non-empty file.
- `tests/test_cli.py` — didn't exist before; covers `parse_concurrency`,
  `parse_headers`, and `resolve_config_overrides` (config-file values fill
  unset params, an explicit CLI flag still wins, comma-string vs. list
  concurrency, header mapping, and rejecting a non-mapping YAML file).
- `Dockerfile` — slim Python 3.12 base, `pip install .`, entrypoint
  `bench`. **Not verified by an actual build** — Docker Desktop's daemon
  wasn't running on this machine during this pass.
- `.dockerignore` — excludes `.venv`, caches, `.git`, test/result dirs from
  the build context.
- `.github/workflows/ci.yml` — runs `ruff check`, `mypy src`, and `pytest`
  on every push and PR.

## Files changed

- `src/request_result.py` — renamed the `output_tokens` field to
  `actual_tokens` and added `requested_output_tokens` (the `max_tokens`
  value sent for that request). `output_tokens_per_second` now divides by
  `actual_tokens`. **This is a results-JSON schema change** — see
  Architectural decisions below.
- `src/load_generator.py` — `send_request()` takes a `force_output_tokens`
  flag; when set, adds `extra_body={"ignore_eos": True}` to the completion
  request (vLLM/SGLang-specific — not sent at all in natural-stop mode, so
  it can't confuse a backend that ignores unknown `extra_body` keys
  silently rather than erroring). Sets `requested_output_tokens` on the
  measurement at construction and writes the final count to
  `actual_tokens` (renamed from `output_tokens`). `run_concurrency_level`,
  `run_warmup`, and `run_sweep` all thread `force_output_tokens` through.
  Also dropped an unused `AsyncOpenAI` import (ruff `F401`).
- `src/stats.py` — added `stdev()` (sample stdev, `None` below two points,
  computed inline rather than via `mean()` to keep mypy's type-narrowing
  happy without an `assert`). `aggregate_level()` now excludes failed
  requests from the `actual_tokens` distribution before computing
  `mean_actual_output_tokens` / `stdev_actual_output_tokens` — same
  null-exclusion convention already applied to `ttft_sec`/
  `generation_time_sec`, extended to this new metric. Also switched
  `Sequence` to import from `collections.abc` (ruff `UP035`).
- `src/cli.py` — the biggest diff:
  - `--force-output-tokens` (flag) and `--header KEY:VALUE` (repeatable)
    options; both threaded through `run_benchmark`/`AsyncOpenAI`.
  - `--config PATH` (YAML). `--endpoint`/`--model` are no longer
    `required=True` at the click level — they're validated by hand *after*
    config-file merge, so `--config` alone can supply them.
  - New helpers: `resolve_config_overrides()` (merges YAML into unset
    params via `click.ParameterSource`), `parse_headers()` (`KEY:VALUE` →
    dict), `_normalize_headers_config()` (YAML mapping or list → the same
    tuple form `parse_headers` expects).
  - Output `config` block gains `config_file`, `force_output_tokens`, and
    `header_names` (never header *values* — see below).
  - New `report` command (`bench report results.json --output chart.png`),
    calling into `src/report.py`.
  - Wrapped two lines that exceeded the new 110-char ruff limit.
- `pyproject.toml` — added `pyyaml==6.0.3` and `matplotlib==3.11.2` to
  runtime deps; `ruff==0.16.8` and `mypy==2.3.1` to `[dev]`; added
  `[project.scripts] bench = "cli:cli"`; added `report` to `py-modules`;
  added `[tool.ruff]` (`select = ["E","F","I","UP"]`, line-length 110) and
  `[tool.mypy]` (`python_version = "3.12"`, `ignore_missing_imports`)
  config blocks.
- `README.md` — moved the six V2 items from "out of scope" to "Done",
  documented `--force-output-tokens`, `--header`, `--config` (with a YAML
  example), the `report` command, Docker usage, and the `bench` entry
  point; updated the output-format JSON example and the real-run sample
  output to include `requested_output_tokens`/`actual_tokens`/
  `mean_actual_output_tokens`/`stdev_actual_output_tokens` (the sample
  values were computed by re-running `aggregate_level()` against the real
  `src/results/run.json` data, not fabricated); Testing section now
  mentions `ruff`/`mypy`.
- `tests/test_load_generator.py` / `tests/test_stats.py` — renamed
  `output_tokens` references to `actual_tokens` throughout; added tests for
  `requested_output_tokens`, that natural-stop mode omits `extra_body`,
  that `--force-output-tokens` sets `ignore_eos`, and that
  `mean_actual_output_tokens`/`stdev_actual_output_tokens` exclude failed
  requests.

## Architectural decisions

- **`output_tokens` → `requested_output_tokens` + `actual_tokens` is a
  breaking schema change.** The old field name was genuinely ambiguous
  (CLI flag `--output-tokens` means "cap," the old dataclass field meant
  "actual") — CLAUDE.md's own "Known gap" writeup names `actual_tokens`
  explicitly, so I renamed rather than bolting on a same-meaning field
  under a new name. Cost: results files from before this pass (e.g.
  `src/results/run.json`) use the old field name per-request. This doesn't
  break anything in this repo — `report.py` only reads the `stats` block,
  never raw per-request fields — but a script parsing old raw request data
  elsewhere would need updating.
- **`mean_actual_output_tokens`/`stdev_actual_output_tokens` exclude
  failed requests**, not just null values, because a failed request's
  `actual_tokens` is `0` (a failure artifact, per the existing zero-vs-null
  handling — see caveat below), not a legitimately short generation. Same
  reasoning as excluding null `ttft` from its mean; extended to a case
  where the "null" is actually a zero.
- **YAML config precedence via `click.ParameterSource`**, not a hand-rolled
  "did the user pass this" check. `--endpoint`/`--model` had to drop
  `required=True` and get validated manually after the merge, since click
  enforces `required` before the command body (and thus before config-file
  values are available) runs.
- **`--header` records names only, never values, in the output JSON.**
  Consistent with `--api-key` already not being written to `config` — a
  results file is meant to be reproducible/shareable per CLAUDE.md's
  self-describing-JSON convention, and a raw auth token doesn't belong in
  a file that convention implies might get committed or passed around.
- **`ignore_eos` is only added to the request when `--force-output-tokens`
  is set** — never sent as `False`/omitted-by-default — so a backend that
  doesn't recognize the key can't silently misbehave on a flag the user
  didn't ask for.
- **ruff scoped to `E, F, I, UP`, not a stricter/broader default.** A
  broader ruff run also flagged `BLE001` (blind `except Exception`) on the
  exact line that implements the "timeouts degrade to ordinary errors"
  convention CLAUDE.md calls out as intentional, and `RUF007` (prefer
  `itertools.pairwise`) on working, already-tested code. Scoped the
  selection down rather than rewriting code CLAUDE.md explicitly endorses
  to satisfy a linter default.
- **`report.py` is a new top-level module, not a function inside
  `cli.py`.** Matches the existing `load_generator.py`/`stats.py` split:
  keep rendering/aggregation logic separately testable from the click
  command that wires it up.

## Next steps

- **Verify the Dockerfile actually builds** — Docker's daemon wasn't
  running locally during this pass, so `docker build` was never run
  against it.
- **Pre-existing convention mismatch, left untouched:** CLAUDE.md's
  "Conventions established in V1" says a failed request's `output_tokens`
  must be null, but V1's actual code (and its tests) zero it instead. This
  predates this pass; fixing it would mean changing `RequestMeasurement`'s
  type from `int` to `int | None` and updating every consumer, which
  wasn't part of the V2 ask. Worth a deliberate decision at some point
  rather than staying an accidental gap.
- **Old results files use the pre-rename field name.** Nothing in this
  repo currently breaks on that, but flagging it in case a future script
  reads raw per-request data from a file generated before this pass.
- **Mock-server integration test for the full sweep** — still explicitly
  out of scope per `CLAUDE.md`; unchanged from V1's reasoning.
