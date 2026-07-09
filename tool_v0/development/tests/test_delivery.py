import unittest

from converter_core.delivery import _format_duration, _slug


class DeliveryTimingTests(unittest.TestCase):
    def test_formats_seconds(self):
        self.assertEqual(_format_duration(12.34), "12.3 秒")

    def test_formats_minutes(self):
        self.assertEqual(_format_duration(497), "8 分 17 秒")

    def test_formats_hours(self):
        self.assertEqual(_format_duration(3671), "1 小时 1 分 11 秒")

    def test_figure_slug_is_short_and_drops_filler_words(self):
        self.assertEqual(
            _slug("(a) Magnetic-resonance linewidth of the atom under pumping"),
            "Magnetic_resonance_linewidth_atom_pumping",
        )


if __name__ == "__main__":
    unittest.main()

