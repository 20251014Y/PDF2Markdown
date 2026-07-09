from __future__ import annotations

import json
import re
from pathlib import Path

from .models import Document


def _yaml(value: object) -> str:
    text = str(value).replace('"', '\\"')
    return f'"{text}"'


def write_outputs(doc: Document, output: Path, config: dict) -> None:
    lines = ["---", f"title: {_yaml(doc.title)}", f"source: {_yaml(doc.source)}", f"sha256: {_yaml(doc.sha256)}", f"pages: {doc.pages}", "converter: PDF2Markdown/v0", "---", ""]
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            joined = paragraph[0]
            for part in paragraph[1:]:
                if joined.endswith("-") and part and part[0].islower():
                    joined = joined[:-1] + part
                else:
                    joined += " " + part
            lines.extend([joined, ""])
            paragraph.clear()

    for block in doc.blocks:
        if block.kind == "heading":
            flush()
            level = 2 if re.match(r"^(?:\d+\.|[IVX]+\.)", block.text) else 1
            lines.extend(["#" * level + " " + block.text, ""])
        elif block.kind == "formula":
            flush()
            anchor = block.number or block.id
            lines.extend([f'<a id="eq-{anchor}"></a>', ""])
            tag = f" \\tag{{{block.number}}}" if block.number else ""
            lines.extend(["$$", block.text + tag, "$$", ""])
        elif block.kind == "figure":
            flush()
            lines.extend([f"![[{block.asset}]]", ""])
        elif block.kind == "caption":
            flush()
            lines.extend([f"*{block.text}*", ""])
        else:
            paragraph.append(block.text)
    flush()
    (output / "article.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    metadata = {"title": doc.title, "source": doc.source, "sha256": doc.sha256, "pages": doc.pages, **doc.metadata}
    (output / "metadata.yaml").write_text("\n".join(f"{k}: {_yaml(v)}" for k, v in metadata.items()) + "\n", encoding="utf-8")
    manifest = {"schema_version": 1, "config": config, "source": metadata, "blocks": [b.json() for b in doc.blocks]}
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    review = ["# 转换复核报告", "", f"- 来源：`{doc.source}`", f"- 页数：{doc.pages}", f"- 待复核项目：{len(doc.reviews)}", ""]
    labels = {"required": "必须复核", "recommended": "建议复核", "info": "信息"}
    for severity in ("required", "recommended", "info"):
        items = [item for item in doc.reviews if item.severity == severity]
        review.extend([f"## {labels[severity]} ({len(items)})", ""])
        if not items:
            review.extend(["无。", ""])
        for item in items:
            review.append(f"- **第 {item.page} 页 · `{item.object_id}`**：{item.reason}")
            if item.asset:
                review.append(f"  - 原始区域：`{item.asset}`")
            if item.candidate:
                review.extend(["  - 候选 LaTeX：", "", "    ```latex", f"    {item.candidate}", "    ```"])
        review.append("")
    (output / "review.md").write_text("\n".join(review), encoding="utf-8")

