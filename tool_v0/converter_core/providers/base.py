from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class ProviderConfig:
    mode: str
    base_url: str = ""
    api_key_environment_variable: str = ""
    timeout: int = 3600


class RecognitionProvider(Protocol):
    """Future boundary shared by local MinerU and hosted providers."""

    def convert(self, pdf: Path, output: Path) -> None: ...
