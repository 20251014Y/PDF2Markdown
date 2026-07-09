"""Recognition-provider boundary reserved for local and hosted deployments."""

from .base import ProviderConfig, RecognitionProvider
from .mineru_api import MinerUApiProvider

__all__ = ["ProviderConfig", "RecognitionProvider", "MinerUApiProvider"]
