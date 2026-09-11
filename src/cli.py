
import asyncio
import json
from pathlib import Path

import click
from openai import AsyncOpenAI

from load_generator import run_sweep

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
    help="Target number of input tokens per request.",
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

def benchmark(endpoint: str, model: str, api_key: str, input_tokens: int, output_tokens: int, concurrency: str, output: str, requests_per_level: int) -> None:
    concurrency_levels = parse_concurrency(concurrency)
    prompt = build_prompt(input_tokens)

    click.echo(f"Input tokens: {input_tokens}")
    click.echo(f"Output tokens: {output_tokens}")
    click.echo(f"Concurrency: {concurrency_levels}")
    click.echo(f"Benchmarking {model} at {endpoint}")
    click.echo(f"Requests per level: {requests_per_level}")

    results = asyncio.run(
        run_benchmark(endpoint, api_key, prompt, output_tokens, model, concurrency_levels, requests_per_level)
    )

    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w") as f:
        json.dump(results, f, indent=2)

    click.echo(f"Wrote results to {output}")


async def run_benchmark(endpoint: str, api_key: str, prompt: str, output_tokens: int, model: str, concurrency_levels: list[int], requests_per_level: int) -> dict:
    async with AsyncOpenAI(base_url=endpoint, api_key=api_key) as client:
        return await run_sweep(client, prompt, output_tokens, model, concurrency_levels, requests_per_level)


def build_prompt(input_tokens: int) -> str:
    # Repeats a filler word to approximate the requested token count. Not an
    # exact tokenization for any given model, but close enough to size load.
    return "Tell me a long, detailed story. " + "word " * input_tokens


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
