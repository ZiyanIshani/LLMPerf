from dataclasses import dataclass, asdict

@dataclass
class RequestMeasurement:
    request_id: str
    request_start_time: float
    first_token_time: float | None
    completion_time: float | None
    token_times: list[float]
    output_tokens: int
    error: str | None = None

    @property
    def ttft(self) -> float:
        if self.first_token_time is None:
            return None
        return self.first_token_time - self.request_start_time

    @property
    def generation_time(self) -> float | None:
        if self.completion_time is None or self.first_token_time is None:
            return None
        return self.completion_time - self.first_token_time

    @property
    def output_tokens_per_second(self) -> float | None:
        if self.generation_time is None or self.generation_time <= 0:
            return None

        return self.output_tokens / self.generation_time
    
    def to_dict(self) -> dict:
        return {
            **asdict(self),
            "ttft": self.ttft,
            "generation_time": self.generation_time,
            "output_tokens_per_second": self.output_tokens_per_second,
        }