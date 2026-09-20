import asyncio

from load_generator import send_request


class _FakeStreamCompletions:
    """Minimal stand-in for client.chat.completions that yields a fixed
    number of chunks then optionally raises, so we can exercise the
    mid-stream failure path without a live endpoint."""

    def __init__(self, chunks, error=None, delay=0.0):
        self._chunks = chunks
        self._error = error
        self._delay = delay
        self.received_kwargs = None

    async def create(self, **kwargs):
        self.received_kwargs = kwargs
        return self._stream()

    async def _stream(self):
        for chunk in self._chunks:
            if self._delay:
                await asyncio.sleep(self._delay)
            yield _Event(chunk)
        if self._error:
            raise self._error


class _Event:
    def __init__(self, content):
        self.choices = [_Choice(content)]


class _Choice:
    def __init__(self, content):
        self.delta = _Delta(content)


class _Delta:
    def __init__(self, content):
        self.content = content


class _FakeClient:
    def __init__(self, chunks, error=None, delay=0.0):
        self.chat = _FakeChat(chunks, error, delay)


class _FakeChat:
    def __init__(self, chunks, error=None, delay=0.0):
        self.completions = _FakeStreamCompletions(chunks, error, delay)


def test_send_request_success():
    async def _run():
        client = _FakeClient(chunks=["a", "b", "c"])
        return await send_request(client, "prompt", 10, "model", request_timeout=5)

    result = asyncio.run(_run())
    assert result.error is None
    assert result.actual_tokens == 3
    assert result.ttft is not None
    assert result.generation_time is not None


def test_send_request_mid_stream_failure_nulls_metrics():
    async def _run():
        client = _FakeClient(chunks=["a", "b"], error=RuntimeError("connection reset"))
        return await send_request(client, "prompt", 10, "model", request_timeout=5)

    result = asyncio.run(_run())
    assert result.error == "connection reset"
    # Tokens were received before the failure, but a failed request must
    # report null metrics uniformly rather than a partial/misleading value.
    assert result.actual_tokens == 0
    assert result.ttft is None
    assert result.generation_time is None
    assert result.token_times == []


def test_send_request_timeout_nulls_metrics():
    async def _run():
        client = _FakeClient(chunks=["a", "b", "c"], delay=0.05)
        return await send_request(client, "prompt", 10, "model", request_timeout=0.02)

    result = asyncio.run(_run())
    assert result.error is not None
    assert "timed out" in result.error
    assert result.actual_tokens == 0
    assert result.ttft is None
    assert result.generation_time is None


def test_send_request_records_requested_output_tokens():
    async def _run():
        client = _FakeClient(chunks=["a", "b", "c"])
        return await send_request(client, "prompt", 10, "model", request_timeout=5)

    result = asyncio.run(_run())
    assert result.requested_output_tokens == 10
    assert result.actual_tokens == 3


def test_send_request_natural_stop_omits_extra_body():
    async def _run():
        client = _FakeClient(chunks=["a"])
        await send_request(client, "prompt", 10, "model", request_timeout=5)
        return client.chat.completions.received_kwargs

    kwargs = asyncio.run(_run())
    assert "extra_body" not in kwargs


def test_send_request_force_output_tokens_sets_ignore_eos():
    async def _run():
        client = _FakeClient(chunks=["a"])
        await send_request(
            client, "prompt", 10, "model", request_timeout=5, force_output_tokens=True
        )
        return client.chat.completions.received_kwargs

    kwargs = asyncio.run(_run())
    assert kwargs["extra_body"] == {"ignore_eos": True}
