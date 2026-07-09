from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pdfplumber

from .formulas import equation_number, inline_math_to_latex, looks_like_display_formula
from .models import Block


CAPTION = re.compile(r"^(Fig(?:ure)?\.?|Table)\s*([A-Za-z]?\d+)", re.I)
HEADING = re.compile(r"^(?:[IVX]+\.|\d+(?:\.\d+)*\.|Appendix\s+[A-Z])\s+\S", re.I)


def _line_groups(words: list[dict], page_width: float, tolerance: float = 3.0) -> list[list[dict]]:
    lines: list[list[dict]] = []
    for word in sorted(words, key=lambda w: (round(float(w["top"]) / tolerance), float(w["x0"]))):
        for line in reversed(lines[-4:]):
            if abs(float(line[0]["top"]) - float(word["top"])) <= tolerance:
                line.append(word)
                break
        else:
            lines.append([word])
    result: list[list[dict]] = []
    for raw in lines:
        line = sorted(raw, key=lambda w: float(w["x0"]))
        gaps = [(float(line[i + 1]["x0"]) - float(line[i]["x1"]), i) for i in range(len(line) - 1)]
        split = max(gaps, default=(0.0, -1))
        if split[0] > max(18.0, page_width * 0.035):
            result.extend((line[: split[1] + 1], line[split[1] + 1 :]))
        else:
            result.append(line)
    return result


def _bbox(line: list[dict]) -> tuple[float, float, float, float]:
    return (min(w["x0"] for w in line), min(w["top"] for w in line), max(w["x1"] for w in line), max(w["bottom"] for w in line))


def _is_math_font(fontname: str) -> bool:
    lowered = fontname.lower()
    return any(marker in lowered for marker in ("newtxmi", "txsys", "txmia", "txex", "txsym", "txbsys", "cmsy", "cmmi", "math"))


def _inline_math_text(line: list[dict]) -> str:
    parts: list[str] = []
    math_run: list[str] = []

    def flush_math() -> None:
        if math_run:
            latex = inline_math_to_latex(" ".join(math_run))
            parts.append(f"${latex}$" if latex else " ".join(math_run))
            math_run.clear()

    for word in line:
        value = str(word["text"])
        if _is_math_font(str(word.get("fontname") or "")):
            math_run.append(value)
        else:
            flush_math()
            parts.append(value)
    flush_math()
    return " ".join(parts)


