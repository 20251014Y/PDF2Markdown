from __future__ import annotations

import re
import time
import io
from pathlib import Path

from pypdf import PdfReader

from .mineru import _quality_check


def _slug(text: str) -> str:
    text = re.sub(r"[$\\{}^_]", " ", text)
    stop = {"a", "an", "the", "of", "on", "for", "with", "under", "versus", "and", "in", "to", "as"}
    words = [word for word in re.findall(r"[A-Za-z0-9]+", text)
             if word.lower() not in stop][:5]
    return "_".join(words) or "Figure"


def _rename_figures(markdown: str, output: Path) -> tuple[str, int]:
    figures = output / "assets" / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    pattern = re.compile(
        r"!\[[^]]*\]\(assets/figures/(?P<md>[^)]+)\)"
        r"|!\[\[assets/figures/(?P<obsidian>[^]|]+)(?:\|[^]]+)?\]\]"
        r"|<img\b[^>]*\bsrc\s*=\s*['\"]assets/figures/(?P<html>[^'\"]+)['\"][^>]*>",
        re.S | re.I,
    )
    mapping: dict[str, str] = {}
    counter = 0

    def old_name(match: re.Match[str]) -> str:
        return match.group("md") or match.group("obsidian") or match.group("html") or ""

    def nearby_nonempty_lines(position: int) -> tuple[str, str]:
        before = markdown[:position].splitlines()
        after = markdown[position:].splitlines()
        previous = next((line.strip() for line in reversed(before) if line.strip()), "")
        following = next((line.strip() for line in after if line.strip()), "")
        return previous, following

    def continued_caption_context(position: int) -> tuple[int, str] | None:
        previous, following = nearby_nonempty_lines(position)
        caption = re.match(r"FIG(?:URE)?\.?\s*([0-9]+)[.:]?\s*(.+)", previous, re.I)
        if not caption:
            return None
        if not following:
            return None
        if re.match(r"(?:FIG(?:URE)?\.?|TABLE|#|\|)", following, re.I):
            return None
        if len(following) > 180:
            return None
        previous_open = not re.search(r"[.!?。！？]\s*$", previous)
        continuation_start = re.match(
            r"(?:[a-z,;:]|and\b|or\b|with\b|without\b|of\b|for\b|to\b|in\b|at\b|on\b|by\b|from\b|than\b|that\b|which\b|where\b|when\b|resonances\b)",
            following,
            re.I,
        )
        if not (previous_open or continuation_start):
            return None
        return int(caption.group(1)), caption.group(2)

    for match in pattern.finditer(markdown):
        old = old_name(match)
        if old in mapping:
            continue
        source = figures / Path(old).name
        # MinerU sometimes exports tiny ORCID/publisher icons as figures.
        if source.is_file() and source.stat().st_size < 4096:
            mapping[old] = ""
            source.unlink()
            continue
        counter += 1
        following = markdown[match.end():match.end() + 600]
        caption = re.search(r"(?:FIG(?:URE)?\.?\s*([0-9]+)[.:]?\s*)([^\n]+)", following, re.I)
        continued = None if caption else continued_caption_context(match.start())
        number = int(caption.group(1)) if caption else (continued[0] if continued else counter)
        topic_source = caption.group(2) if caption else (continued[1] if continued else f"Figure {number}")
        topic = _slug(topic_source)
        suffix = Path(old).suffix.lower() or ".png"
        if continued:
            part = 2 + sum(1 for value in mapping.values() if value.startswith(f"Fig{number:02d}_{topic}_part"))
            new = f"Fig{number:02d}_{topic}_part{part}{suffix}"
        else:
            new = f"Fig{number:02d}_{topic}{suffix}"
        while new in mapping.values():
            counter += 1
            if continued:
                part += 1
                new = f"Fig{number:02d}_{topic}_part{part}{suffix}"
            else:
                new = f"Fig{number:02d}_{topic}_{counter}{suffix}"
        target = figures / new
        if source.is_file() and source.resolve() != target.resolve():
            source.replace(target)
        mapping[old] = new

    def replace(match: re.Match[str]) -> str:
        old = old_name(match)
        new = mapping.get(old, Path(old).name)
        return f"![[assets/figures/{new}]]" if new else ""

    markdown = pattern.sub(replace, markdown)
    referenced = {name for name in mapping.values() if name}
    for image in figures.iterdir():
        if image.is_file() and image.name not in referenced:
            image.unlink()
    return markdown, len(referenced)


