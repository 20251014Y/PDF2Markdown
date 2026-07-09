import unittest

from converter_core.formulas import best_effort_latex, conservative_latex, equation_number, inline_math_to_latex, validate_latex
from converter_core.mathpix import normalize_mmd


class FormulaTests(unittest.TestCase):
    def test_number(self):
        self.assertEqual(equation_number("E = mc^2 (12)"), "12")

    def test_flat_formula(self):
        result = conservative_latex("E = mc^2 (12)")
        self.assertEqual(result.latex, "E = mc^2")
        self.assertGreaterEqual(result.confidence, 0.8)

    def test_unicode(self):
        self.assertIn(r"\alpha", conservative_latex("α = 2 × β").latex)

    def test_validation(self):
        self.assertTrue(validate_latex(r"\frac{a}{b}"))
        self.assertFalse(validate_latex(r"\frac{a}{b"))

    def test_inline_obsidian_latex(self):
        self.assertEqual(inline_math_to_latex("Γ ≥ 2"), r"\Gamma \ge 2")

    def test_best_effort_removes_pdf_glyph_tokens(self):
        value = best_effort_latex("A (cid:16) + Γ")
        self.assertNotIn("cid:", value)
        self.assertIn(r"\Gamma", value)

    def test_mathpix_delimiters_become_obsidian_delimiters(self):
        value = normalize_mmd(r"Inline \(x^2\) and display \[\frac{a}{b}\]")
        self.assertIn("$x^2$", value)
        self.assertIn("$$\n\\frac{a}{b}\n$$", value)


if __name__ == "__main__":
    unittest.main()

