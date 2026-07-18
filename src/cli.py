
import click

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

def benchmark(endpoint: str, model: str, input_tokens: int, output_tokens: int, concurrency: str, output: str, requests_per_level: int) -> None:
    concurrency_levels = parse_concurrency(concurrency)

    click.echo(f"Input tokens: {input_tokens}")
    click.echo(f"Output tokens: {output_tokens}")
    click.echo(f"Concurrency: {concurrency_levels}")
    click.echo(f"Benchmarking {model} at {endpoint}")
    click.echo(f"Requests per level: {requests_per_level}")

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