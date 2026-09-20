import asyncio
import json
import logging
from pathlib import Path

import click
import yaml
from openai import AsyncOpenAI

from load_generator import run_sweep, run_warmup
from report import render_report

logger = logging.getLogger(__name__)

# Maps a benchmark() parameter name to the YAML key(s) that can supply it,
# checked in order. Only consulted for a parameter the user did NOT pass
# explicitly on the command line (see ParameterSource check in benchmark()),
# so an explicit CLI flag always wins over the config file.
_CONFIG_KEY_ALIASES = {
    "concurrency": ("concurrency", "concurrency_levels"),
}


@click.group()
def cli() -> None:
    pass


@cli.command()
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help=(
        "YAML file providing defaults for the other options below (e.g. "
        "concurrency_levels, requests_per_level, model, endpoint, "
        "input_tokens, output_tokens, prompt_file). Any option passed "
        "explicitly on the command line always overrides the config file."
    ),
)
@click.option('--endpoint',
              default=None,
                help='The endpoint to benchmark. Required unless supplied via --config.')
@click.option('--model',
              default=None,
              help='The model to use. Required unless supplied via --config.')
@click.option(
    "--api-key",
    envvar="LLMPERF_API_KEY",
    default="not-needed",
    show_default=True,
    help="API key for the endpoint. Can also be set via LLMPERF_API_KEY.",
)
@click.option(
    "--input-tokens",
    type=click.IntRange(min=1),
    default=1024,
    show_default=True,
    help="Target number of input tokens per request (ignored if --prompt-file is set).",
)
@click.option(
    "--output-tokens",
    type=click.IntRange(min=1),
    default=256,
    show_default=True,
    help="Maximum number of generated tokens per request.",
)
@click.option(
    "--concurrency",
    type=str,
    default="1,2,4,8,16,32",
    show_default=True,
    help="Comma-separated concurrency levels to benchmark.",
)
@click.option("--output", type=click.Path(), default="results/run.json", show_default=True)
@click.option("--requests-per-level", type=click.IntRange(min=1), default=100, show_default=True)
@click.option(
    "--request-timeout",
    type=click.FloatRange(min=0.1),
    default=60.0,
    show_default=True,
    help="Per-request timeout in seconds. A request that hangs past this is recorded as an error.",
)
@click.option(
    "--warmup-requests",
    type=click.IntRange(min=0),
    default=1,
    show_default=True,
    help=(
        "Throwaway requests fired before the timed sweep, to absorb "
        "cold-start (e.g. Ollama model load). Discarded entirely, not "
        "written to output."
    ),
)
@click.option(
    "--prompt-file",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help="Optional file of newline-separated prompts to sample from instead of a generated filler prompt.",
)
@click.option(
    "--force-output-tokens",
    is_flag=True,
    default=False,
    help=(
        "Force generation to run to --output-tokens via backend-specific "
        "extra_body={'ignore_eos': True} (vLLM/SGLang) instead of letting the "
        "model stop on EOS. Not all backends support this (notably Ollama's "
        "OpenAI-compat layer does not) — it's opt-in rather than silently "
        "probed for."
    ),
)
@click.option(
    "--header",
    "headers",
    multiple=True,
    metavar="KEY:VALUE",
    help=(
        "Additional HTTP header to send with every request, as KEY:VALUE. "
        "Repeatable. For endpoints needing non-bearer auth beyond --api-key."
    ),
)
@click.option("--verbose", is_flag=True, default=False, help="Enable debug logging.")
@click.pass_context
def benchmark(
    ctx: click.Context,
    config_path: str | None,
    endpoint: str | None,
    model: str | None,
    api_key: str,
    input_tokens: int,
    output_tokens: int,
    concurrency: str,
    output: str,
    requests_per_level: int,
    request_timeout: float,
    warmup_requests: int,
    prompt_file: str | None,
    force_output_tokens: bool,
    headers: tuple[str, ...],
    verbose: bool,
) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if config_path is not None:
        overrides = resolve_config_overrides(ctx, config_path)
        endpoint = overrides.get("endpoint", endpoint)
        model = overrides.get("model", model)
        api_key = overrides.get("api_key", api_key)
        input_tokens = overrides.get("input_tokens", input_tokens)
        output_tokens = overrides.get("output_tokens", output_tokens)
        concurrency = overrides.get("concurrency", concurrency)
        output = overrides.get("output", output)
        requests_per_level = overrides.get("requests_per_level", requests_per_level)
        request_timeout = overrides.get("request_timeout", request_timeout)
        warmup_requests = overrides.get("warmup_requests", warmup_requests)
        prompt_file = overrides.get("prompt_file", prompt_file)
        force_output_tokens = overrides.get("force_output_tokens", force_output_tokens)
        headers = overrides.get("headers", headers)
        logger.info("Loaded config defaults from %s", config_path)

    if not endpoint:
        raise click.UsageError("--endpoint is required (directly or via --config).")
    if not model:
        raise click.UsageError("--model is required (directly or via --config).")

    concurrency_levels = parse_concurrency(concurrency)
    prompts, prompt_meta = build_prompts(input_tokens, prompt_file)
    parsed_headers = parse_headers(headers)

    logger.info("Input tokens (target): %d", input_tokens)
    logger.info("Output tokens: %d", output_tokens)
    logger.info(
        "Output-token mode: %s",
        "forced (ignore_eos)" if force_output_tokens else "natural-stop (EOS)",
    )
    logger.info("Concurrency: %s", concurrency_levels)
    logger.info("Benchmarking %s at %s", model, endpoint)
    logger.info("Requests per level: %d", requests_per_level)
    logger.info("Request timeout: %ss", request_timeout)
    logger.info("Warm-up requests: %d", warmup_requests)
    logger.info("Prompt source: %s", prompt_meta["source"])
    if parsed_headers:
        logger.info("Extra headers: %s", list(parsed_headers.keys()))

    results = asyncio.run(
        run_benchmark(
            endpoint,
            api_key,
            prompts,
            output_tokens,
            model,
            concurrency_levels,
            requests_per_level,
            request_timeout,
            warmup_requests,
            force_output_tokens,
            parsed_headers,
        )
    )

    output_data = {
        "config": {
            "config_file": config_path,
            "endpoint": endpoint,
            "model": model,
            "input_tokens_target": input_tokens,
            "output_tokens": output_tokens,
            "force_output_tokens": force_output_tokens,
            "concurrency_levels": concurrency_levels,
            "requests_per_level": requests_per_level,
            "request_timeout_sec": request_timeout,
            "warmup_requests": warmup_requests,
            "prompt": prompt_meta,
            # Names only, never values — an API secret sent via --header
            # must not end up readable in a committed/shared results file.
            "header_names": list(parsed_headers.keys()),
        },
        "levels": results,
    }

    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w") as f:
        json.dump(output_data, f, indent=2)

    logger.info("Wrote results to %s", output)


