import unittest

from converter_core.user_customizations import apply_user_customizations


class UserCustomizationTests(unittest.TestCase):
    def test_prefers_unicode_copyright_for_mineru_latex_variants(self):
        source = (
            r"$X^{\circledcirc}$ "
            r"$X^{\text{\circledcirc}}$ "
            r"$X^{\circledast}$ "
            r"$X^{\text{\circledast}}$ "
            r"$H^{\text{\textcircled{C}}}$ "
            r"$H^{\textcircled{c}}$ "
            r"$S_x^{\textcircle{C}}$ "
            r"$S_x^{\text{©}}$"
        )
        expected = r"$X^{©}$ $X^{©}$ $X^{©}$ $X^{©}$ $H^{©}$ $H^{©}$ $S_x^{©}$ $S_x^{©}$"
        self.assertEqual(apply_user_customizations(source), expected)


if __name__ == "__main__":
    unittest.main()
