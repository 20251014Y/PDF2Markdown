from __future__ import annotations

import argparse
import re
from pathlib import Path


TABLE_I = r"""| $I$ | $p_a(I,P)$ | $\langle S_z\rangle_a(I,P)$ | $\lvert P_{\mathrm{eq}}\rvert$ |
|---:|:---:|:---:|---:|
| $\frac{1}{2}$ | $\frac{3}{4}+\frac{P^2}{4}$ | $\frac{P}{2}$ | $1$ |
| $1$ | $\frac{2}{3}+\frac{4P^2}{3(3+P^2)}$ | $\frac{5P+P^3}{3(3+P^2)}$ | $0.394$ |
| $\frac{3}{2}$ | $\frac{5}{8}+\frac{5P^2+P^4}{8(1+P^2)}$ | $\frac{5P+3P^3}{8(1+P^2)}$ | $0.207$ |
| $2$ | $\frac{3}{5}+\frac{4(5P^2+3P^4)}{5(5+10P^2+P^4)}$ | $\frac{35P+42P^3+3P^5}{10(5+10P^2+P^4)}$ | $0.128$ |
| $\frac{5}{2}$ | $\frac{7}{12}+\frac{35P^2+42P^4+3P^6}{12(3+10P^2+3P^4)}$ | $\frac{7P+14P^3+3P^5}{3(3+10P^2+3P^4)}$ | $0.087$ |"""


def repair_vert_letter_spacing(markdown: str) -> str:
    """Prevent a backslash-vert-letter sequence from becoming one command."""
    return re.sub(r"\\vert(?=[A-Za-z])", r"\\vert ", markdown)


_LINE_LEADING_ALIGNMENT_OPERATOR = re.compile(
    r"^\s*(=|[+\-]|\\times|\\cdot|\\pm|\\mp|\\equiv|\\leq?|\\geq?|\\approx|\\sim|\\propto|<|>)"
)

_CONTINUATION_OPERATORS = ("+", "-", r"\times", r"\cdot", r"\pm", r"\mp")


def _insert_alignment_point(line: str) -> str:
    """Add one aligned-environment marker without changing the formula meaning."""
    line = _normalize_existing_alignment(line)
    if "&" in line:
        return line
    leading = _LINE_LEADING_ALIGNMENT_OPERATOR.match(line)
    if leading:
        operator = leading.group(1)
        rest = line[leading.end(1):].strip()
        if operator in _CONTINUATION_OPERATORS:
            return f"&{operator} {rest}".rstrip()
        return line[:leading.start(1)] + "&" + line[leading.start(1):]
    for pattern in (
        r"(?<![<>=])=(?!=)",
        r"\\equiv",
        r"\\leq?",
        r"\\geq?",
        r"\\approx",
        r"\\sim",
        r"\\propto",
        r"<",
        r">",
    ):
        match = re.search(pattern, line)
        if match:
            return line[:match.start()] + "&" + line[match.start():]
    return line


def _normalize_existing_alignment(line: str) -> str:
    """Move misplaced alignment markers to the relation/operator side.

    Common MinerU mistakes:
    - ``\\times &\\left`` should be ``&\\times \\left``.
    - ``\\qquad + ... &\\left`` uses spacing as fake alignment; in ``aligned``
      it should be ``&+ ... \\left``.
    - ``&\\left. + ...`` puts a continuation plus under the equals sign; use
      ``&+ \\left. ...`` so it appears on the right-hand side.
    """
    stripped = line.strip()

    # Continuation line with an invisible delimiter before the operator.
    invisible_delimiter_operator = re.match(
        r"^&\s*(\\left\.|\\right\.)\s*([+\-]|\\times|\\cdot|\\pm|\\mp)\s+(.*)$",
        stripped,
        flags=re.S,
    )
    if invisible_delimiter_operator:
        delimiter = invisible_delimiter_operator.group(1)
        operator = invisible_delimiter_operator.group(2)
        rest = invisible_delimiter_operator.group(3).strip()
        return f"&{operator} {delimiter} {rest}"

    # Continuation line already has an alignment marker immediately before an
    # additive/multiplicative operator.  Keep relation symbols such as ``&=``
    # aligned, but move continuation operators to the right-hand side.
    aligned_continuation = re.match(
        r"^&\s*([+\-]|\\times|\\cdot|\\pm|\\mp)\s+(.*)$",
        stripped,
        flags=re.S,
    )
    if aligned_continuation:
        return f"&{aligned_continuation.group(1)} {aligned_continuation.group(2).strip()}"

    # Fake indentation followed by a misplaced later alignment marker.
    fake_indent = re.match(
        r"^(\\qquad|\\quad)\s*([+\-]|\\times|\\cdot|\\pm|\\mp)\s+(.*?)\s*&\s*(.*)$",
        stripped,
        flags=re.S,
    )
    if fake_indent:
        operator = fake_indent.group(2)
        middle = fake_indent.group(3).strip()
        tail = fake_indent.group(4).strip()
        return f"&{operator} {middle} {tail}".strip()

    # Lines beginning with an operator but followed by ``&`` after it.
    leading_operator_then_amp = re.match(
        r"^([+\-]|=|\\times|\\cdot|\\pm|\\mp|\\equiv|\\leq?|\\geq?|\\approx|\\sim|\\propto|<|>)\s*&\s*(.*)$",
        stripped,
        flags=re.S,
    )
    if leading_operator_then_amp:
        operator = leading_operator_then_amp.group(1)
        rest = leading_operator_then_amp.group(2).strip()
        if operator in _CONTINUATION_OPERATORS:
            return f"&{operator} {rest}"
        return f"&{operator} {rest}"

    # Same problem with a little spacing before the operator.
    line = re.sub(
        r"(^|\s)(\\times|\\cdot|[+\-]|\\pm|\\mp)\s*&\s*",
        lambda match: f"{match.group(1)}&{match.group(2)} ",
        line,
        count=1,
    )

    # If MinerU used ``\qquad`` or ``\quad`` at the start of a continuation
    # line, treat it as an alignment request rather than visual padding.
    line = re.sub(
        r"^\s*\\q?quad\s*([+\-]|\\times|\\cdot|\\pm|\\mp)\s+",
        lambda match: f"&{match.group(1)} ",
        line,
        count=1,
    )
    return line.strip()


