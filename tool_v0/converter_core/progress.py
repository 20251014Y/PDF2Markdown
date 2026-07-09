from __future__ import annotations

import json
import os
from pathlib import Path


def emit_progress(stage: str, fraction: float, **details: object) -> None:
    """Publish machine-readable progress for the friendly batch launcher."""
    target = os.environ.get("PDF2MD_PROGRESS_FILE")
    if not target:
        return
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"stage": stage, "fraction": max(0.0, min(1.0, float(fraction))), **details}
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

