"""User-specific Markdown and LaTeX preferences.

AI maintainers: add personal output preferences in this module only.  Rules
here are intentionally separate from general MinerU normalization and LaTeX
correctness repairs.
"""

from __future__ import annotations

import re


_COPYRIGHT_LATEX_PATTERNS = (
    r"\\text\{\s*\\circledcirc\s*\}",
    r"\\circledcirc",
    r"\\text\{\s*\\circledast\s*\}",
    r"\\circledast",
    r"\\text\{\s*\\textcircled\{\s*[cC]\s*\}\s*\}",
    r"\\textcircled\{\s*[cC]\s*\}",
    r"\\text\{\s*\\textcircle\{\s*[cC]\s*\}\s*\}",
    r"\\textcircle\{\s*[cC]\s*\}",
    r"\\text\{\s*©\s*\}",
)


def prefer_unicode_copyright(markdown: str) -> str:
    """Use the directly typable copyright character instead of TeX variants."""
    for pattern in _COPYRIGHT_LATEX_PATTERNS:
        markdown = re.sub(pattern, "\u00a9", markdown)
    return markdown


def apply_user_customizations(markdown: str) -> str:
    """Single extension point for all personalized output rules."""
    markdown = prefer_unicode_copyright(markdown)
    return markdown
