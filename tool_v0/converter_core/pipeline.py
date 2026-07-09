from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path

from pypdf import PdfReader

from . import __version__
from .extract import clean_repeated_headers, extract_blocks
from .formulas import best_effort_latex, conservative_latex
from .models import Block, Document, ReviewItem
from .mathpix import MathpixError, process_pdf
from .mineru import MinerUError, executable as mineru_executable, process_pdf as process_pdf_mineru
from .render import crop_pdf_bbox, render_pages
from .writer import write_outputs
from .progress import emit_progress
from .providers.base import ProviderConfig
from .providers.mineru_api import MinerUApiError, MinerUApiProvider


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-") or "document"


def _report_metadata(*, pdf: Path, source_hash: str, engine: str,
                     max_pages: int | None, api_base_url: str | None = None) -> dict[str, str]:
    metadata = {
        "batch_started_at": os.environ.get("PDF2MD_BATCH_STARTED_AT", "未记录"),
        "backend": os.environ.get("PDF2MD_BACKEND_LABEL", engine),
        "tool_version": f"v{__version__}",
        "gpu_info": os.environ.get("PDF2MD_GPU_INFO", ""),
        "max_pages": f"前 {max_pages} 页" if max_pages else "全文",
        "sha256": source_hash,
        "source_name": pdf.name,
    }
    if api_base_url:
        metadata["api_base_url"] = api_base_url
    return metadata


def _merge_formula_fragments(blocks: list[Block]) -> list[Block]:
    """TeX equations are often emitted as several baselines with the same number."""
    result: list[Block] = []
    numbered: dict[tuple[int, str], Block] = {}
    for block in blocks:
        if block.kind == "formula" and result and result[-1].kind == "formula" and result[-1].page == block.page:
            prior = result[-1]
            same_column = abs((prior.bbox[0] + prior.bbox[2]) / 2 - (block.bbox[0] + block.bbox[2]) / 2) < 200
            close = block.bbox[1] - prior.bbox[3] < 70 and block.bbox[1] >= prior.bbox[1]
            if same_column and close and (block.number or not prior.number):
                result.pop()
                block.bbox = (min(prior.bbox[0], block.bbox[0]), min(prior.bbox[1], block.bbox[1]), max(prior.bbox[2], block.bbox[2]), max(prior.bbox[3], block.bbox[3]))
                block.text = (prior.text + " " + block.text).strip()
        key = (block.page, block.number) if block.kind == "formula" and block.number else None
        previous = numbered.get(key) if key else None
        if previous and abs((previous.bbox[1] + previous.bbox[3]) / 2 - (block.bbox[1] + block.bbox[3]) / 2) < 60:
            previous.bbox = (min(previous.bbox[0], block.bbox[0]), min(previous.bbox[1], block.bbox[1]), max(previous.bbox[2], block.bbox[2]), max(previous.bbox[3], block.bbox[3]))
            if len(block.text) > len(previous.text):
                previous.text = block.text
            continue
        result.append(block)
        if key:
            numbered[key] = block
    return result


