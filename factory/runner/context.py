"""Resources supplied to each document run."""

from dataclasses import dataclass, field
from random import Random

from factory.browser.browser import Browser
from factory.contract.models import Trace
from factory.contract.taxonomy import Taxonomy
from factory.llm.client import LLMClient


@dataclass
class Context:
    rng: Random
    llm: LLMClient
    browser: Browser
    taxonomy: Taxonomy
    trace: Trace
    budget: dict = field(default_factory=lambda: {"llm_usd": 0, "wall_seconds": 120})
