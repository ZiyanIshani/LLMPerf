import asyncio
import logging
import random
import time
import uuid

from openai import AsyncOpenAI

from request_result import RequestMeasurement
from stats import aggregate_level

logger = logging.getLogger(__name__)


async def send_request(client, prompt, output_tokens, model, request_timeout) -> RequestMeasurement:
    req = RequestMeasurement(
        request_id=str(uuid.uuid4()),
        request_start_time=time.perf_counter(),
        first_token_time=None,
        completion_time=None,
        token_times=[],
        output_tokens=0,
    )
    actual_tokens = 0

    async def _stream_request():
        nonlocal actual_tokens
        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=output_tokens,
            stream=True,
        )
        async for event in response:
            if req.first_token_time is None:
                req.first_token_time = time.perf_counter()
            if event.choices[0].delta.content:
                actual_tokens += 1
                req.token_times.append(time.perf_counter())

    try:
        await asyncio.wait_for(_stream_request(), timeout=request_timeout)
    except asyncio.TimeoutError:
        req.error = f"Request timed out after {request_timeout}s"
    except Exception as e:
        req.error = str(e)

    if req.error is not None:
        # A request that fails partway through (mid-stream timeout, dropped
        # connection) may have collected some tokens already. Treat it like
        # any other failure — null metrics, not a partial/misleading number —
        # so it can't quietly skew aggregate stats.
        req.first_token_time = None
        req.token_times = []
        actual_tokens = 0

    req.output_tokens = actual_tokens
    req.completion_time = time.perf_counter()

    return req


async def run_concurrency_level(
    client, prompts, output_tokens, model, concurrency, requests_per_level, request_timeout
):
    semaphore = asyncio.Semaphore(concurrency)

    async def bounded_request():
        prompt = random.choice(prompts)
        async with semaphore:
            return await send_request(client, prompt, output_tokens, model, request_timeout)

    level_start = time.perf_counter()
    tasks = [asyncio.create_task(bounded_request()) for _ in range(requests_per_level)]
    results = await asyncio.gather(*tasks)
    level_wall_time = time.perf_counter() - level_start

    request_dicts = [res.to_dict() for res in results]
    stats = aggregate_level(request_dicts, level_wall_time)
    return {"requests": request_dicts, "stats": stats}


async def run_warmup(client, prompts, output_tokens, model, warmup_requests, request_timeout):
    """Fire throwaway requests against the endpoint before the timed sweep so
    the first real measurement isn't inflated by Ollama's cold-start model
    load. Results are discarded entirely — not included in the output."""
    for i in range(warmup_requests):
        logger.info("Warm-up request %d/%d", i + 1, warmup_requests)
        prompt = random.choice(prompts)
        result = await send_request(client, prompt, output_tokens, model, request_timeout)
        if result.error is not None:
            logger.warning("Warm-up request failed (continuing anyway): %s", result.error)


async def run_sweep(client, prompts, output_tokens, model, concurrency_levels, requests_per_level, request_timeout):
    all_results = {}
    for level in concurrency_levels:
        logger.info("Running concurrency level: %d", level)
        all_results[level] = await run_concurrency_level(
            client, prompts, output_tokens, model, level, requests_per_level, request_timeout
        )
    return all_results
