# CLAUDE.md — Benchmarking CLI

Project context and conventions for Claude Code when working in this repo.
This is a hardware-aware CLI for benchmarking LLM serving endpoints
(OpenAI-compatible) via concurrency sweeps: TTFT, generation time,
tokens/sec, error rate, aggregated per concurrency level.

## Status

V1 and V2 are both complete (sweep wiring, per-level stats, warm-up,
per-request timeout, output-token standardization, `report` chart
command, YAML config, console entry point + Dockerfile, CI, auth
headers). Overall a strong pass — the schema rename, config-precedence
handling via `click.ParameterSource`, and the header-values-never-logged
decision are all correct as implemented. All six V2 revisions below have
since been resolved; kept here as a record of what they were and how
each was closed out.

## V2 revisions (resolved)

1. **Report doesn't visualize the thing item 1 was for (P0). Fixed.**
   `render_report()` now has a fourth subplot: mean actual output
   tokens/request with a stdev error bar per concurrency level (see
   `_render_token_spread_panel()` in `report.py`), so a high tokens/sec
   number next to a wide error bar is visible at a glance instead of only
   discoverable by reading the raw JSON.

2. **Report command + old results files — untested edge case. Fixed.**
   `extract_series()` now reads `mean_actual_output_tokens`/
   `stdev_actual_output_tokens` with `.get()` instead of `[...]`, so a
   pre-V2 results file (missing those keys) doesn't raise `KeyError` —
   the token-spread panel renders a "no data" placeholder instead.
   Covered by `test_extract_series_handles_missing_v2_keys_gracefully`
   and `test_render_report_handles_pre_v2_results_file` in
   `tests/test_report.py`.

3. **`ignore_eos` was unit-tested, not endpoint-tested. Validated.** Ran
   real sweeps against local Ollama (`llama3.2`) with
   `--force-output-tokens`: the endpoint returns `200 OK` and completes
   normally with `extra_body={"ignore_eos": True}` set — no error, no
   exception. Confirms the "backend silently ignores unknown extra_body
   keys" assumption holds for Ollama's OpenAI-compat layer in practice,
   not just in the fake-client tests.

4. **The zero-vs-null workaround is good, but say so explicitly. Fixed.**
   Added `test_aggregate_level_real_zero_token_success_is_not_treated_as_error`
   in `tests/test_stats.py`, which asserts a real success with
   `actual_tokens=0` is included in the mean (not dropped the way an
   `error`-carrying request's `actual_tokens=0` is) — pins down that
   `aggregate_level()` filters on `error`, not `actual_tokens == 0`.

5. **Ruff scope-down deserves a comment in `pyproject.toml`. Fixed.**
   `select` now includes `BLE` and `RUF` (previously neither prefix was
   selected, so the exclusion didn't do anything), with
   `ignore = ["BLE001", "RUF007"]` and a comment explaining each: BLE001
   for the intentional blind `except Exception` in
   `load_generator.send_request`, RUF007 for the intentional manual
   `zip()` pairwise pattern in `stats.inter_token_diffs`.

6. **Docker is an open item, not a done one. Closed.** `docker build .`
   run for real (image `llmperf`), plus `docker run llmperf` and
   `docker run llmperf report --help` to confirm the `bench` entry point
   actually works inside the container, not just that the image builds.

## Working style notes

- Independent-builder preference: write implementations directly; use
  Claude for targeted guidance on specific blockers, not full code
  generation.
- Prefers direct, candid technical evaluation over flattery — call out
  confounds, bugs, and scope creep plainly.