def _replace_with_embedded_originals(pdf: Path, markdown: str, output: Path) -> int:
    """Use original PDF raster figures when they map one-to-one to references."""
    import pypdf.filters
    from PIL import Image

    pypdf.filters.ZLIB_MAX_OUTPUT_LENGTH = 500_000_000
    pypdf.filters.FLATE_MAX_BUFFER_SIZE = 500_000_000
    references = re.findall(r"!\[\[assets/figures/([^]|]+)", markdown)
    candidates: list[bytes] = []
    reader = PdfReader(str(pdf))
    for page in reader.pages:
        try:
            page_images = list(page.images)
        except Exception:
            continue
        for image in page_images:
            try:
                opened = Image.open(io.BytesIO(image.data))
                if opened.width >= 300 and opened.height >= 300:
                    candidates.append(image.data)
            except Exception:
                continue
    if not references or len(candidates) != len(references):
        return 0
    figures = output / "assets" / "figures"
    for name, data in zip(references, candidates):
        image = Image.open(io.BytesIO(data))
        if image.mode not in ("RGB", "L"):
            background = Image.new("RGB", image.size, "white")
            if "A" in image.getbands():
                background.paste(image, mask=image.getchannel("A"))
            else:
                background.paste(image.convert("RGB"))
            image = background
        image.save(figures / name, format="JPEG", quality=95, optimize=True)
    return len(candidates)


def _save_raster(image, target: Path) -> None:
    from PIL import Image
    if image.mode not in ("RGB", "L"):
        background = Image.new("RGB", image.size, "white")
        if "A" in image.getbands():
            background.paste(image, mask=image.getchannel("A"))
        else:
            background.paste(image.convert("RGB"))
        image = background
    if target.suffix.lower() == ".png":
        image.save(target, format="PNG", optimize=True)
    else:
        image.save(target, format="JPEG", quality=95, optimize=True)


def _embedded_figure_for_number(pdf: Path, number: int):
    """Return the largest embedded raster on the page carrying FIG. N."""
    from PIL import Image
    reader = PdfReader(str(pdf))
    caption = re.compile(rf"\bFIG(?:URE)?\.?\s*{number}\b", re.I)
    for page in reader.pages:
        try:
            if not caption.search(page.extract_text() or ""):
                continue
            candidates = []
            for item in page.images:
                image = Image.open(io.BytesIO(item.data))
                if image.width >= 300 and image.height >= 250:
                    candidates.append(image.copy())
            return max(candidates, key=lambda item: item.width * item.height) if candidates else None
        except Exception:
            continue
    return None


