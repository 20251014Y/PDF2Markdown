from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .pipeline import convert


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="pdf2markdown", description="Convert a PDF to Markdown without requiring network services.")
    result.add_argument("input", type=Path, help="PDF file")
    result.add_argument("--output", "-o", type=Path, required=True, help="Output directory")
    result.add_argument("--mode", choices=("local", "enhanced"), default="local")
    result.add_argument("--dpi", type=int, default=300)
    result.add_argument("--formula-timeout", type=int, default=30)
    result.add_argument("--formula-retries", type=int, default=1)
    result.add_argument("--formula-engine", choices=("auto", "mineru", "mineru-api", "mathpix", "heuristic"), default="auto", help="Formula/document OCR engine")
    result.add_argument("--mineru-timeout", type=int, default=3600, help="MinerU document timeout in seconds")
    result.add_argument("--mathpix-timeout", type=int, default=600, help="Whole-document Mathpix timeout in seconds")
    result.add_argument("--mathpix-keep-remote", action="store_true", help="Do not delete the remote Mathpix job after download")
    result.add_argument("--keep-intermediate", action="store_true")
    result.add_argument("--overwrite", action="store_true")
    result.add_argument("--max-pages", type=int, help="Convert only the first N pages (useful for testing)")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if not 72 <= args.dpi <= 600:
        print("error: --dpi must be between 72 and 600", file=sys.stderr)
        return 2
    if args.formula_timeout < 1 or args.formula_retries < 0 or args.mathpix_timeout < 30 or args.mineru_timeout < 30 or (args.max_pages is not None and args.max_pages < 1):
        print("error: invalid formula timeout/retry configuration", file=sys.stderr)
        return 2
    try:
        doc = convert(args.input.resolve(), args.output.resolve(), mode=args.mode, dpi=args.dpi, formula_timeout=args.formula_timeout, formula_retries=args.formula_retries, keep_intermediate=args.keep_intermediate, overwrite=args.overwrite, max_pages=args.max_pages, formula_engine=args.formula_engine, mathpix_timeout=args.mathpix_timeout, mathpix_keep_remote=args.mathpix_keep_remote, mineru_timeout=args.mineru_timeout)
    except (ValueError, FileExistsError, RuntimeError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Converted {doc.pages} page(s) to {args.output}")
    print(f"Review items: {len(doc.reviews)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

