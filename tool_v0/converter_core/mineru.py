from __future__ import annotations

import json
import hashlib
import ctypes
import html
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class MinerUError(RuntimeError):
    pass


def _run_worker(command: list[str], *, cwd: Path, env: dict[str, str],
                timeout: int) -> subprocess.CompletedProcess[str]:
    """Run the MinerU worker and avoid leaving it alive if this process exits.

    On Windows, closing the command window normally terminates the Python batch
    process.  A child process can occasionally outlive its parent, so the worker
    is put into a small Job object with KILL_ON_JOB_CLOSE when available.  If the
    current Windows policy refuses Job assignment, conversion still runs in the
    normal foreground process group.
    """
    if os.name != "nt":
        return subprocess.run(
            command, cwd=cwd, env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
        )

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", ctypes.c_uint32),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", ctypes.c_uint32),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", ctypes.c_uint32),
            ("SchedulingClass", ctypes.c_uint32),
        ]

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = ctypes.c_void_p
    kernel32.SetInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
    kernel32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    job = kernel32.CreateJobObjectW(None, None)
    if job:
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = 0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        kernel32.SetInformationJobObject(
            job, 9, ctypes.byref(info), ctypes.sizeof(info)
        )
    process = subprocess.Popen(
        command, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
    )
    if job:
        try:
            kernel32.AssignProcessToJobObject(job, process._handle)
        except Exception:
            pass
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        stdout, stderr = process.communicate()
        raise subprocess.TimeoutExpired(command, timeout, output=stdout, stderr=stderr) from exc
    finally:
        if job:
            kernel32.CloseHandle(job)
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def _friendly_mineru_failure(diagnostic: str) -> str:
    if "fast_langdetect" in diagnostic or "FastText model" in diagnostic:
        return (
            "MinerU 的语言检测模型加载失败。通常是本地依赖资源损坏、安装路径兼容性问题，"
            "或第三方 fastText 运行库在当前电脑上无法读取模型文件。"
            "请优先重新安装本地版；如果电脑显存较小，也可以改用 API 版。"
        )
    if "CUDA out of memory" in diagnostic or "out of memory" in diagnostic.lower():
        return (
            "本地 GPU 显存不足，MinerU VLM 无法完成本篇解析。"
            "这台电脑可以改用 API 版，或换显存更大的电脑运行本地版。"
        )
    return ""


@dataclass
class MinerUResult:
    markdown: str
    formulas: int
    equation_tags: list[str]
    images: int
    warnings: list[str]


def _html_tables_to_markdown(markdown: str) -> str:
    """Convert MinerU's simple HTML tables to Obsidian pipe tables."""
    def convert(match: re.Match[str]) -> str:
        html = match.group(0)
        image_sources = re.findall(r"<img\b[^>]*\bsrc\s*=\s*['\"]([^'\"]+)['\"][^>]*>", html, re.S | re.I)
        if image_sources:
            text_without_images = re.sub(r"<img\b[^>]*>", " ", html, flags=re.S | re.I)
            text_without_tags = re.sub(r"<[^>]+>", " ", text_without_images)
            residual_text = re.sub(r"\s+", " ", text_without_tags).strip()
            # MinerU can wrap a scientific figure in a one-cell HTML table
            # when the image itself contains grid lines.  Such image-only
            # tables should remain figures, not Obsidian pipe tables.
            if len(residual_text) <= 40:
                return "\n".join(f"![]({source})" for source in image_sources)
        rows: list[list[str]] = []
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S | re.I):
            cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S | re.I)
            if cells:
                cleaned = [re.sub(r"\s+", " ", cell).strip().replace("|", r"\vert") for cell in cells]
                rows.append(cleaned)
        if not rows:
            return match.group(0)
        width = max(map(len, rows))
        rows = [row + [""] * (width - len(row)) for row in rows]
        lines = ["| " + " | ".join(rows[0]) + " |", "| " + " | ".join(["---"] * width) + " |"]
        lines.extend("| " + " | ".join(row) + " |" for row in rows[1:])
        return "\n".join(lines)
    return re.sub(r"<table[^>]*>.*?</table>", convert, markdown, flags=re.S | re.I)


