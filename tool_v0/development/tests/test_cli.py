import unittest

from converter_core.cli import main


class CliTests(unittest.TestCase):
    def test_invalid_dpi(self):
        self.assertEqual(main(["missing.pdf", "-o", "out", "--dpi", "10"]), 2)


if __name__ == "__main__":
    unittest.main()


