import asyncio
from openai import AsyncOpenAI 
import time
from request_result import RequestMeasurement
import uuid

client = AsyncOpenAI(base_url="http://localhost:11434", api_key="ollama")
#model1="llama3.2"

async def send_request(client, prompt, output_tokens, model) -> RequestMeasurement:
    req = RequestMeasurement(
        request_id=str(uuid.uuid4()),
        request_start_time=time.perf_counter(),
        first_token_time=None,
        completion_time=None,
        token_times=[],
        output_tokens=0,
    )
    actual_tokens = 0
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=output_tokens,
            stream = True
        )
        async for event in response:
            if req.first_token_time is None:
                req.first_token_time = time.perf_counter()
            if event.choices[0].delta.content:
                actual_tokens += 1
                req.token_times.append(time.perf_counter())
    except Exception as e:
        req.error = str(e)

    req.output_tokens = actual_tokens
    req.completion_time = time.perf_counter() 

    return req



async def run_concurrency_level(client, prompt, output_tokens, model, concurrency, requests_per_level):
    semaphore = asyncio.Semaphore(concurrency)
    
    async def bounded_request():
        async with semaphore:
            return await send_request(client, prompt, output_tokens, model)

    
    tasks = [asyncio.create_task(bounded_request()) for _ in range(requests_per_level)]
    results = await asyncio.gather(*tasks)
    return results

async def main():
    async with AsyncOpenAI(base_url="http://localhost:11434/v1", api_key="ollama") as client:
        results = await run_concurrency_level(
            client=client,
            prompt="Tell me a short story about a robot.",
            output_tokens=100,
            model="llama3.2",
            concurrency=4,
            requests_per_level=10,
        )
        for r in results:
            print(r.request_id, r.ttft, r.generation_time, r.output_tokens, r.error)

asyncio.run(main())