def _mineru_algorithm_divs_to_code(markdown: str) -> str:
    """Convert MinerU algorithm HTML blocks to normal Markdown code blocks."""
    def convert(match: re.Match[str]) -> str:
        body = html.unescape(match.group(1))
        body = re.sub(r"^\s*\n", "", body)
        body = re.sub(r"\n\s*$", "", body)
        language = "matlab" if re.search(r"(?m)^\s*function\b|%\s*\w+", body) else ""
        fence = f"```{language}".rstrip()
        return f"\n\n{fence}\n{body}\n```\n\n"

    pattern = (
        r"<div\b(?=[^>]*\bclass\s*=\s*['\"][^'\"]*\bmineru-algorithm\b)"
        r"[^>]*>(.*?)</div>"
    )
    return re.sub(pattern, convert, markdown, flags=re.S | re.I)


def referenced_figure_names(markdown: str) -> set[str]:
    """Return image basenames referenced by Markdown, Obsidian, or HTML img."""
    names: set[str] = set()
    patterns = [
        r"!\[[^]]*\]\(assets/figures/([^)]+)\)",
        r"!\[\[assets/figures/([^]|]+)",
        r"<img\b[^>]*\bsrc\s*=\s*['\"]assets/figures/([^'\"]+)['\"][^>]*>",
    ]
    for pattern in patterns:
        names.update(Path(name).name for name in re.findall(pattern, markdown, flags=re.S | re.I))
    return names


def executable(workspace: Path) -> Path | None:
    candidates = [
        workspace / ".python" / "Scripts" / "mineru.exe",
        workspace / ".python-dev" / "Scripts" / "mineru.exe",
        Path(shutil.which("mineru") or ""),
    ]
    return next((path for path in candidates if path and path.is_file()), None)


def _normalize(markdown: str) -> str:
    # Chart-analysis blocks are model-generated summaries, not source content.
    markdown = re.sub(r"\n*<details>.*?</details>\s*", "\n\n", markdown, flags=re.S | re.I)
    markdown = _mineru_algorithm_divs_to_code(markdown)
    markdown = _html_tables_to_markdown(markdown)
    markdown = re.sub(r"^# ([IVX]+\.\s+)", r"## \1", markdown, flags=re.M)
    markdown = re.sub(r"^# ([A-Z]\.\s+)", r"### \1", markdown, flags=re.M)
    markdown = re.sub(r"^# (\d+\.\s+)", r"#### \1", markdown, flags=re.M)
    markdown = re.sub(r"\$\s*(\[[0-9,\s–-]+\])\s*\$", r"\1", markdown)
    markdown = markdown.replace("images/", "assets/figures/")
    markdown = re.sub(r"\n{3,}", "\n\n", markdown)
    from .refine_markdown import (
        remove_display_formula_latex_delimiters,
        repair_multiline_formula_alignment,
        repair_vert_letter_spacing,
        remove_display_formula_padding,
    )
    markdown = repair_vert_letter_spacing(markdown)
    markdown = repair_multiline_formula_alignment(markdown)
    markdown = remove_display_formula_latex_delimiters(markdown)
    # Personal output preferences are isolated from general correctness fixes.
    from .user_customizations import apply_user_customizations
    markdown = apply_user_customizations(markdown)
    markdown = remove_display_formula_padding(markdown)
    return markdown.strip() + "\n"


def _quality_check(markdown: str) -> tuple[list[str], list[str], int]:
    errors: list[str] = []
    warnings: list[str] = []
    if "\ufffd" in markdown:
        errors.append(f"包含 {markdown.count(chr(0xFFFD))} 个 Unicode 替换字符")
    cid_count = len(re.findall(r"\(?cid:\d+\)?", markdown, re.I))
    if cid_count:
        errors.append(f"包含 {cid_count} 个未映射 cid 字形")
    private_count = sum(0xE000 <= ord(char) <= 0xF8FF for char in markdown)
    if private_count:
        errors.append(f"包含 {private_count} 个私用区字符")
    display = re.findall(r"\$\$\s*(.*?)\s*\$\$", markdown, re.S)
    if markdown.count("$$") != len(display) * 2:
        errors.append("行间公式 $$ 定界符不闭合")
    without_display = re.sub(r"\$\$.*?\$\$", "", markdown, flags=re.S)
    inline_dollars = len(re.findall(r"(?<!\\)\$", without_display))
    if inline_dollars % 2:
        errors.append("行内公式 $ 定界符不闭合")
    for index, formula in enumerate(display, 1):
        if any(token in formula for token in (r"\(", r"\)", r"\[", r"\]")):
            errors.append(f"第 {index} 个行间公式包含 Obsidian 不兼容的 LaTeX 定界符")
        if formula.count("{") != formula.count("}"):
            warnings.append(f"第 {index} 个行间公式花括号不平衡")
        if len(formula.strip()) < 3:
            warnings.append(f"第 {index} 个行间公式内容为空或过短")
    tags = re.findall(r"\\tag\s*\{\s*([^}]+?)\s*\}", markdown)
    duplicates = sorted({tag for tag in tags if tags.count(tag) > 1})
    if duplicates:
        warnings.append("公式编号重复：" + ", ".join(duplicates))
    return errors, warnings, len(display)