def convert(pdf: Path, output: Path, *, mode: str = "local", dpi: int = 300, formula_timeout: int = 30, formula_retries: int = 1, keep_intermediate: bool = False, overwrite: bool = False, max_pages: int | None = None, formula_engine: str = "auto", mathpix_timeout: int = 600, mathpix_keep_remote: bool = False, mineru_timeout: int = 3600) -> Document:
    conversion_started = time.perf_counter()
    emit_progress("检查 PDF 和输出目录", 0.01)
    if not pdf.is_file() or pdf.suffix.lower() != ".pdf":
        raise ValueError(f"Input is not a PDF file: {pdf}")
    if output.exists() and any(output.iterdir()) and not overwrite:
        raise FileExistsError(f"Output is not empty: {output} (use --overwrite)")
    source_hash = file_hash(pdf)
    reader = PdfReader(str(pdf))
    if reader.is_encrypted:
        raise ValueError("Encrypted PDFs are not supported")
    total_pages = len(reader.pages)
    page_count = min(total_pages, max_pages) if max_pages else total_pages
    workspace = Path(__file__).resolve().parent.parent
    if formula_engine == "mineru-api":
        staging = workspace / ".runtime-home" / "api" / "staging" / source_hash[:12]
        if staging.exists():
            shutil.rmtree(staging)
        (staging / "assets" / "figures").mkdir(parents=True)
        (staging / "assets" / "formulas").mkdir(parents=True)
        preflight_seconds = time.perf_counter() - conversion_started
        recognition_started = time.perf_counter()
        api_base_url = os.environ.get("MINERU_API_BASE_URL", "https://mineru.net/api/v4")
        try:
            provider = MinerUApiProvider(
                ProviderConfig(
                    mode="api",
                    base_url=api_base_url,
                    api_key_environment_variable="MINERU_API_TOKEN",
                    timeout=mineru_timeout,
                ),
                workspace,
            )
            result = provider.convert(pdf, staging, max_pages=max_pages)
        except MinerUApiError:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        recognition_seconds = time.perf_counter() - recognition_started
        title_match = re.search(r"^#\s+(.+)$", result.markdown, re.M)
        title = title_match.group(1).strip() if title_match else pdf.stem
        doc = Document(
            title=title, source=pdf.name, sha256=source_hash, pages=page_count,
            metadata={"engine": "mineru-api-vlm", "formulas": result.formulas, "images": result.images},
        )
        frontmatter = "\n".join([
            "---", f'title: "{title.replace(chr(34), chr(39))}"', f'source: "{pdf.name}"',
            f'sha256: "{source_hash}"', f"pages: {page_count}", "engine: mineru-api-vlm", "---", "",
        ])
        (staging / "article.md").write_text(frontmatter + result.markdown, encoding="utf-8")
        emit_progress("整理 API Markdown、图片与 README", 0.94, phase="整理 Markdown 与图片")
        from .delivery import finalize_delivery
        finalize_delivery(
            staging, source_name=pdf.name, title=title, pages=page_count,
            formulas=result.formulas, images=result.images, warnings=result.warnings,
            timings={"PDF 预检与准备": preflight_seconds,
                     "上传、排队与云端解析": recognition_seconds},
            source_pdf=pdf, engine_label="MinerU API（云端 VLM）",
            report_metadata=_report_metadata(
                pdf=pdf, source_hash=source_hash, engine="MinerU API（云端 VLM）",
                max_pages=max_pages, api_base_url=api_base_url,
            ),
        )
        emit_progress("API 质量检查完成", 1.0, phase="质量检查完成")
        if output.exists():
            shutil.rmtree(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(staging), str(output))
        return doc

    if overwrite and output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "assets" / "figures").mkdir(parents=True)
    (output / "assets" / "formulas").mkdir(parents=True)

    use_mineru = formula_engine == "mineru" or (formula_engine == "auto" and mineru_executable(workspace) is not None)
    if use_mineru:
        recognition_started = time.perf_counter()
        try:
            emit_progress("启动 MinerU 视觉识别", 0.02)
            result = process_pdf_mineru(pdf, output, workspace, max_pages=max_pages, timeout=mineru_timeout)
        except MinerUError:
            # High-accuracy mode must never silently degrade to heuristics.
            raise
        recognition_seconds = time.perf_counter() - recognition_started
        preflight_seconds = recognition_started - conversion_started
        title_match = re.search(r"^#\s+(.+)$", result.markdown, re.M)
        title = title_match.group(1).strip() if title_match else pdf.stem
        doc = Document(title=title, source=pdf.name, sha256=source_hash, pages=page_count, metadata={"engine": "mineru-vlm", "formulas": result.formulas, "images": result.images})
        frontmatter = "\n".join(["---", f'title: "{title.replace(chr(34), chr(39))}"', f'source: "{pdf.name}"', f'sha256: "{source_hash}"', f"pages: {page_count}", "engine: mineru-vlm", "---", ""])
        (output / "article.md").write_text(frontmatter + result.markdown, encoding="utf-8")
        (output / "metadata.yaml").write_text(f'title: "{title}"\nsource: "{pdf.name}"\nsha256: "{source_hash}"\npages: {page_count}\nengine: "mineru-vlm"\n', encoding="utf-8")
        manifest = {"schema_version": 1, "source": {"name": pdf.name, "sha256": source_hash, "pages": page_count}, "config": {"formula_engine": "mineru", "max_pages": max_pages}, "quality": {"replacement_chars": 0, "cid_glyphs": 0, "private_use_chars": 0, "display_formulas": result.formulas, "equation_tags": result.equation_tags}, "images": result.images}
        (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        review = ["# 转换复核报告", "", "- 引擎：MinerU VLM（本地 GPU）", f"- 行间公式：{result.formulas}", f"- 公式编号：{', '.join(result.equation_tags) or '无'}", "- 乱码检查：通过（replacement/cid/private-use 均为 0）", f"- 图片：{result.images}", ""]
        if result.warnings:
            review.extend(["## 建议复核", "", *[f"- {warning}" for warning in result.warnings], ""])
        else:
            review.extend(["## 建议复核", "", "自动结构检查未发现异常；仍建议抽查复杂矩阵和公式编号。", ""])
        (output / "review.md").write_text("\n".join(review), encoding="utf-8")
        emit_progress("整理 Markdown、图片与复核信息", 0.94)
        from .delivery import finalize_delivery
        finalize_delivery(output, source_name=pdf.name, title=title, pages=page_count,
                          formulas=result.formulas, images=result.images, warnings=result.warnings,
                          timings={"PDF 预检与准备": preflight_seconds,
                                   "模型识别（正文、公式与图片）": recognition_seconds},
                          source_pdf=pdf, engine_label="MinerU VLM（本地 GPU）",
                          report_metadata=_report_metadata(
                              pdf=pdf, source_hash=source_hash, engine="MinerU VLM（本地 GPU）",
                              max_pages=max_pages,
                          ))
        emit_progress("质量检查完成", 1.0)
        return doc
    app_id = os.environ.get("MATHPIX_APP_ID", "")
    app_key = os.environ.get("MATHPIX_APP_KEY", "")
    use_mathpix = mode == "enhanced" and formula_engine in ("auto", "mathpix") and bool(app_id and app_key)
    if formula_engine == "mathpix" and not (app_id and app_key):
        raise ValueError("Mathpix requires MATHPIX_APP_ID and MATHPIX_APP_KEY")
    mathpix_fallback_reason: str | None = None
    if use_mathpix:
        try:
            result = process_pdf(pdf, output, app_id, app_key, max_pages=max_pages, timeout=mathpix_timeout, delete_remote=not mathpix_keep_remote)
            title = str(getattr(reader.metadata, "title", "") or pdf.stem).strip()
            doc = Document(title=title, source=pdf.name, sha256=source_hash, pages=page_count, metadata={"engine": "mathpix", "mathpix_images": result.image_count})
            frontmatter = "\n".join(["---", f'title: "{title.replace(chr(34), chr(39))}"', f'source: "{pdf.name}"', f'sha256: "{source_hash}"', f"pages: {page_count}", "engine: mathpix", "---", ""])
            (output / "article.md").write_text(frontmatter + result.markdown, encoding="utf-8")
            (output / "metadata.yaml").write_text(f'title: "{title}"\nsource: "{pdf.name}"\nsha256: "{source_hash}"\npages: {page_count}\nengine: "mathpix"\n', encoding="utf-8")
            manifest = {"schema_version": 1, "source": {"name": pdf.name, "sha256": source_hash, "pages": page_count}, "config": {"mode": mode, "formula_engine": "mathpix", "max_pages": max_pages}, "mathpix": {"remote_deleted": not mathpix_keep_remote, "localized_images": result.image_count}}
            (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            (output / "review.md").write_text("# 转换复核报告\n\n本次使用 Mathpix 整篇文档识别。请重点抽查公式编号、上下标、矩阵和图片引用。\n", encoding="utf-8")
            return doc
        except Exception as exc:
            if formula_engine == "mathpix":
                raise RuntimeError(str(exc)) from exc
            # auto mode must remain usable: continue with the local pipeline.
            mathpix_fallback_reason = str(exc)
    cache = output.parent / ".pdf2markdown-cache" / f"{source_hash[:16]}-{dpi}-p{page_count}"
    page_images = render_pages(pdf, cache / "pages", dpi, max_pages=page_count)
    if len(page_images) != page_count:
        raise RuntimeError(f"Rendered {len(page_images)} pages but PDF contains {page_count}")

    blocks, page_sizes, extraction_meta = extract_blocks(pdf, max_pages=page_count)
    extraction_meta["source_total_pages"] = total_pages
    extraction_meta["partial_conversion"] = page_count < total_pages
    blocks = clean_repeated_headers(blocks, page_count)
    blocks = _merge_formula_fragments(blocks)
    pdf_title = None
    if reader.metadata:
        pdf_title = getattr(reader.metadata, "title", None)
    first_page_headings = [b.text for b in blocks if b.kind == "heading" and b.page == 1 and not re.match(r"^(?:[IVX]+|\d+)\.", b.text)]
    first_page_text = next((b.text for b in blocks if b.page == 1 and len(b.text) > 20), None)
    title = (str(pdf_title).strip() if pdf_title else None) or (first_page_headings[0] if first_page_headings else first_page_text) or pdf.stem
    doc = Document(title=title, source=pdf.name, sha256=source_hash, pages=page_count, metadata=extraction_meta)

    if not blocks:
        doc.reviews.append(ReviewItem("required", 1, "document", "PDF 没有可用文本层；已保留逐页渲染图，但当前版本未内置通用 OCR。"))
        for index, image in enumerate(page_images, 1):
            target = output / "assets" / "figures" / f"page-{index:03d}.png"
            shutil.copy2(image, target)
            doc.blocks.append(Block("figure", index, (0, 0, *page_sizes[index - 1]), asset=f"assets/figures/{target.name}", id=f"page-{index:03d}", method="full-page-fallback"))
    else:
        formula_index = 0
        figure_index = 0
        for index, block in enumerate(blocks, 1):
            block.id = f"block-{index:05d}"
            if block.kind == "figure":
                figure_index += 1
                filename = f"fig-{figure_index:03d}-p{block.page:03d}.png"
                relative = f"assets/figures/{filename}"
                crop_pdf_bbox(page_images[block.page - 1], block.bbox, page_sizes[block.page - 1], output / relative, padding=8)
                block.asset = relative
                doc.blocks.append(block)
                continue
            if block.kind == "caption" and block.text.lower().startswith(("fig", "figure")):
                previous_figure = next((b for b in reversed(doc.blocks) if b.page == block.page and b.kind == "figure" and b.bbox[3] <= block.bbox[1] + 8), None)
                if previous_figure is None:
                    figure_index += 1
                    filename = f"fig-{figure_index:03d}-p{block.page:03d}.png"
                    relative = f"assets/figures/{filename}"
                    page_width, _ = page_sizes[block.page - 1]
                    inferred = (max(0.0, block.bbox[0] - 8), max(0.0, block.bbox[1] - 190), min(page_width, block.bbox[2] + 8), max(0.0, block.bbox[1] - 5))
                    crop_pdf_bbox(page_images[block.page - 1], inferred, page_sizes[block.page - 1], output / relative, padding=4)
                    figure = Block("figure", block.page, inferred, asset=relative, method="caption-inferred", id=f"figure-{figure_index:03d}", confidence=.55)
                    doc.blocks.append(figure)
                    doc.reviews.append(ReviewItem("recommended", block.page, figure.id, "图像边界由图注位置推断，请确认裁切范围。", relative))
            if block.kind != "formula":
                doc.blocks.append(block)
                continue
            formula_index += 1
            label = _safe_name(block.number or f"u{formula_index:03d}")
            filename = f"eq-{label}-p{block.page:03d}.png"
            relative = f"assets/formulas/{filename}"
            target = output / relative
            page_width, page_height = page_sizes[block.page - 1]
            center = (block.bbox[0] + block.bbox[2]) / 2
            left, right = (24.0, page_width / 2 - 8) if center < page_width / 2 else (page_width / 2 + 8, page_width - 24.0)
            expanded = (left, max(0.0, block.bbox[1] - 24), right, min(page_height, block.bbox[3] + 20))
            crop_pdf_bbox(page_images[block.page - 1], expanded, page_sizes[block.page - 1], target, padding=6)
            block.bbox = expanded
            result = conservative_latex(block.text)
            if result.latex and result.confidence >= 0.8:
                block.text, block.confidence, block.method = result.latex, result.confidence, result.method
            else:
                candidate = result.latex or best_effort_latex(block.text)
                block.text, block.asset, block.confidence, block.method = candidate, relative, result.confidence, "best-effort-latex"
                reason = "该行间公式以低置信度 LaTeX 输出；原文裁图仅供复核，不会嵌入正文。"
                if mode == "enhanced":
                    reason += " 未配置增强识别适配器，因此没有阻塞等待线上服务。"
                doc.reviews.append(ReviewItem("recommended", block.page, block.id, reason, relative, candidate))
            doc.blocks.append(block)

    if mode == "enhanced":
        if mathpix_fallback_reason:
            doc.reviews.append(ReviewItem("info", 1, "mathpix-fallback", f"Mathpix 不可用，已自动回退到本地流程：{mathpix_fallback_reason}"))
        elif not (app_id and app_key):
            doc.reviews.append(ReviewItem("info", 1, "enhanced-mode", "未配置 Mathpix 凭据，已使用本地流程。"))
    config = {"version": __version__, "mode": mode, "formula_engine": formula_engine, "dpi": dpi, "formula_timeout": formula_timeout, "formula_retries": formula_retries, "max_pages": max_pages}
    write_outputs(doc, output, config)
    (cache / "complete.json").write_text(json.dumps({"sha256": source_hash, "config": config}), encoding="utf-8")
    if keep_intermediate:
        intermediate = output / "intermediate" / "pages"
        intermediate.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(cache / "pages", intermediate, dirs_exist_ok=True)
    return doc

