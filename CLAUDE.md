# LLMPerf — V1 Spec

## Context

P0 is done and tested: the CLI runs a real sweep against a real endpoint,
survives failed requests (errors captured, no crash, no silently-zeroed
metrics), and `--endpoint`/`--model`/`--input-tokens`/`--output` all flow
through correctly. This spec covers the next pass — turning a working CLI
into one whose numbers are actually trustworthy and whose repo is usable by
someone who isn't me.

**Still explicitly out of scope:** leaderboard, backend API, database,
auth-for-a-service, submission flow, Dockerfile, CI, console entry point
(`pip install .` → `bench`), YAML config for repeatable suites, chart/report
output. Those are P2+ or the separate leaderboard-pivot direction — don't
start on them this pass.

## Before making any changes

Read the current state of `cli.py`, `load_generator.py`, and
`request_result.py` fresh rather than assuming the P0 fixes look a
particular way — confirm what's actually there before building on top of it.

## V1 scope

### 1. Aggregated per-level statistics

Right now output is a flat list of per-request measurements per concurrency
level. Add a summary computed from that raw data — don't discard the raw
per-request list, add the aggregation alongside it. For each concurrency
level, compute:

- Mean, p50, p95, p99 TTFT
- Mean, p50, p95, p99 generation time
- Aggregate output tokens/sec across all requests at that level (not the
  average of per-request tokens/sec — total output tokens / total wall time
  for the level, which is the number that actually reflects throughput)
- Inter-token latency (mean time between consecutive tokens, from
  `token_times`)
- Error rate (failed requests / total requests at that level)

Excluding `null` fields correctly from mean/percentile calculations matters
here — a failed request's `null` TTFT must not become a `0` that drags the
mean down, which is the same class of bug P0 already fixed at the
per-request level. Compute stats only over requests where the relevant
field is non-null, and report the error rate separately so a level with a
high failure rate doesn't quietly hide it by only showing survivors' stats.

### 2. Warm-up phase

The first request in any sweep model-loads on a cold Ollama instance —
confirmed in testing, where request 1's TTFT was ~3.8s vs. request 2's
~0.05s, purely from cold start. Add a warm-up: fire one (or a small
configurable number of) throwaway request(s) against the endpoint before
the timed sweep begins, discard their results entirely, and don't include
them in the output JSON at all. Make sure the warm-up request actually
targets the same model that's about to be swept.

### 3. Prompt sizing / dataset input

Currently `--input-tokens` is unused and the prompt is a fixed string.
Either:

- (a) generate a prompt sized to roughly match `--input-tokens` (tokenize
  and pad/truncate, or repeat filler text to hit an approximate token
  count), or
- (b) accept a `--prompt-file` / dataset path as an alternative to
  `--input-tokens`, sampling real prompts from it.

Pick (a) if you want simplicity and consistency across runs; pick (b) if
you want realistic prompt content. Either way, record the actual prompt (or
a summary of it — length, source) in the output JSON so results are
reproducible and explainable.

### 4. Per-request timeout

Add a configurable per-request timeout (e.g. `--request-timeout` in
seconds, sensible default). A hung request currently could stall a whole
concurrency level indefinitely. A timed-out request should look like any
other error case — captured in `error`, metrics `null`, sweep continues —
not a special code path.

### 5. Auth headers / multiple prompts (if time allows)

Support an `--api-key` flag or env var (currently `"ollama"` is
hardcoded — fine for local testing, not fine for anything else) and,
optionally, allow more than one prompt/dataset entry to be sampled across
requests rather than sending the identical prompt every time.

### 6. Hardening

- `pyproject.toml` (or `requirements.txt`) with pinned dependency versions.
- Unit tests for the aggregation/statistics logic at minimum (this is the
  new logic most likely to have a subtle bug — e.g. percentile calculation
  on an empty or all-null list — and it's cheap to test since it's pure
  computation, no live endpoint needed). A mock-server integration test for
  the full sweep is a good addition if time allows, not required for V1.
- Replace any remaining `print()` calls with `logging`, with a `--verbose`
  or log-level flag.

## Definition of done for V1

- A sweep against a real endpoint produces, per concurrency level, both the
  raw per-request list (as today) and a stats summary (mean/p50/p95/p99
  TTFT and generation time, aggregate tokens/sec, inter-token latency,
  error rate).
- The first real (non-warm-up) request in the output no longer shows an
  inflated cold-start TTFT.
- A run with `--input-tokens 500` vs. `--input-tokens 50` visibly differs
  in prompt size / recorded prompt metadata.
- A hung endpoint doesn't stall the sweep past the configured timeout.
- `pip install -e .` (or equivalent) from a clean clone installs pinned
  deps with no version drift surprises.
- Aggregation logic has unit tests that pass, including at least one case
  with some `null` fields mixed into the data (proving nulls are excluded
  correctly, not treated as zero).

## Deliverables alongside the code

### README update

Update the README's status section to reflect V1 — move P0 items from "in
progress" to done, describe the new stats output and warm-up behavior, and
update or add a real sample output snippet from an actual run (not
fabricated numbers). Keep the honest-status framing from the original
README draft — don't overclaim finished features.

### Change log file

Create `CHANGES-v1.md` (or similar — pick a clear name) documenting this
pass, structured as:

```markdown
# V1 Changes

## Files created

- `path/to/new_file.py` — one or two sentences on what it does and why it
  was added.

## Files changed

- `path/to/existing_file.py` — one or two sentences per meaningful change
  (not a line-by-line diff restatement). Group related changes in one
  entry rather than listing every touched line separately.

## Summary

A few sentences on what V1 actually accomplished, framed against the V1
scope above — what's done, what (if anything) from this spec was
deliberately deferred and why.
```

This file is for me to review what actually happened in a session without
re-reading every diff — keep it accurate to the real changes, not a
restatement of this spec's intentions. If something in this spec turned out
to be wrong or need a different approach once you were in the code, note
that here too rather than silently deviating.
