"""Isolated MinerU worker without the temporary FastAPI orchestration layer."""

from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path


def _install_progress_reporter(document_pages: int) -> None:
    """Mirror MinerU's real page progress into the batch progress file."""
    if not os.environ.get("PDF2MD_PROGRESS_FILE"):
        return
    import tqdm as tqdm_module
    from converter_core.progress import emit_progress

    original = tqdm_module.tqdm

    class ReportingTqdm(original):
        predict_round = 0

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            if str(getattr(self, "desc", "") or "").strip().lower() == "predict":
                ReportingTqdm.predict_round += 1
            self._predict_round = ReportingTqdm.predict_round
            self._report()

        def update(self, n=1):
            result = super().update(n)
            self._report()
            return result

        def _report(self):
            total = float(self.total or 0)
            ratio = (float(self.n) / total) if total else 0.0
            description = str(getattr(self, "desc", "") or "页面与公式识别").strip()
            lowered = description.lower()
            if lowered == "predict":
                phase = "页面初步识别" if self._predict_round <= 1 else "公式与版面识别"
            elif "processing pages" in lowered:
                phase = "版面重建"
            else:
                phase = "正文、公式与图片识别"
            emit_progress(
                "页面与公式识别",
                0.08 + 0.82 * min(1.0, ratio),
                phase=phase,
                current=int(self.n),
                total=int(total),
                document_pages=document_pages,
                is_page_progress=bool(total and int(total) == document_pages),
            )

    tqdm_module.tqdm = ReportingTqdm


def _prepare_fasttext_language_model() -> None:
    """Make MinerU's language detector robust on non-ASCII Windows paths.

    fast_langdetect normally loads its bundled ``lid.176.ftz`` from
    site-packages.  On some Windows machines the fastText native extension
    fails when that path contains non-ASCII account names, even though Python
    itself can read the file.  Copying the small language model to a stable
    public ASCII path and pointing fast_langdetect at it keeps the official
    MinerU pipeline unchanged while avoiding that path-sensitive failure.
    """
    if os.name != "nt":
        return
    try:
        import fast_langdetect.ft_detect.infer as infer

        source = Path(infer.LOCAL_SMALL_MODEL_PATH)
        if not source.is_file():
            return
        target_dir = Path(os.environ.get("PDF2MD_FASTTEXT_CACHE", r"C:\Users\Public\PDF2Markdown\fasttext"))
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / source.name
        if not target.is_file() or target.stat().st_size != source.stat().st_size:
            shutil.copy2(source, target)
        infer.LOCAL_SMALL_MODEL_PATH = target
        os.environ["FTLANG_CACHE"] = str(target_dir)
    except Exception:
        # Language detection is a MinerU internal detail; if this compatibility
        # preparation fails, let MinerU continue and report its own error.
        return


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--max-pages", type=int)
    args = parser.parse_args()
    from pypdf import PdfReader
    document_pages = len(PdfReader(str(args.pdf)).pages)
    if args.max_pages:
        document_pages = min(document_pages, args.max_pages)
    _install_progress_reporter(document_pages)
    _prepare_fasttext_language_model()
    from mineru.cli.common import do_parse
    from converter_core.progress import emit_progress

    emit_progress("加载识别模型", 0.03)
    do_parse(
        output_dir=str(args.output),
        pdf_file_names=[args.pdf.stem],
        pdf_bytes_list=[args.pdf.read_bytes()],
        p_lang_list=["ch"],
        backend="vlm-engine",
        parse_method="auto",
        formula_enable=True,
        table_enable=True,
        f_draw_layout_bbox=False,
        f_draw_span_bbox=False,
        f_dump_md=True,
        f_dump_middle_json=True,
        f_dump_model_output=True,
        f_dump_orig_pdf=False,
        f_dump_content_list=True,
        start_page_id=0,
        end_page_id=(args.max_pages - 1) if args.max_pages else None,
        image_analysis=False,
    )
    emit_progress("整理识别结果", 0.91)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

