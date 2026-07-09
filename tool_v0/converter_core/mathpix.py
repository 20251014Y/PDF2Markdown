from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import requests
except ImportError:  # Mathpix is optional; local conversion must still start.
    requests = None  # type: ignore[assignment]


API_ROOT = "https://api.mathpix.com/v3/pdf"


class MathpixError(RuntimeError):
    pass


@dataclass
class MathpixResult:
    markdown: str
    pdf_id: str
    image_count: int


def normalize_mmd(markdown: str) -> str:
    """Normalize Mathpix math delimiters for Obsidian MathJax."""
    markdown = re.sub(r"\\\[\s*", "\n$$\n", markdown)
    markdown = re.sub(r"\s*\\\]", "\n$$\n", markdown)
    markdown = re.sub(r"\\\(\s*", "$", markdown)
    markdown = re.sub(r"\s*\\\)", "$", markdown)
    markdown = re.sub(r"\n{3,}", "\n\n", markdown)
    return markdown.strip() + "\n"


def _localize_images(markdown: str, output: Path, session: Any, timeout: int) -> tuple[str, int]:
    pattern = re.compile(r"!\[([^]]*)\]\((https://[^)]+)\)")
    count = 0
    replacements: dict[str, str] = {}
    for match in pattern.finditer(markdown):
        url = match.group(2)
        if url in replacements:
            continue
        response = session.get(url, timeout=min(timeout, 60))
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        suffix = ".jpg" if "jpeg" in content_type else ".png"
        count += 1
        relative = f"assets/figures/mathpix-{count:03d}{suffix}"
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(response.content)
        replacements[url] = relative
    for url, relative in replacements.items():
        markdown = markdown.replace(f"]({url})", f"]({relative})")
    return markdown, count


def process_pdf(pdf: Path, output: Path, app_id: str, app_key: str, *, max_pages: int | None = None, timeout: int = 600, delete_remote: bool = True, session: Any = None) -> MathpixResult:
    if requests is None and session is None:
        raise MathpixError("Mathpix support requires the 'requests' package; install the project dependencies first")
    client = session or requests.Session()
    headers = {"app_id": app_id, "app_key": app_key}
    options: dict[str, object] = {
        "math_inline_delimiters": ["$", "$"],
        "rm_spaces": True,
        "metadata": {"improve_mathpix": False},
    }
    if max_pages:
        options["page_ranges"] = f"1-{max_pages}"
    with pdf.open("rb") as stream:
        response = client.post(API_ROOT, headers=headers, files={"file": (pdf.name, stream, "application/pdf")}, data={"options_json": json.dumps(options)}, timeout=min(timeout, 120))
    if response.status_code >= 400:
        raise MathpixError(f"Mathpix submission failed ({response.status_code}): {response.text[:300]}")
    pdf_id = response.json().get("pdf_id")
    if not pdf_id:
        raise MathpixError("Mathpix response did not contain pdf_id")
    deadline = time.monotonic() + timeout
    try:
        while True:
            if time.monotonic() >= deadline:
                raise MathpixError(f"Mathpix processing timed out after {timeout}s")
            status_response = client.get(f"{API_ROOT}/{pdf_id}", headers=headers, timeout=30)
            status_response.raise_for_status()
            status = status_response.json()
            if status.get("status") == "completed":
                break
            if status.get("status") == "error":
                raise MathpixError(f"Mathpix processing failed: {status.get('error') or status}")
            time.sleep(3)
        result_response = client.get(f"{API_ROOT}/{pdf_id}.mmd", headers=headers, timeout=60)
        result_response.raise_for_status()
        markdown, image_count = _localize_images(result_response.text, output, client, timeout)
        return MathpixResult(normalize_mmd(markdown), pdf_id, image_count)
    finally:
        if delete_remote:
            try:
                client.delete(f"{API_ROOT}/{pdf_id}", headers=headers, timeout=30)
            except Exception:
                pass

