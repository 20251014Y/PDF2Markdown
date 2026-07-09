from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import threading
import time
import warnings
from datetime import datetime
from pathlib import Path

from rich.console import Console, Group
from rich.live import Live
from rich.progress import (BarColumn, Progress, SpinnerColumn, TaskProgressColumn,
                            TextColumn, TimeElapsedColumn)
from rich.text import Text

from .pipeline import convert

for logger_name in ("pypdf", "pypdf._reader", "pypdf.generic"):
    logging.getLogger(logger_name).setLevel(logging.CRITICAL)
warnings.filterwarnings("ignore", module=r"pypdf(\..*)?")


LOCAL_STEPS = (
    "检查 PDF、页数与输出目录",
    "加载 MinerU 视觉模型",
    "逐页识别正文、公式与图片",
    "整理 Markdown、表格与图片",
    "质量检查并生成 README",
)

API_STEPS = (
    "检查 PDF、Token 与输出目录",
    "获取安全上传地址",
    "上传 PDF",
    "云端排队并逐页解析",
    "下载并解压识别结果",
    "整理 Markdown、图片并生成 README",
)


def _beijing_time() -> str:
    # Keep this dependency-free for embedded Python.  On the user's Windows
    # machine this is normally Beijing time; if not, it is still a useful local
    # run timestamp and will never fail because tzdata is missing.
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _gpu_info() -> str:
    try:
        completed = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        line = (completed.stdout or "").splitlines()[0].strip()
        return line or "未检测到 NVIDIA GPU"
    except Exception:
        return "未检测到 NVIDIA GPU"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="将 input 中的 PDF 批量转换为 Obsidian Markdown")
    parser.add_argument("-InputPdf", "--input", dest="input_pdf", type=Path,
                        help="只转换指定 PDF；省略时自动扫描 input 中全部 PDF")
    parser.add_argument("-MaxPages", "--max-pages", dest="max_pages", type=int, default=0,
                        help="仅转换前 N 页（调试用途）")
    parser.add_argument("-Overwrite", "--overwrite", action="store_true",
                        help="强制重新转换；默认跳过已有 article.md 的文献")
    parser.add_argument("--backend", choices=("local", "api"),
                        default=os.environ.get("PDF2MD_BACKEND", "local"),
                        help=argparse.SUPPRESS)
    return parser


