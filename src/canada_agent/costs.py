"""Actual USD cost of a Claude call from its usage block and `config/prices.toml`.

Money is Decimal, never float: eval cost caps compare against these numbers.
"""

import tomllib
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

PRICES = Path(__file__).resolve().parents[2] / "config" / "prices.toml"
MILLION = Decimal(1_000_000)


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0

    @property
    def prompt_tokens(self) -> int:
        return self.input_tokens + self.cache_read_input_tokens + self.cache_creation_input_tokens


def load_prices(path: Path = PRICES) -> dict:
    with path.open("rb") as f:
        return tomllib.load(f)


def usd_cost(model: str, usage: Usage, prices: dict) -> Decimal:
    rates = prices["models"][model]  # KeyError on an unknown model: never silently "free"
    long_prompt = usage.prompt_tokens > rates.get("long_prompt_threshold", float("inf"))
    input_rate = Decimal(rates["long_input" if long_prompt else "input"])
    output_rate = Decimal(rates["long_output" if long_prompt else "output"])
    read = input_rate * Decimal(prices["cache_read_multiplier"])
    write = input_rate * Decimal(prices["cache_write_multiplier"])
    total = (
        usage.input_tokens * input_rate
        + usage.output_tokens * output_rate
        + usage.cache_read_input_tokens * read
        + usage.cache_creation_input_tokens * write
    ) / MILLION
    return total.normalize()
