from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from PIL import Image


def find_pdftoppm() -> str:
    found = shutil.which("pdftoppm") or shutil.which("pdftoppm.cmd")
    if not found:
        raise RuntimeError("pdftoppm is required but was not found on PATH")
    candidate = Path(found).resolve()
    if candidate.suffix.lower() == ".cmd":
        # The bundled Windows shim can lag behind the runtime's actual Conda layout.
        native_exe = candidate.parent.parent / "native" / "poppler" / "Library" / "bin" / "pdftoppm.exe"
        if native_exe.is_file():
            return str(native_exe)
    return found


def render_pages(pdf: Path, target: Path, dpi: int, max_pages: int | None = None) -> list[Path]:
    target.mkdir(parents=True, exist_ok=True)
    existing = sorted(target.glob("page-*.png"))
    if existing:
        return existing
    prefix = target / "page"
    command = [find_pdftoppm(), "-png", "-r", str(dpi)]
    if max_pages:
        command.extend(["-f", "1", "-l", str(max_pages)])
    command.extend([str(pdf), str(prefix)])
    completed = subprocess.run(command, capture_output=True, text=True, timeout=900)
    if completed.returncode:
        raise RuntimeError(f"Page rendering failed: {completed.stderr.strip()}")
    rendered = sorted(target.glob("page-*.png"))
    if not rendered:
        raise RuntimeError("Page rendering produced no images")
    return rendered


def crop_pdf_bbox(page_image: Path, bbox: tuple[float, float, float, float], page_size: tuple[float, float], output: Path, padding: int = 8) -> None:
    with Image.open(page_image) as image:
        sx, sy = image.width / page_size[0], image.height / page_size[1]
        left = max(0, int(bbox[0] * sx) - padding)
        top = max(0, int(bbox[1] * sy) - padding)
        right = min(image.width, int(bbox[2] * sx) + padding)
        bottom = min(image.height, int(bbox[3] * sy) + padding)
        output.parent.mkdir(parents=True, exist_ok=True)
        image.crop((left, top, right, bottom)).save(output, "PNG", optimize=True)

