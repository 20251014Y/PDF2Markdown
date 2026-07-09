from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path

from .mineru import _normalize, _quality_check, referenced_figure_names


def build_clean_delivery(source: Path, destination: Path) -> None:
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError(f"Destination is not empty: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    article = (source / "article.md").read_text(encoding="utf-8")
    match = re.match(r"(---\n.*?\n---\n)\s*", article, re.S)
    frontmatter = match.group(1) + "\n" if match else ""
    raw_path = source / "diagnostics" / "mineru-raw.md"
    raw = raw_path.read_text(encoding="utf-8") if raw_path.is_file() else article[match.end():] if match else article
    removed_details = len(re.findall(r"<details>.*?</details>", raw, re.S | re.I))
    cleaned = _normalize(raw)
    errors, warnings, formula_count = _quality_check(cleaned)
    if errors:
        raise RuntimeError("Cleaned Markdown failed quality checks: " + "; ".join(errors))
    (destination / "article.md").write_text(frontmatter + cleaned, encoding="utf-8")

    image_names = referenced_figure_names(cleaned)
    source_images = source / "assets" / "figures"
    target_images = destination / "assets" / "figures"
    target_images.mkdir(parents=True, exist_ok=True)
    for name in sorted(image_names):
        image = source_images / name
        if not image.is_file():
            raise FileNotFoundError(f"Referenced image is missing: {image}")
        shutil.copy2(image, target_images / name)

    shutil.copy2(source / "metadata.yaml", destination / "metadata.yaml")
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    manifest["delivery"] = {
        "removed_generated_details": removed_details,
        "referenced_images": len(image_names),
        "display_formulas": formula_count,
        "warnings": warnings,
    }
    (destination / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    review = (source / "review.md").read_text(encoding="utf-8").rstrip()
    review += f"\n\n## 清理记录\n\n- 已移除模型生成的图表分析折叠块：{removed_details}\n- 最终正文引用图片：{len(image_names)}\n"
    (destination / "review.md").write_text(review, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a clean delivery folder from MinerU output")
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    build_clean_delivery(args.source.resolve(), args.destination.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

