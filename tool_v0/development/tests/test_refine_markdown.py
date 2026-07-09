import unittest

from converter_core.refine_markdown import repair_vert_letter_spacing, remove_display_formula_padding


class RefineMarkdownTests(unittest.TestCase):
    def test_removes_blank_lines_around_display_math(self):
        source = "Text\n\n$$\nx^2\n$$\n\nMore\n"
        self.assertEqual(remove_display_formula_padding(source), "Text\n$$\nx^2\n$$\nMore\n")

    def test_repairs_vert_followed_by_any_ascii_letter(self):
        source = r"$\vertP\vert+\vert x\vert+\lvert Q\rvert$"
        expected = r"$\vert P\vert+\vert x\vert+\lvert Q\rvert$"
        self.assertEqual(repair_vert_letter_spacing(source), expected)


if __name__ == "__main__":
    unittest.main()

