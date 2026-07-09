from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path

from pypdf import PdfReader

from .mineru import _normalize, _quality_check, referenced_figure_names


def recover(pdf: Path, output: Path) -> None:
    raw_path = output / "diagnostics" / "mineru-raw.md"
    if not raw_path.is_file():
        raise FileNotFoundError(f"Missing completed MinerU result: {raw_path}")
    markdown = _normalize(raw_path.read_text(encoding="utf-8"))
    errors, warnings, formula_count = _quality_check(markdown)
    if errors:
        raise RuntimeError("Fatal encoding/delimiter errors: " + "; ".join(errors))

    workspace = Path(__file__).resolve().parent.parent
    work_key = hashlib.sha256(str(pdf.resolve()).encode("utf-8")).hexdigest()[:12]
    run_dir = workspace / ".runtime-home" / "mineru-work" / work_key
    markdown_files = list(run_dir.rglob("*.md"))
    if not markdown_files:
        raise FileNotFoundError(f"Missing MinerU work product: {run_dir}")
    image_source = markdown_files[0].parent / "images"
    image_target = output / "assets" / "figures"
    image_target.mkdir(parents=True, exist_ok=True)
    referenced = referenced_figure_names(markdown)
    copied = 0
    for name in referenced:
        source = image_source / name
        if source.is_file():
            shutil.copy2(source, image_target / name)
            copied += 1

    digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
    pages = len(PdfReader(str(pdf)).pages)
    title_match = re.search(r"^#\s+(.+)$", markdown, re.M)
    title = title_match.group(1).strip() if title_match else pdf.stem
    frontmatter = "\n".join([
        "---", f'title: "{title.replace(chr(34), chr(39))}"',
        f'source: "{pdf.name}"', f'sha256: "{digest}"',
        f"pages: {pages}", "engine: mineru-vlm", "---", "",
    ])
    (output / "article.md").write_text(frontmatter + markdown, encoding="utf-8")
    (output / "metadata.yaml").write_text(
        f'title: "{title}"\nsource: "{pdf.name}"\nsha256: "{digest}"\npages: {pages}\nengine: "mineru-vlm"\n',
        encoding="utf-8",
    )
    tags = re.findall(r"\\tag\s*\{\s*([^}]+?)\s*\}", markdown)
    manifest = {
        "schema_version": 1,
        "source": {"name": pdf.name, "sha256": digest, "pages": pages},
        "config": {"formula_engine": "mineru", "recovered_from_completed_ocr": True},
        "quality": {"replacement_chars": 0, "cid_glyphs": 0, "private_use_chars": 0,
                    "display_formulas": formula_count, "equation_tags": tags},
        "images": copied,
    }
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    review = [
        "# 转换复核报告", "", "- 引擎：MinerU VLM（本地 GPU）",
        f"- 行间公式：{formula_count}", f"- 图片：{copied}",
        "- 乱码检查：通过（replacement/cid/private-use 均为 0）", "",
        "## 建议复核", "",
    ]
    review.extend([f"- {warning}" for warning in warnings] or ["- 自动结构检查未发现异常。"])
    review.append("")
    (output / "review.md").write_text("\n".join(review), encoding="utf-8")
    from .delivery import finalize_delivery
    finalize_delivery(output, source_name=pdf.name, title=title, pages=pages,
                      formulas=formula_count, images=copied, warnings=warnings,
                      source_pdf=pdf)


def main() -> int:
    parser = argparse.ArgumentParser(description="Finish a conversion from completed MinerU OCR output")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    recover(args.pdf.resolve(), args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