def _step_for(stage: str, backend: str) -> int:
    if backend == "api":
        if "质量" in stage or "整理 API" in stage:
            return 6
        if "下载" in stage or "解压" in stage:
            return 5
        if "云端" in stage or "解析" in stage:
            return 4
        if "上传 PDF" in stage:
            return 3
        if "上传地址" in stage:
            return 2
        return 1
    if "质量" in stage:
        return 5
    if "整理" in stage:
        return 4
    if "页面" in stage or "公式识别" in stage:
        return 3
    if "模型" in stage or "MinerU" in stage:
        return 2
    if "检查" in stage:
        return 1
    return 1


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    console = Console()
    steps = API_STEPS if args.backend == "api" else LOCAL_STEPS
    step_count = len(steps)
    detail_step = 4 if args.backend == "api" else 3
    root = Path(os.environ.get("PDF2MD_ROOT", Path(__file__).resolve().parents[2])).resolve()
    input_dir = root / "input"
    output_dir = root / "output"
    output_dir.mkdir(exist_ok=True)
    console.print("\n[bold cyan]PDF → Obsidian Markdown[/bold cyan]")
    gpu_text = ""
    if args.backend == "api":
        console.print("[bold magenta]工作方式：MinerU API（联网）[/bold magenta]")
    else:
        console.print("[bold blue]工作方式：本地 MinerU VLM（GPU）[/bold blue]")
        gpu_text = _gpu_info()
        console.print(f"[cyan]GPU：{gpu_text}[/cyan]")
    console.print("[bold]前置阶段：比较 input 与 output[/bold]")

    if args.input_pdf:
        selected = args.input_pdf if args.input_pdf.is_absolute() else (Path.cwd() / args.input_pdf)
        pdfs = [selected.resolve()]
    else:
        pdfs = sorted(input_dir.glob("*.pdf"), key=lambda path: path.name.lower())
    if not pdfs:
        console.print("[bold red]未在 input 中找到 PDF。[/bold red]")
        return 1
    missing = [pdf for pdf in pdfs if not pdf.is_file() or pdf.suffix.lower() != ".pdf"]
    if missing:
        console.print(f"[bold red]输入文件不存在或不是 PDF：{missing[0]}[/bold red]")
        return 1

    pending: list[tuple[Path, Path]] = []
    skipped: list[Path] = []
    verbose_scan = len(pdfs) <= 10
    for pdf in pdfs:
        destination = output_dir / pdf.stem
        if (destination / "article.md").is_file() and not args.overwrite:
            skipped.append(pdf)
            if verbose_scan:
                console.print(f"  [yellow]跳过[/yellow] {pdf.name} [dim]（已有 article.md）[/dim]")
        else:
            pending.append((pdf, destination))
            console.print(f"  [green]待转换[/green] {pdf.name}")
    if not verbose_scan and skipped:
        console.print(f"  [dim]已跳过 {len(skipped)} 篇已有结果；为保持界面简洁不逐条显示。[/dim]")
    console.print(f"[bold green]✓ 比较完成：输入 {len(pdfs)} 篇，待转换 {len(pending)} 篇，跳过 {len(skipped)} 篇。[/bold green]")
    if not pending:
        console.print("\n[bold green]100%  全部文献已有完整结果，无需重复生成。[/bold green]")
        return 0

    console.print(f"\n[bold]每篇文献依次执行以下 {step_count} 步：[/bold]")
    for index, step in enumerate(steps, 1):
        console.print(f"  [dim]{index}/{step_count}[/dim]  {step}")
    console.print()

    # Keep runtime state beside the running converter package.  Deriving this
    # from the source location avoids creating a stale root/tool directory
    # when the versioned runtime folder is named tool_v0 (or moved elsewhere).
    tool_dir = Path(__file__).resolve().parent.parent
    progress_dir = tool_dir / ".runtime-home" / "progress"
    progress_dir.mkdir(parents=True, exist_ok=True)
    summary_columns = [
        SpinnerColumn(), TextColumn("[bold cyan]{task.description}"),
        BarColumn(bar_width=32), TaskProgressColumn(),
        TextColumn("[white]{task.fields[current]}"),
    ]
    summary = Progress(*summary_columns, console=console, auto_refresh=False)
    active_step = Progress(
        SpinnerColumn(), TextColumn("[bold yellow]{task.description}"),
        TextColumn("[dim]（"), TimeElapsedColumn(), TextColumn("[dim]）"),
        console=console, auto_refresh=False,
    )
    details = Progress(TextColumn("{task.description}"), console=console, auto_refresh=False)
    display_log: list[str] = []

    def screen() -> Group:
        log_text = Text("\n".join(display_log[-18:])) if display_log else Text("")
        return Group(summary, active_step, details, log_text)

    started = time.perf_counter()
    batch_started_at = _beijing_time()
    os.environ["PDF2MD_BATCH_STARTED_AT"] = batch_started_at
    os.environ["PDF2MD_BACKEND_LABEL"] = "MinerU API（联网）" if args.backend == "api" else "本地 MinerU VLM（GPU）"
    if gpu_text:
        os.environ["PDF2MD_GPU_INFO"] = gpu_text
    else:
        os.environ.pop("PDF2MD_GPU_INFO", None)
    console.print(f"[bold]整批次开始运行：[/bold][cyan]{batch_started_at}[/cyan] [dim]（北京时间）[/dim]")
    overall_task = summary.add_task("整批总进度", total=len(pending), current="准备开始")
    document_task = summary.add_task("当前文献", total=1.0, current="尚未开始", visible=False)
    succeeded: list[Path] = []
    failed: list[tuple[Path, str]] = []
    with Live(
        screen(),
        console=console,
        refresh_per_second=4,
        transient=False,
        redirect_stdout=False,
        redirect_stderr=False,
        vertical_overflow="visible",
    ) as live:
        for document_index, (pdf, destination) in enumerate(pending):
            document_number = document_index + 1
            document_started = time.perf_counter()
            display_log.append(f"文献 {document_number}/{len(pending)}：{pdf.name}")
            summary.update(document_task, completed=0, visible=True,
                           description=f"本文 {document_number}/{len(pending)}",
                           current="进行中")
            token = f"batch-{os.getpid()}-{document_index}.json"
            progress_file = progress_dir / token
            progress_file.unlink(missing_ok=True)
            os.environ["PDF2MD_PROGRESS_FILE"] = str(progress_file)
            stop = threading.Event()
            step_state = {
                "current": 1,
                "started": time.perf_counter(),
                "task": None,
                "details": [],
                "last_status_print": 0.0,
            }
            step_state["task"] = active_step.add_task(
                f"[1/{step_count}] {steps[0]}", total=None
            )
            live.update(screen())

            def finish_step(step: int, now: float) -> None:
                elapsed = now - step_state["started"]
                task_id = step_state.get("task")
                if task_id is not None:
                    active_step.remove_task(task_id)
                for detail_task in step_state["details"]:
                    details.remove_task(detail_task)
                step_state["details"] = []
                display_log.append(f"  ✓ [{step}/{step_count}] {steps[step - 1]} （{elapsed:.1f} 秒）")
                step_state["started"] = now
                step_state["task"] = None
                live.update(screen())

            def fail_step(message: str) -> None:
                elapsed = time.perf_counter() - step_state["started"]
                task_id = step_state.get("task")
                if task_id is not None:
                    active_step.remove_task(task_id)
                for detail_task in step_state["details"]:
                    details.remove_task(detail_task)
                step_state["details"] = []
                current = max(1, min(step_state["current"], step_count))
                display_log.append(f"  ✗ [{current}/{step_count}] {steps[current - 1]} （{elapsed:.1f} 秒）")
                display_log.append(f"    {message}")
                step_state["task"] = None
                live.update(screen())

            def start_step(step: int) -> None:
                step_state["current"] = step
                step_state["task"] = active_step.add_task(
                    f"[{step}/{step_count}] {steps[step - 1]}", total=None
                )
                step_state["last_status_print"] = 0.0
                if step == detail_step:
                    step_state["details"] = [
                        details.add_task("    当前阶段：准备识别", total=None),
                        details.add_task("    页面：准备中", total=None),
                        details.add_task("    本阶段：0%", total=None),
                    ]

            def monitor(base: int = document_index, path: Path = progress_file) -> None:
                highest = 0.0
                while not stop.wait(0.1):
                    try:
                        state = json.loads(path.read_text(encoding="utf-8"))
                        highest = max(highest, float(state.get("fraction", 0.0)))
                        stage = str(state.get("stage", "准备"))
                        step = _step_for(stage, args.backend)
                        if step > step_state["current"]:
                            now = time.perf_counter()
                            while step_state["current"] < step:
                                finish_step(step_state["current"], now)
                                start_step(step_state["current"] + 1)
                        if step == detail_step and step_state["details"]:
                            phase = str(state.get("phase", "正文、公式与图片识别"))
                            current = int(state.get("current", 0) or 0)
                            total = int(state.get("total", 0) or 0)
                            document_pages = int(state.get("document_pages", 0) or 0)
                            is_page = bool(state.get("is_page_progress", False))
                            stage_percent = round(current * 100 / total) if total else 0
                            if is_page:
                                page_text = f"    页面：{min(current, document_pages)}/{document_pages}"
                            else:
                                page_text = (f"    页面：{document_pages}/{document_pages}（初步扫描完成）"
                                             if document_pages else "    页面：等待服务器返回页数")
                            details.update(step_state["details"][0], description=f"    当前阶段：{phase}")
                            details.update(step_state["details"][1], description=page_text)
                            unit_text = f"，处理单元 {current}/{total}" if total and not is_page else ""
                            details.update(step_state["details"][2], description=f"    本阶段：{stage_percent}%{unit_text}")
                        summary.update(document_task, completed=highest,
                                       current=f"进行到 {step}/{step_count}")
                        summary.update(overall_task, completed=base + highest,
                                       current=f"正在处理 {document_number}/{len(pending)}")
                        live.update(screen())
                    except (OSError, ValueError, json.JSONDecodeError):
                        continue

            watcher = threading.Thread(target=monitor, daemon=True)
            watcher.start()
            try:
                convert(pdf, destination,
                        formula_engine="mineru-api" if args.backend == "api" else "mineru",
                        overwrite=destination.exists(),
                        max_pages=args.max_pages or None)
            except Exception as exc:
                stop.set()
                watcher.join(timeout=1)
                # Fast network failures may happen before the monitor thread's
                # next 100 ms refresh.  Read the last event once so the failed
                # step shown to the user is still accurate.
                try:
                    failed_state = json.loads(progress_file.read_text(encoding="utf-8"))
                    failed_step = _step_for(str(failed_state.get("stage", "")), args.backend)
                    now = time.perf_counter()
                    while step_state["current"] < failed_step:
                        finish_step(step_state["current"], now)
                        start_step(step_state["current"] + 1)
                except (OSError, ValueError, json.JSONDecodeError):
                    pass
                reason = str(exc)
                failed.append((pdf, reason))
                fail_step(f"转换失败：{pdf.name}")
                summary.update(document_task, completed=1.0, visible=False,
                               current=f"失败，已跳过：{pdf.name}")
                summary.update(overall_task, completed=document_number,
                               current=f"已处理 {document_number}/{len(pending)}（失败 {len(failed)} 篇）")
                display_log.append(f"  ✗ 文献 {document_number}/{len(pending)} 已跳过")
                display_log.append(f"    {reason}")
                live.update(screen())
                continue
            finally:
                stop.set()
                watcher.join(timeout=1)
                progress_file.unlink(missing_ok=True)
            now = time.perf_counter()
            while step_state["current"] <= step_count:
                finish_step(step_state["current"], now)
                if step_state["current"] == step_count:
                    break
                start_step(step_state["current"] + 1)
            document_elapsed = time.perf_counter() - document_started
            succeeded.append(pdf)
            summary.update(document_task, completed=1.0, visible=False,
                           current=f"本文 {document_number}/{len(pending)} 完成")
            summary.update(overall_task, completed=document_number,
                           current=f"已完成 {document_number}/{len(pending)}")
            display_log.append(f"  ✓ 文献 {document_number}/{len(pending)} 已完成 （{document_elapsed / 60:.1f} 分钟）")
            display_log.append(f"    输出：{destination}")
            live.update(screen())
    os.environ.pop("PDF2MD_PROGRESS_FILE", None)
    os.environ.pop("PDF2MD_BATCH_STARTED_AT", None)
    os.environ.pop("PDF2MD_BACKEND_LABEL", None)
    os.environ.pop("PDF2MD_GPU_INFO", None)
    elapsed = time.perf_counter() - started
    batch_finished_at = _beijing_time()
    console.print(f"\n[bold]整批次完成：[/bold][cyan]{batch_finished_at}[/cyan] [dim]（北京时间）[/dim]")
    if failed:
        console.print(
            f"[bold yellow]批量完成：成功 {len(succeeded)} 篇，失败 {len(failed)} 篇，"
            f"跳过 {len(skipped)} 篇，总耗时 {elapsed / 60:.1f} 分钟。[/bold yellow]"
        )
        console.print("[bold red]失败文献：[/bold red]")
        for pdf, reason in failed:
            first_line = reason.splitlines()[0] if reason else "未知原因"
            console.print(f"  [red]- {pdf.name}[/red]：{first_line}")
    else:
        console.print(
            f"[bold green]全部完成：成功 {len(succeeded)} 篇，失败 0 篇，"
            f"跳过 {len(skipped)} 篇，总耗时 {elapsed / 60:.1f} 分钟。[/bold green]"
        )
    console.print(f"结果目录：[cyan]{output_dir}[/cyan]")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