def extract_blocks(pdf_path: Path, max_pages: int | None = None) -> tuple[list[Block], list[tuple[float, float]], dict]:
    blocks: list[Block] = []
    sizes: list[tuple[float, float]] = []
    font_sizes: Counter[float] = Counter()
    with pdfplumber.open(pdf_path) as pdf:
        for page_number, page in enumerate(pdf.pages, 1):
            if max_pages and page_number > max_pages:
                break
            sizes.append((float(page.width), float(page.height)))
            # Physics PDFs often use tightly kerned TeX fonts. pdfplumber's default
            # x tolerance (3 pt) can merge an entire sentence into one token.
            words = page.extract_words(x_tolerance=0.5, y_tolerance=3, extra_attrs=["size", "fontname"], keep_blank_chars=False, use_text_flow=False)
            for word in words:
                if word.get("size"):
                    font_sizes[round(float(word["size"]), 1)] += 1
            preliminary = _line_groups(words, float(page.width))
            major_line = next((line for line in preliminary if HEADING.match(" ".join(str(w["text"]) for w in line).strip())), None) if page_number == 1 else None
            if major_line:
                split_y = max(float(w["bottom"]) for w in major_line)
                top_words = [w for w in words if float(w["top"]) <= split_y]
                body_words = [w for w in words if float(w["top"]) > split_y]
                left_words = [w for w in body_words if (float(w["x0"]) + float(w["x1"])) / 2 < float(page.width) / 2]
                right_words = [w for w in body_words if w not in left_words]
                lines = _line_groups(top_words, float(page.width)) + _line_groups(left_words, float(page.width) / 2) + _line_groups(right_words, float(page.width) / 2)
            else:
                left_words = [w for w in words if (float(w["x0"]) + float(w["x1"])) / 2 < float(page.width) / 2]
                right_words = [w for w in words if w not in left_words]
                lines = _line_groups(left_words, float(page.width) / 2) + _line_groups(right_words, float(page.width) / 2)
            page_blocks: list[Block] = []
            for line in lines:
                raw_text = " ".join(str(w["text"]) for w in line).strip()
                if not raw_text:
                    continue
                box = _bbox(line)
                sizes_in_line = [float(w.get("size") or 0) for w in line]
                avg_size = sum(sizes_in_line) / max(1, len(sizes_in_line))
                kind = "paragraph"
                number = None
                if looks_like_display_formula(raw_text, float(page.width), box):
                    kind, number = "formula", equation_number(raw_text)
                elif CAPTION.match(raw_text):
                    kind, number = "caption", CAPTION.match(raw_text).group(2)  # type: ignore[union-attr]
                math_fonts = sum(1 for w in line if _is_math_font(str(w.get("fontname") or "")))
                math_ratio = math_fonts / max(1, len(line))
                if kind == "paragraph" and math_ratio >= .65 and len(raw_text.split()) <= 20 and any(token in raw_text for token in ("=", "∑", "∫", "©")):
                    kind = "formula"
                mostly_text = sum(ch.isalpha() for ch in raw_text) >= 8 and math_fonts / max(1, len(line)) < .4
                if kind == "paragraph" and (HEADING.match(raw_text) or (avg_size >= 13 and len(raw_text) < 120 and mostly_text)):
                    kind = "heading"
                text = raw_text if kind == "formula" else _inline_math_text(line)
                page_blocks.append(Block(kind, page_number, box, text=text, number=number))
            for image_index, image in enumerate(page.images, 1):
                box = (float(image["x0"]), float(image["top"]), float(image["x1"]), float(image["bottom"]))
                width, height = box[2] - box[0], box[3] - box[1]
                # Ignore tiny masks, bullets, and publisher ornaments.
                if width >= 40 and height >= 40 and width * height >= float(page.width * page.height) * 0.008:
                    page_blocks.append(Block("figure", page_number, box, method="embedded-region", id=f"p{page_number}-image-{image_index}"))
            # Reading order: full-width items, then columns by vertical bands. This is conservative
            # and keeps exact provenance if a user needs to correct an unusual layout.
            major_heading = next((b for b in sorted(page_blocks, key=lambda x: x.bbox[1]) if page_number == 1 and b.kind == "heading" and re.match(r"^(?:[IVX]+|\d+)\.", b.text)), None)
            preamble = []
            if major_heading:
                preamble = [b for b in page_blocks if b.bbox[1] <= major_heading.bbox[1] + 2]
                preamble.sort(key=lambda b: (b.bbox[1], b.bbox[0]))
            body = [b for b in page_blocks if b not in preamble]
            left = [b for b in body if (b.bbox[0] + b.bbox[2]) / 2 < page.width / 2]
            right = [b for b in body if b not in left]
            left.sort(key=lambda b: (b.bbox[1], b.bbox[0]))
            right.sort(key=lambda b: (b.bbox[1], b.bbox[0]))
            ordered = preamble + left + right
            blocks.extend(ordered)
    common_size = font_sizes.most_common(1)[0][0] if font_sizes else None
    return blocks, sizes, {"common_font_size": common_size, "has_text_layer": bool(blocks)}


def clean_repeated_headers(blocks: list[Block], page_count: int) -> list[Block]:
    normalized = Counter(re.sub(r"\d+", "#", b.text.strip().lower()) for b in blocks if b.bbox[1] < 60 or b.bbox[3] > 740)
    repeated = {text for text, count in normalized.items() if count >= max(3, page_count // 3)}
    return [b for b in blocks if re.sub(r"\d+", "#", b.text.strip().lower()) not in repeated]