async def run_benchmark(
    endpoint: str,
    api_key: str,
    prompts: list[str],
    output_tokens: int,
    model: str,
    concurrency_levels: list[int],
    requests_per_level: int,
    request_timeout: float,
    warmup_requests: int,
    force_output_tokens: bool = False,
    headers: dict[str, str] | None = None,
) -> dict:
    async with AsyncOpenAI(base_url=endpoint, api_key=api_key, default_headers=headers or None) as client:
        if warmup_requests > 0:
            await run_warmup(
                client, prompts, output_tokens, model, warmup_requests, request_timeout, force_output_tokens
            )
        return await run_sweep(
            client,
            prompts,
            output_tokens,
            model,
            concurrency_levels,
            requests_per_level,
            request_timeout,
            force_output_tokens,
        )


_CONFIG_PARAM_NAMES = (
    "endpoint",
    "model",
    "api_key",
    "input_tokens",
    "output_tokens",
    "concurrency",
    "output",
    "requests_per_level",
    "request_timeout",
    "warmup_requests",
    "prompt_file",
    "force_output_tokens",
    "headers",
)


def resolve_config_overrides(ctx: click.Context, config_path: str) -> dict:
    """Reads a YAML config file and returns {param_name: value} only for
    benchmark() parameters the user did NOT pass explicitly (command line or
    env var) — an explicit flag always beats the config file."""
    with open(config_path) as f:
        file_config = yaml.safe_load(f) or {}
    if not isinstance(file_config, dict):
        raise click.BadParameter("Config file must contain a YAML mapping.", param_hint="--config")

    overrides: dict = {}
    for name in _CONFIG_PARAM_NAMES:
        if ctx.get_parameter_source(name) != click.ParameterSource.DEFAULT:
            continue
        for key in _CONFIG_KEY_ALIASES.get(name, (name,)):
            if key not in file_config:
                continue
            value = file_config[key]
            if name == "concurrency" and isinstance(value, list):
                value = ",".join(str(v) for v in value)
            if name == "headers":
                value = _normalize_headers_config(value)
            overrides[name] = value
            break
    return overrides