def _repair_alignment_body(body: str) -> str:
    parts = re.split(r"\\\\", body)
    trailing_empty = bool(parts and not parts[-1].strip())
    if trailing_empty:
        parts = parts[:-1]
    if len([part for part in parts if part.strip()]) < 2:
        return body
    repaired = [_insert_alignment_point(part.strip()) for part in parts if part.strip()]
    repaired = _align_rhs_continuations(repaired)
    result = r" \\ ".join(repaired)
    if trailing_empty:
        result += r" \\"
    return result


def _align_rhs_continuations(lines: list[str]) -> list[str]:
    """Align additive/multiplicative continuations after the first ``=``.

    If later rows are ``&+ ...`` or ``&\\times ...``, the visual target is the
    right-hand side after the first equals sign.  Therefore the first row should
    be ``= &``.  Rows beginning with another relation, such as ``&=``, keep the
    original relation alignment.
    """
    if len(lines) < 2:
        return lines
    continuation_prefixes = ("&+", "&-", r"&\times", r"&\cdot", r"&\pm", r"&\mp")
    relation_prefixes = ("&=", r"&\equiv", r"&\le", r"&\leq", r"&\ge", r"&\geq", r"&\approx", r"&\sim", r"&\propto", "&<", "&>")
    normalized = [re.sub(r"\s+", "", line.strip()) for line in lines[1:]]
    has_rhs_continuation = any(
        any(line.startswith(prefix) for prefix in continuation_prefixes)
        for line in normalized
    )
    has_relation_continuation = any(
        any(line.startswith(prefix) for prefix in relation_prefixes)
        for line in normalized
    )
    if has_rhs_continuation and not has_relation_continuation:
        first = lines[0]
        first = re.sub(r"&\s*(=|\\equiv|\\approx)", r"\1 &", first, count=1)
        lines = [first, *lines[1:]]
    return lines


def _move_tag_out_of_alignment(markdown: str) -> str:
    r"""Move equation tags outside inner alignment environments.

    MathJax/amsmath accept ``\begin{aligned}...\end{aligned}\tag{n}``, but
    ``\tag`` inside the aligned rows is fragile and often fails in Obsidian.
    """
    def repair(match: re.Match[str]) -> str:
        env = match.group(1)
        body = match.group(2)
        outside_tag = match.group(4)
        tags = re.findall(r"\\tag\s*\{\s*([^{}]+?)\s*\}", body)
        if not tags:
            return match.group(0)
        body = re.sub(r"\s*,?\s*\\tag\s*\{\s*[^{}]+?\s*\}\s*", " ", body).strip()
        tag = (outside_tag or tags[-1]).strip()
        return f"\\begin{{{env}}} {body} \\end{{{env}}}\\tag{{{tag}}}"

    return re.sub(
        r"\\begin\{(aligned|alignedat|gathered|array)\}(.*?)\\end\{\1\}(\s*\\tag\s*\{\s*([^{}]+?)\s*\})?",
        repair,
        markdown,
        flags=re.S,
    )


