import asyncio
import json
import logging
from pathlib import Path

import click
from openai import AsyncOpenAI

from load_generator import run_sweep, run_warmup

logger = logging.getLogger(__name__)


@click.group()
def cli() -> None:
    pass


@cli.command()
@click.option('--endpoint',
              required=True,
                help='The endpoint to benchmark.')
@click.option('--model',
              required=True,
              help='The model to use.')
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
    help="Throwaway requests fired before the timed sweep, to absorb cold-start (e.g. Ollama model load). Discarded entirely, not written to output.",
)
@click.option(
    "--prompt-file",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help="Optional file of newline-separated prompts to sample from instead of a generated filler prompt.",
)
@click.option("--verbose", is_flag=True, default=False, help="Enable debug logging.")
def benchmark(
    endpoint: str,
    model: str,
    api_key: str,
    input_tokens: int,
    output_tokens: int,
    concurrency: str,
    output: str,
    requests_per_level: int,
    request_timeout: float,
    warmup_requests: int,
    prompt_file: str | None,
    verbose: bool,
) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    concurrency_levels = parse_concurrency(concurrency)
    prompts, prompt_meta = build_prompts(input_tokens, prompt_file)

    logger.info("Input tokens (target): %d", input_tokens)
    logger.info("Output tokens: %d", output_tokens)
    logger.info("Concurrency: %s", concurrency_levels)
    logger.info("Benchmarking %s at %s", model, endpoint)
    logger.info("Requests per level: %d", requests_per_level)
    logger.info("Request timeout: %ss", request_timeout)
    logger.info("Warm-up requests: %d", warmup_requests)
    logger.info("Prompt source: %s", prompt_meta["source"])

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
        )
    )

    output_data = {
        "config": {
            "endpoint": endpoint,
            "model": model,
            "input_tokens_target": input_tokens,
            "output_tokens": output_tokens,
            "concurrency_levels": concurrency_levels,
            "requests_per_level": requests_per_level,
            "request_timeout_sec": request_timeout,
            "warmup_requests": warmup_requests,
            "prompt": prompt_meta,
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
) -> dict:
    async with AsyncOpenAI(base_url=endpoint, api_key=api_key) as client:
        if warmup_requests > 0:
            await run_warmup(client, prompts, output_tokens, model, warmup_requests, request_timeout)
        return await run_sweep(
            client, prompts, output_tokens, model, concurrency_levels, requests_per_level, request_timeout
        )


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
            raise click.BadParameter(f"No non-empty prompts found in {prompt_file}", param_hint="--prompt-file")
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

if __name__ == "__main__":
    cli()