def _normalize_headers_config(value) -> tuple[str, ...]:
    if isinstance(value, dict):
        return tuple(f"{k}:{v}" for k, v in value.items())
    return tuple(value)


def parse_headers(values: tuple[str, ...]) -> dict[str, str]:
    headers: dict[str, str] = {}
    for value in values:
        if ":" not in value:
            raise click.BadParameter(
                f"Expected KEY:VALUE, got {value!r}", param_hint="--header"
            )
        key, _, val = value.partition(":")
        key = key.strip()
        if not key:
            raise click.BadParameter(f"Empty header name in {value!r}", param_hint="--header")
        headers[key] = val.strip()
    return headers


def build_prompt(input_tokens: int) -> str:
    # Repeats a filler word to approximate the requested token count. Not an
    # exact tokenization for any given model, but close enough to size load.
    return "Tell me a long, detailed story. " + "word " * input_tokens


def build_prompts(input_tokens: int, prompt_file: str | None) -> tuple[list[str], dict]:
    """Returns (prompts, metadata) where metadata records how the prompt(s)
    were produced, for reproducibility in the output JSON."""
    if prompt_file is not None:
        lines = [line.strip() for line in Path(prompt_file).read_text().splitlines()]
        prompts = [line for line in lines if line]
        if not prompts:
            raise click.BadParameter(
                f"No non-empty prompts found in {prompt_file}", param_hint="--prompt-file"
            )
        meta = {
            "source": f"file:{prompt_file}",
            "num_prompts": len(prompts),
            "preview": prompts[0][:200],
        }
        return prompts, meta

    prompt = build_prompt(input_tokens)
    meta = {
        "source": "generated",
        "num_prompts": 1,
        "input_tokens_target": input_tokens,
        "approx_word_count": len(prompt.split()),
        "preview": prompt[:200],
    }
    return [prompt], meta


def parse_concurrency(value: str) -> list[int]:
    try:
        levels = [int(item.strip()) for item in value.split(",")]
    except ValueError as exc:
        raise click.BadParameter(
            "Concurrency must be comma-separated integers, such as 1,2,4,8."
        ) from exc

    if not levels or any(level <= 0 for level in levels):
        raise click.BadParameter(
            "All concurrency levels must be positive integers."
        )

    return sorted(set(levels))


@cli.command()
@click.argument("results_file", type=click.Path(exists=True, dir_okay=False))
@click.option(
    "--output",
    type=click.Path(),
    default="report.png",
    show_default=True,
    help="Path to write the rendered chart to (format inferred from the extension, e.g. .png/.pdf/.svg).",
)
@click.option("--verbose", is_flag=True, default=False, help="Enable debug logging.")
def report(results_file: str, output: str, verbose: bool) -> None:
    """Render latency-vs-concurrency curves from a completed results JSON
    (as written by `benchmark`). Reads a past run from disk — no live
    endpoint involved."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    with open(results_file) as f:
        results = json.load(f)

    render_report(results, output)
    logger.info("Wrote report to %s", output)


if __name__ == "__main__":
    cli()
