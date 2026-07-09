from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


BBox = tuple[float, float, float, float]


@dataclass
class Block:
    kind: str
    page: int
    bbox: BBox
    text: str = ""
    asset: str | None = None
    number: str | None = None
    confidence: float = 1.0
    method: str = "text-layer"
    id: str = ""

    def json(self) -> dict[str, Any]:
        value = asdict(self)
        value["bbox"] = [round(x, 2) for x in self.bbox]
        return value


@dataclass
class ReviewItem:
    severity: str
    page: int
    object_id: str
    reason: str
    asset: str | None = None
    candidate: str | None = None


@dataclass
class Document:
    title: str
    source: str
    sha256: str
    pages: int
    blocks: list[Block] = field(default_factory=list)
    reviews: list[ReviewItem] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