def _deduplicate_display_tags(markdown: str) -> str:
    r"""Keep one ``\tag{}`` per display formula to avoid MathJax errors."""
    display = re.compile(r"\$\$(.*?)\$\$", flags=re.S)
    tag = re.compile(r"\\tag\s*\{\s*([^{}]+?)\s*\}")

    def repair(match: re.Match[str]) -> str:
        body = match.group(1)
        tags = list(tag.finditer(body))
        if len(tags) <= 1:
            return match.group(0)
        kept = tags[-1].group(1).strip()
        body = tag.sub("", body).strip()
        body = re.sub(r"\s+", " ", body)
        return f"$$\n{body}\\tag{{{kept}}}\n$$"

    return display.sub(repair, markdown)


def repair_multiline_formula_alignment(markdown: str) -> str:
    """Recover relation/operator alignment in multiline display equations.

    MinerU sometimes emits a visually aligned derivation as a one-column
    ``array``.  In that form a second line beginning with ``=`` is rendered as
    left-aligned text.  For Obsidian/MathJax, a single-column derivation is more
    robust as ``aligned`` with ``&`` before the relation/operator.
    """
    def convert_single_column_array(match: re.Match[str]) -> str:
        body = match.group(1)
        if "\\begin{" in body or "\\end{" in body:
            return match.group(0)
        repaired = _repair_alignment_body(body)
        if repaired == body:
            return match.group(0)
        return "\\begin{aligned} " + repaired + " \\end{aligned}"

    markdown = re.sub(
        r"\\begin\{array\}\{[lcr]\}(.*?)\\end\{array\}",
        convert_single_column_array,
        markdown,
        flags=re.S,
    )

    def repair_existing_aligned(match: re.Match[str]) -> str:
        env = match.group(1)
        body = match.group(2)
        repaired = _repair_alignment_body(body)
        return f"\\begin{{{env}}} {repaired} \\end{{{env}}}"

    markdown = re.sub(
        r"\\begin\{(aligned|alignedat|gathered)\}(.*?)\\end\{\1\}",
        repair_existing_aligned,
        markdown,
        flags=re.S,
    )
    markdown = _move_tag_out_of_alignment(markdown)
    return _deduplicate_display_tags(markdown)


def remove_display_formula_padding(markdown: str) -> str:
    lines = markdown.splitlines()
    output: list[str] = []
    in_display = False
    for line in lines:
        is_delimiter = line.strip() == "$$"
        if is_delimiter and not in_display:
            if output and not output[-1].strip():
                output.pop()
            output.append("$$")
            in_display = True
            continue
        if is_delimiter and in_display:
            output.append("$$")
            in_display = False
            continue
        if not in_display and output and output[-1] == "$$" and not line.strip():
            continue
        output.append(line)
    return "\n".join(output).rstrip() + "\n"


def remove_display_formula_latex_delimiters(markdown: str) -> str:
    r"""Remove stray ``\(...\)``/``\[...\]`` delimiters inside ``$$`` blocks.

    The pipeline has already decided which content is display math.  If MinerU
    leaves LaTeX delimiters inside a display block, they are redundant wrappers
    and can break Obsidian/MathJax rendering.  Text outside ``$$...$$`` is left
    untouched.
    """
    display = re.compile(r"\$\$(.*?)\$\$", flags=re.S)

    def repair(match: re.Match[str]) -> str:
        body = match.group(1)
        body = body.replace(r"\(", "").replace(r"\)", "")
        body = body.replace(r"\[", "").replace(r"\]", "")
        return f"$${body}$$"

    return display.sub(repair, markdown)


def refine(article: Path, readme: Path | None = None) -> tuple[int, int]:
    markdown = article.read_text(encoding="utf-8")
    markdown = repair_multiline_formula_alignment(markdown)
    markdown = remove_display_formula_latex_delimiters(markdown)
    markdown, table_count = re.subn(r"<table>.*?</table>", lambda _: TABLE_I, markdown, count=1, flags=re.S | re.I)
    if table_count != 1:
        raise RuntimeError(f"Expected one HTML table, replaced {table_count}")
    before = len(re.findall(r"\n\n\$\$|\$\$\n\n", markdown))
    markdown = remove_display_formula_padding(markdown)
    article.write_text(markdown, encoding="utf-8")
    if readme and readme.is_file():
        text = readme.read_text(encoding="utf-8")
        text = re.sub(
            r"- Table I：.*",
            "- Table I：使用 Obsidian 兼容的 Markdown 管道表格；单元格公式采用 `$...$`，多行内容使用 `<br>`。",
            text,
        )
        readme.write_text(text, encoding="utf-8")
    return table_count, before


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("article", type=Path)
    parser.add_argument("--readme", type=Path)
    parser.add_argument("--remove-unused-table-image", type=Path)
    args = parser.parse_args()
    table_count, padding_count = refine(args.article, args.readme)
    if args.remove_unused_table_image and args.remove_unused_table_image.is_file():
        args.remove_unused_table_image.unlink()
    print(f"tables={table_count} formula_padding_patterns={padding_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