def process_pdf(pdf: Path, output: Path, workspace: Path, *, max_pages: int | None = None, timeout: int = 3600) -> MinerUResult:
    command_path = executable(workspace)
    if command_path is None:
        raise MinerUError("MinerU is not installed; expected .python/Scripts or .python-dev/Scripts")
    runtime_home = workspace / ".runtime-home"
    # MinerU appends the PDF stem beneath this directory.  Using the output
    # name here duplicates long paper titles and can exceed MAX_PATH on
    # Windows, so internal work folders use a stable short hash instead.
    work_key = hashlib.sha256(str(pdf.resolve()).encode("utf-8")).hexdigest()[:12]
    run_dir = runtime_home / "mineru-work" / work_key
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)
    model_root = workspace / ".models"
    runtime_home.mkdir(exist_ok=True)
    vlm_model = model_root / "modelscope" / "OpenDataLab" / "MinerU2.5-Pro-2605-1.2B"
    if vlm_model.is_dir():
        config_path = runtime_home / "mineru.json"
        config = {}
        if config_path.is_file():
            try:
                config = json.loads(config_path.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                config = {}
        config.update({
            "latex-delimiter-config": {
                "display": {"left": "$$", "right": "$$"},
                "inline": {"left": "$", "right": "$"},
            },
            "models-dir": {"vlm": str(vlm_model.resolve())},
            "model-source": "modelscope",
            "config_version": "1.3.2",
        })
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    env = os.environ.copy()
    env.update({
        "HOME": str(runtime_home),
        "USERPROFILE": str(runtime_home),
        "HF_HOME": str(model_root / "huggingface"),
        "MODELSCOPE_CACHE": str(model_root / "modelscope"),
        "MODELSCOPE_HOME": str(model_root / "modelscope"),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
    })
    worker_python = command_path.parent / "python.exe"
    if not worker_python.is_file():
        worker_python = workspace / ".python" / "python.exe"
    short_input = runtime_home / "inputs" / f"{work_key}.pdf"
    short_input.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(pdf, short_input)
    command = [str(worker_python), "-m", "converter_core.mineru_worker", str(short_input), str(run_dir)]
    if max_pages:
        command.extend(["--max-pages", str(max_pages)])
    try:
        try:
            completed = _run_worker(command, cwd=workspace, env=env, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise MinerUError(f"MinerU timed out after {timeout}s") from exc
    finally:
        short_input.unlink(missing_ok=True)
    if completed.returncode:
        diagnostic = (completed.stderr or completed.stdout)[-3000:]
        friendly = _friendly_mineru_failure(diagnostic)
        if friendly:
            diagnostic = friendly + "\n\n原始错误摘要：\n" + diagnostic
        raise MinerUError(f"MinerU failed with exit code {completed.returncode}:\n{diagnostic}")
    markdown_files = list(run_dir.rglob("*.md"))
    if not markdown_files:
        raise MinerUError("MinerU completed but produced no Markdown")
    source_root = markdown_files[0].parent
    raw = markdown_files[0].read_text(encoding="utf-8")
    normalized = _normalize(raw)
    errors, warnings, formula_count = _quality_check(normalized)
    diagnostic_dir = runtime_home / "diagnostics" / output.name
    diagnostic_dir.mkdir(parents=True, exist_ok=True)
    (diagnostic_dir / "mineru-raw.md").write_text(raw, encoding="utf-8")
    if errors:
        raise MinerUError("MinerU output failed quality checks: " + "; ".join(errors))
    image_source = source_root / "images"
    image_target = output / "assets" / "figures"
    image_target.mkdir(parents=True, exist_ok=True)
    image_count = 0
    if image_source.is_dir():
        referenced_images = referenced_figure_names(normalized)
        for image in image_source.iterdir():
            if image.is_file() and image.name in referenced_images:
                shutil.copy2(image, image_target / image.name)
                image_count += 1
    tags = re.findall(r"\\tag\s*\{\s*([^}]+?)\s*\}", normalized)
    middle = next(iter(source_root.glob("*_middle.json")), None)
    if middle:
        shutil.copy2(middle, diagnostic_dir / "mineru-middle.json")
    result = MinerUResult(normalized, formula_count, tags, image_count, warnings)
    shutil.rmtree(run_dir, ignore_errors=True)
    return result