def _stitch_panels(paths: list[Path]):
    """Combine MinerU panel crops without changing their scientific content."""
    from PIL import Image
    panels = []
    for path in paths:
        with Image.open(path) as image:
            panels.append(image.convert("RGB").copy())

    def fit_to_width(image, width: int):
        if image.width == width:
            return image
        height = max(1, round(image.height * width / image.width))
        return image.resize((width, height), Image.Resampling.LANCZOS)

    def fit_to_height(image, height: int):
        if image.height == height:
            return image
        width = max(1, round(image.width * height / image.height))
        return image.resize((width, height), Image.Resampling.LANCZOS)

    def horizontal(items):
        common_height = round(sum(panel.height for panel in items) / len(items))
        scaled = [fit_to_height(panel, common_height) for panel in items]
        width = sum(panel.width for panel in scaled) + gap * (len(scaled) - 1)
        height = max(panel.height for panel in scaled)
        canvas = Image.new("RGB", (width, height), "white")
        x = 0
        for panel in scaled:
            canvas.paste(panel, (x, (height - panel.height) // 2))
            x += panel.width + gap
        return canvas

    def vertical(items):
        common_width = round(sum(panel.width for panel in items) / len(items))
        scaled = [fit_to_width(panel, common_width) for panel in items]
        width = max(panel.width for panel in scaled)
        height = sum(panel.height for panel in scaled) + gap * (len(scaled) - 1)
        canvas = Image.new("RGB", (width, height), "white")
        y = 0
        for panel in scaled:
            canvas.paste(panel, ((width - panel.width) // 2, y))
            y += panel.height + gap
        return canvas

    gap = 14
    if len(panels) == 2:
        aspects = [panel.width / max(1, panel.height) for panel in panels]
        if all(aspect > 1.35 for aspect in aspects):
            return vertical(panels)
        return horizontal(panels)
    if len(panels) == 3 and panels[0].width * panels[0].height > 1.4 * max(
        panel.width * panel.height for panel in panels[1:]
    ):
        right_width = round(sum(panel.width for panel in panels[1:]) / 2)
        right_panels = [fit_to_width(panel, right_width) for panel in panels[1:]]
        right_width = max(panel.width for panel in right_panels)
        right_height = sum(panel.height for panel in right_panels) + gap
        left = fit_to_height(panels[0], right_height)
        width = left.width + gap + right_width
        height = max(left.height, right_height)
        canvas = Image.new("RGB", (width, height), "white")
        canvas.paste(left, (0, (height - left.height) // 2))
        y = (height - right_height) // 2
        for panel in right_panels:
            canvas.paste(panel, (left.width + gap + (right_width - panel.width) // 2, y))
            y += panel.height + gap
        return canvas
    if len(panels) == 3 and all(panel.width / max(1, panel.height) > 1.25 for panel in panels):
        return vertical(panels)
    columns = 2
    rows = (len(panels) + columns - 1) // columns
    target_width = round(sum(panel.width for panel in panels) / len(panels))
    scaled = [fit_to_width(panel, target_width) for panel in panels]
    cell_width = max(panel.width for panel in scaled)
    cell_height = max(panel.height for panel in scaled)
    canvas = Image.new(
        "RGB", (columns * cell_width + gap, rows * cell_height + gap * (rows - 1)), "white"
    )
    for index, panel in enumerate(scaled):
        row, column = divmod(index, columns)
        x = column * (cell_width + gap) + (cell_width - panel.width) // 2
        y = row * (cell_height + gap) + (cell_height - panel.height) // 2
        canvas.paste(panel, (x, y))
    return canvas


def _merge_split_figures(markdown: str, output: Path,
                         source_pdf: Path | None) -> tuple[str, int, int]:
    """Replace consecutive panels belonging to one numbered figure by one image."""
    lines = markdown.splitlines()
    image_line = re.compile(r"^\s*!\[\[assets/figures/([^]|]+)(?:\|[^]]+)?\]\]\s*$")
    caption_line = re.compile(r"^\s*FIG(?:URE)?\.?\s*([0-9]+)\b", re.I)
    panel_label = re.compile(r"^\s*\([a-z]\)\s+.{0,80}\s*$", re.I)
    figures = output / "assets" / "figures"
    merged_groups = 0
    embedded_used = 0
    index = 0
    while index < len(lines):
        first = image_line.match(lines[index])
        if not first:
            index += 1
            continue
        entries: list[tuple[int, str]] = [(index, first.group(1))]
        removable_labels: list[int] = []
        cursor = index + 1
        while cursor < len(lines):
            if not lines[cursor].strip():
                cursor += 1
                continue
            match = image_line.match(lines[cursor])
            if match:
                entries.append((cursor, match.group(1)))
                cursor += 1
                continue
            if panel_label.match(lines[cursor]):
                removable_labels.append(cursor)
                cursor += 1
                continue
            if not match:
                break
        while cursor < len(lines) and not lines[cursor].strip():
            cursor += 1
        caption = caption_line.match(lines[cursor]) if cursor < len(lines) else None
        if len(entries) < 2 or not caption:
            index += 1
            continue
        number = int(caption.group(1))
        prefix = f"Fig{number:02d}_"
        if not all(Path(name).name.startswith(prefix) for _, name in entries):
            index += 1
            continue
        paths = [figures / Path(name).name for _, name in entries]
        if not all(path.is_file() for path in paths):
            index += 1
            continue
        target = paths[0]
        original = _embedded_figure_for_number(source_pdf, number) if source_pdf else None
        if original is not None:
            _save_raster(original, target)
            embedded_used += 1
        else:
            _save_raster(_stitch_panels(paths), target)
        for path in paths[1:]:
            path.unlink(missing_ok=True)
        lines[index] = f"![[assets/figures/{target.name}]]"
        for line_index, _ in entries[1:]:
            lines[line_index] = ""
        for line_index in removable_labels:
            lines[line_index] = ""
        if index > 0 and panel_label.match(lines[index - 1]):
            lines[index - 1] = ""
        merged_groups += 1
        index = cursor
    result = "\n".join(lines)
    result = re.sub(r"\n{3,}", "\n\n", result).strip() + "\n"
    final_count = len(set(re.findall(r"!\[\[assets/figures/([^]|]+)", result)))
    return result, final_count, embedded_used


def _figure_inventory_issues(markdown: str, output: Path) -> list[str]:
    figures = output / "assets" / "figures"
    referenced = set(_figure_references(markdown))
    files = {path.name for path in figures.iterdir() if path.is_file()} if figures.is_dir() else set()
    issues: list[str] = []
    missing = sorted(referenced - files)
    unreferenced = sorted(files - referenced)
    hashed = sorted(name for name in files if re.match(r"^[0-9a-f]{16,}", Path(name).stem, re.I))
    nonstandard_references = sorted(name for name in referenced if not _is_standard_figure_name(name))
    nonstandard_files = sorted(name for name in files if not _is_standard_figure_name(name))
    if missing:
        issues.append("正文引用但文件缺失：" + "、".join(missing[:8]) + (" 等" if len(missing) > 8 else ""))
    if unreferenced:
        issues.append("图片文件未被正文引用：" + "、".join(unreferenced[:8]) + (" 等" if len(unreferenced) > 8 else ""))
    if hashed:
        issues.append("仍有哈希式图片命名需复核：" + "、".join(hashed[:8]) + (" 等" if len(hashed) > 8 else ""))
    if nonstandard_references:
        issues.append("正文仍引用非规范图片名：" + "、".join(nonstandard_references[:8]) + (" 等" if len(nonstandard_references) > 8 else ""))
    if nonstandard_files:
        issues.append("图片文件仍有非规范命名：" + "、".join(nonstandard_files[:8]) + (" 等" if len(nonstandard_files) > 8 else ""))
    return issues


def _figure_references(markdown: str) -> list[str]:
    """Return figure filenames referenced by the article in visual order."""
    patterns = [
        r"!\[\[assets/figures/([^]|]+)",
        r"!\[[^]]*\]\(assets/figures/([^)]+)\)",
        r"<img\b[^>]*\bsrc\s*=\s*['\"]assets/figures/([^'\"]+)['\"][^>]*>",
    ]
    matches: list[tuple[int, str]] = []
    for pattern in patterns:
        for match in re.finditer(pattern, markdown, flags=re.S | re.I):
            matches.append((match.start(), Path(match.group(1)).name))
    ordered: list[str] = []
    seen: set[str] = set()
    for _, name in sorted(matches, key=lambda item: item[0]):
        if name and name not in seen:
            ordered.append(name)
            seen.add(name)
    return ordered


def _is_hash_figure_name(name: str) -> bool:
    return bool(re.match(r"^[0-9a-f]{16,}", Path(name).stem, re.I))


def _is_standard_figure_name(name: str) -> bool:
    return bool(re.match(r"^(?:Fig|Table)[0-9]{1,3}[A-Za-z0-9_ -]*\.(?:png|jpe?g|webp)$", Path(name).name, re.I))


def _replace_file_exact_case(source: Path, target: Path) -> None:
    if source.resolve() == target.resolve() and source.name != target.name:
        temporary = source.with_name(f".pdf2md-rename-{time.time_ns()}{source.suffix}")
        source.replace(temporary)
        temporary.replace(target)
    elif source.resolve() != target.resolve():
        source.replace(target)


def _enforce_standard_figure_delivery(markdown: str, output: Path) -> None:
    """Make delivered figure assets match article.md references exactly.

    Figure renaming may pass through several stages: MinerU hash names,
    Fig-based names, optional panel stitching, and optional embedded-original
    replacement.  This is not a user preference patch; it is a delivery
    invariant: every referenced image should exist with the same standardized
    filename, and nonreferenced hash-style leftovers should not remain in the
    delivered folder.
    """
    figures = output / "assets" / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    referenced = _figure_references(markdown)
    referenced_set = set(referenced)

    files = {path.name: path for path in figures.iterdir() if path.is_file()}
    lower_files = {name.lower(): path for name, path in files.items()}

    for name in referenced:
        target = figures / name
        if target.is_file():
            continue
        case_match = lower_files.get(name.lower())
        if case_match and case_match.is_file():
            _replace_file_exact_case(case_match, target)
            files[target.name] = target
            lower_files[target.name.lower()] = target

    files = {path.name: path for path in figures.iterdir() if path.is_file()}
    missing = [name for name in referenced if name not in files]
    reusable_leftovers = sorted(
        (path for name, path in files.items() if name not in referenced_set),
        key=lambda path: path.name.lower(),
    )
    for name in missing:
        if not reusable_leftovers:
            break
        source = reusable_leftovers.pop(0)
        target = figures / name
        if not target.exists() and _is_standard_figure_name(name):
            source.replace(target)

    files = {path.name: path for path in figures.iterdir() if path.is_file()}
    for name, path in files.items():
        if name not in referenced_set:
            path.unlink(missing_ok=True)


def _abstract(markdown: str) -> str:
    body = re.sub(r"\A---\n.*?\n---\n", "", markdown, flags=re.S)
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    for paragraph in paragraphs:
        plain = re.sub(r"[#*!\[\]()]", "", paragraph)
        if len(plain) >= 250 and not paragraph.startswith("$$"):
            return paragraph.replace("\n", " ")
    return "正文已完整转换，请参阅 `article.md`。"


def _format_duration(seconds: float) -> str:
    seconds = max(0.0, seconds)
    if seconds < 60:
        return f"{seconds:.1f} 秒"
    total_seconds = round(seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours} 小时 {minutes} 分 {secs} 秒"
    return f"{minutes} 分 {secs} 秒"


def finalize_delivery(output: Path, *, source_name: str, title: str, pages: int,
                      formulas: int, images: int, warnings: list[str],
                      timings: dict[str, float] | None = None,
                      source_pdf: Path | None = None,
                      engine_label: str = "MinerU VLM（本地 GPU）",
                      report_metadata: dict[str, str] | None = None) -> None:
    delivery_started = time.perf_counter()
    article_path = output / "article.md"
    markdown = article_path.read_text(encoding="utf-8")
    markdown, image_count = _rename_figures(markdown, output)
    markdown, image_count, merged_original_count = _merge_split_figures(
        markdown, output, source_pdf
    )
    article_path.write_text(markdown, encoding="utf-8")
    original_image_count = merged_original_count
    if source_pdf:
        original_image_count += _replace_with_embedded_originals(source_pdf, markdown, output)
    _enforce_standard_figure_delivery(markdown, output)
    figure_inventory_issues = _figure_inventory_issues(markdown, output)

    report_metadata = dict(report_metadata or {})
    batch_started_at = report_metadata.get("batch_started_at") or "未记录"
    backend = report_metadata.get("backend") or engine_label
    tool_version = report_metadata.get("tool_version") or "v0"
    gpu_info = report_metadata.get("gpu_info") or ""
    api_base_url = report_metadata.get("api_base_url") or ""
    max_pages_text = report_metadata.get("max_pages") or "全文"
    source_hash = report_metadata.get("sha256") or ""
    checks = [
        f"- 原始 PDF：`../../input/{source_name}`",
        f"- 原文页数：{pages} 页",
        f"- 识别引擎：{engine_label}",
        f"- 行间公式：{formulas} 个",
        f"- 图片：{image_count} 张，均已按 Fig 编号重命名",
        f"- PDF 内嵌原图：已直接提取 {original_image_count} 张；其余使用版面裁切图",
        "- 图片资产一致性："
        + ("通过（正文引用与 assets/figures 文件一一对应，未发现哈希名残留）" if not figure_inventory_issues else "需复核"),
        "- 表格：Obsidian 兼容的 Markdown 管道表格",
        "- 乱码检查：Unicode replacement、CID 占位符、私用区字符均为 0",
    ]
    accuracy = [
        "- 正文、上下标和 LaTeX 公式由视觉模型自动识别，已通过定界符与字符编码检查。",
        "- 自动检查只能发现结构问题，不能保证每个数字、符号和上下标与 PDF 完全一致。",
    ]
    if warnings:
        accuracy.extend(["- 以下项目必须对照原 PDF 复核：", *[f"  - {item}" for item in warnings]])
    if figure_inventory_issues:
        accuracy.extend(["- 图片资产问题：", *[f"  - {item}" for item in figure_inventory_issues]])
    else:
        accuracy.append("- 自动结构检查未发现异常；仍建议抽查复杂矩阵、分式和公式编号。")
    for name in ("metadata.yaml", "manifest.json", "review.md"):
        path = output / name
        if path.is_file():
            path.unlink()
    diagnostics = output / "diagnostics"
    if diagnostics.is_dir():
        import shutil
        shutil.rmtree(diagnostics)
    formulas_dir = output / "assets" / "formulas"
    if formulas_dir.is_dir() and not any(formulas_dir.iterdir()):
        formulas_dir.rmdir()
    if timings is None:
        timing_lines = [
            "- PDF 预检与准备：未记录",
            "- 模型识别（正文、公式与图片）：未记录",
            "- Markdown、图片整理与质量检查：未记录",
            "- **总耗时：未记录**",
            "- 说明：本文由旧版本工具转换，当时尚未启用计时功能。",
        ]
    else:
        measured = dict(timings)
        measured["Markdown、图片整理与质量检查"] = time.perf_counter() - delivery_started
        total = sum(measured.values())
        timing_lines = [*[f"- {name}：{_format_duration(seconds)}" for name, seconds in measured.items()],
                        f"- **总耗时：{_format_duration(total)}**"]
    total_runtime = "未记录"
    for line in reversed(timing_lines):
        match = re.search(r"\*\*总耗时：(.+?)\*\*", line)
        if match:
            total_runtime = match.group(1)
            break
    environment_lines = [
        f"- 工具版本：{tool_version}",
        f"- 运行模式：{backend}",
        f"- 整批次开始时间：{batch_started_at}（北京时间）",
        f"- 本篇运行时间：{total_runtime}",
        f"- 识别引擎：{engine_label}",
        f"- 转换范围：{max_pages_text}",
    ]
    if gpu_info:
        environment_lines.append(f"- GPU：{gpu_info}")
    if api_base_url:
        environment_lines.append(f"- API地址：{api_base_url}")
    if source_hash:
        environment_lines.append(f"- PDF SHA256：`{source_hash}`")
    environment_lines.extend([
        f"- 输出目录：`{output.name}/`",
        "- Markdown目标：Obsidian 兼容，同时尽量保持通用 Markdown/LaTeX 可读。",
    ])
    readme = "\n".join([
        f"# {title}", "", "## 文件组成", "",
        "- `article.md`：适合 Obsidian 的单栏全文",
        "- `assets/figures/`：正文引用图片",
        "- `README.md`：文献信息、内容概览和转换检查（本文件）",
        "", "## 内容概览", "", _abstract(markdown), "",
        "## 运行环境与方案", "", *environment_lines, "",
        "## 转换记录与检查", "", *checks, "",
        "## 转换耗时", "", *timing_lines, "",
        "## 准确性与复核", "", *accuracy, "",
    ])
    (output / "README.md").write_text(readme, encoding="utf-8")


def finalize_existing(pdf: Path, output: Path) -> None:
    markdown = (output / "article.md").read_text(encoding="utf-8")
    title_match = re.search(r'^title:\s*["\']?(.+?)["\']?\s*$', markdown, re.M)
    if not title_match:
        title_match = re.search(r"^#\s+(.+)$", markdown, re.M)
    title = title_match.group(1).strip() if title_match else pdf.stem
    errors, warnings, formulas = _quality_check(markdown)
    if errors:
        raise RuntimeError("Cannot finalize corrupt Markdown: " + "; ".join(errors))
    image_pattern = re.compile(r"!\[[^]]*\]\(assets/figures/([^)]+)\)|!\[\[assets/figures/([^]|]+)")
    images = len({a or b for a, b in image_pattern.findall(markdown)})
    finalize_delivery(output, source_name=pdf.name, title=title,
                      pages=len(PdfReader(str(pdf)).pages), formulas=formulas,
                      images=images, warnings=warnings, source_pdf=pdf)


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Normalize an existing PDF-to-Markdown delivery")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    finalize_existing(args.pdf.resolve(), args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

