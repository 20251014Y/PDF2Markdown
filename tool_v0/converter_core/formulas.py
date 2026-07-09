from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Protocol


EQUATION_NUMBER = re.compile(r"\(([A-Za-z]?\d+(?:\.\d+)?)\)\s*$")
MATH_TOKENS = re.compile(r"[=∫∑√±×·≤≥≈≠∞∂∇]|(?:\^|_)[A-Za-z0-9{]")


@dataclass
class FormulaResult:
    latex: str | None
    confidence: float
    method: str


class FormulaRecognizer(Protocol):
    def recognize(self, image_path: str, timeout: int) -> FormulaResult: ...


class NullRecognizer:
    def recognize(self, image_path: str, timeout: int) -> FormulaResult:
        return FormulaResult(None, 0.0, "unavailable")


def inline_math_to_latex(text: str) -> str:
    value = unicodedata.normalize("NFKC", text)
    replacements = {
        "×": r"\times", "·": r"\cdot", "±": r"\pm", "≤": r"\le",
        "≥": r"\ge", "≠": r"\ne", "≈": r"\approx", "∞": r"\infty",
        "∂": r"\partial", "∇": r"\nabla", "∑": r"\sum", "∫": r"\int",
        "Γ": r"\Gamma", "Δ": r"\Delta", "Φ": r"\Phi", "Ω": r"\Omega",
        "α": r"\alpha", "β": r"\beta", "γ": r"\gamma", "δ": r"\delta",
        "θ": r"\theta", "λ": r"\lambda", "μ": r"\mu", "ρ": r"\rho",
        "σ": r"\sigma", "φ": r"\phi", "ψ": r"\psi", "ω": r"\omega",
    }
    return "".join(replacements.get(ch, ch) for ch in value).strip()


def best_effort_latex(text: str) -> str:
    """Produce editable MathJax input even when PDF structure is incomplete."""
    value = inline_math_to_latex(text)
    value = re.sub(r"\(cid:\d+\)", r"\\mathord{?}", value)
    value = re.sub(r"\s+", " ", value).strip()
    # A dangling brace makes the whole MathJax block fail. Preserve the visible
    # characters while balancing delimiters; the review report retains the crop.
    for opening, closing in (("{", "}"), ("(", ")"), ("[", "]")):
        delta = value.count(opening) - value.count(closing)
        if delta > 0:
            value += closing * delta
        elif delta < 0:
            value = opening * (-delta) + value
    return value or r"\text{[formula extraction unavailable]}"


def looks_like_display_formula(text: str, page_width: float, bbox: tuple[float, float, float, float]) -> bool:
    compact = text.strip()
    if not compact or len(compact) > 240:
        return False
    symbolic = len(MATH_TOKENS.findall(compact))
    has_number = bool(EQUATION_NUMBER.search(compact))
    centered = bbox[0] > page_width * 0.10 and bbox[2] < page_width * 0.97
    words = compact.split()
    numbered_equation = has_number and not re.search(r"\b(?:Eq\.?|Equation)\s*\(", compact, re.I) and (symbolic >= 1 or len(words) <= 35)
    return (numbered_equation and len(words) <= 55) or (centered and symbolic >= 2 and len(words) <= 35)


def equation_number(text: str) -> str | None:
    match = EQUATION_NUMBER.search(text.strip())
    return match.group(1) if match else None


def conservative_latex(text: str) -> FormulaResult:
    """Convert only flat, unambiguous Unicode math; reject 2-D notation."""
    raw = text.strip()
    number = EQUATION_NUMBER.search(raw)
    if number:
        raw = raw[: number.start()].rstrip()
    if "(cid:" in raw or any(0x1D400 <= ord(ch) <= 0x1D7FF for ch in raw) or "{" in raw or "}" in raw:
        return FormulaResult(None, 0.0, "text-layer-unmapped-glyph")
    raw = unicodedata.normalize("NFKC", raw)
    replacements = {
        "×": r"\times ", "·": r"\cdot ", "±": r"\pm ", "≤": r"\le ",
        "≥": r"\ge ", "≠": r"\ne ", "≈": r"\approx ", "∞": r"\infty ",
        "∂": r"\partial ", "∇": r"\nabla ", "∑": r"\sum ", "∫": r"\int ",
        "α": r"\alpha ", "β": r"\beta ", "γ": r"\gamma ", "δ": r"\delta ",
        "ε": r"\epsilon ", "θ": r"\theta ", "λ": r"\lambda ", "μ": r"\mu ",
        "π": r"\pi ", "ρ": r"\rho ", "σ": r"\sigma ", "φ": r"\phi ",
        "ψ": r"\psi ", "ω": r"\omega ", "Δ": r"\Delta ", "Ω": r"\Omega ",
    }
    if any(ch in raw for ch in "√∏⎡⎤⎣⎦") or "  " in raw:
        return FormulaResult(None, 0.25, "text-layer-unsafe")
    latex = "".join(replacements.get(ch, ch) for ch in raw).strip()
    if not latex or not validate_latex(latex):
        return FormulaResult(None, 0.0, "text-layer-invalid")
    confidence = 0.88 if "=" in raw and len(raw) < 100 else 0.68
    return FormulaResult(latex, confidence, "text-layer-flat")


def validate_latex(value: str) -> bool:
    if any(ord(ch) < 32 and ch not in "\n\t" for ch in value):
        return False
    pairs = {"{": "}", "[": "]", "(": ")"}
    stack: list[str] = []
    escaped = False
    for ch in value:
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
        elif ch in pairs:
            stack.append(pairs[ch])
        elif ch in pairs.values() and (not stack or stack.pop() != ch):
            return False
    if stack or value.count(r"\left") != value.count(r"\right"):
        return False
    begins = re.findall(r"\\begin\{([^}]+)\}", value)
    ends = re.findall(r"\\end\{([^}]+)\}", value)
    return begins == ends

