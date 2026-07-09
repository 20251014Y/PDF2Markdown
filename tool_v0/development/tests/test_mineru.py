import unittest

from converter_core.mineru import _normalize, _quality_check


class MinerUPostprocessTests(unittest.TestCase):
    def test_obsidian_normalization(self):
        value = _normalize("# II. RESULTS\n\n$[1, 2]$\n\n![](images/a.png)")
        self.assertIn("## II. RESULTS", value)
        self.assertIn("[1, 2]", value)
        self.assertNotIn("$[", value)
        self.assertIn("assets/figures/a.png", value)

    def test_removes_generated_chart_details(self):
        value = _normalize("Before\n<details>\n<summary>heatmap</summary>\n| fake | table |\n</details>\nAfter")
        self.assertEqual(value, "Before\n\nAfter\n")
        self.assertNotIn("fake", value)

    def test_converts_html_table_for_obsidian(self):
        value = _normalize("<table><tr><td>A</td><td>$x$</td></tr><tr><td>B</td><td>$y$</td></tr></table>")
        self.assertIn("| A | $x$ |", value)
        self.assertIn("| B | $y$ |", value)
        self.assertNotIn("<td>", value)

    def test_rejects_corrupt_glyphs(self):
        errors, _, _ = _quality_check("text \ufffd (cid:16) \ue000")
        self.assertEqual(len(errors), 3)

    def test_accepts_balanced_formula(self):
        errors, _, count = _quality_check("$$\nE = mc^{2} \\tag{1}\n$$")
        self.assertEqual(errors, [])
        self.assertEqual(count, 1)

    def test_flags_unbalanced_formula_for_review_without_failing_document(self):
        errors, warnings, count = _quality_check("$$\nE = mc^{2 \\tag{1}\n$$")
        self.assertEqual(errors, [])
        self.assertEqual(count, 1)
        self.assertTrue(any("花括号不平衡" in item for item in warnings))

    def test_rejects_unbalanced_inline_math(self):
        errors, _, _ = _quality_check("Text with $x^2 and no close")
        self.assertIn("行内公式 $ 定界符不闭合", errors)


if __name__ == "__main__":
    unittest.main()

