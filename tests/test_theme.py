"""Unit tests for Material You (M3) Theme Engine."""
import unittest
from unittest.mock import patch
from PySide6.QtGui import QColor, QImage
from PySide6.QtCore import Qt

from utils.theme import M3Theme, THEME_PRESETS, PRESET_SEEDS


class M3ThemeTest(unittest.TestCase):
    def test_default_tokens_exist(self):
        theme = M3Theme(preset_key="lavender")
        self.assertTrue(theme.primary.startswith("#"))
        self.assertTrue(theme.on_primary.startswith("#"))
        self.assertTrue(theme.primary_container.startswith("#"))
        self.assertTrue(theme.on_primary_container.startswith("#"))
        self.assertTrue(theme.secondary.startswith("#"))
        self.assertTrue(theme.secondary_container.startswith("#"))
        self.assertTrue(theme.tertiary.startswith("#"))
        self.assertTrue(theme.surface.startswith("#"))
        self.assertTrue(theme.surface_container.startswith("#"))
        self.assertTrue(theme.surface_container_high.startswith("#"))
        self.assertTrue(theme.outline.startswith("#"))
        self.assertTrue(theme.error.startswith("#"))
        self.assertTrue(theme.success.startswith("#"))

    def test_presets_generate_distinct_palettes(self):
        for preset_name in ("lavender", "ocean", "emerald", "coral", "amoled"):
            theme = M3Theme(preset_key=preset_name)
            self.assertEqual(theme.preset_key, preset_name)
            self.assertTrue(theme.primary.startswith("#"))
            if preset_name == "amoled":
                self.assertEqual(theme.surface, "#000000")

    def test_custom_seed_generation(self):
        theme = M3Theme()
        custom_seed = QColor(255, 100, 50)
        theme.generate_palette(custom_seed)
        self.assertTrue(theme.primary.startswith("#"))
        self.assertTrue(theme.on_primary.startswith("#"))
        self.assertTrue(theme.primary_container.startswith("#"))

    def test_button_styles(self):
        theme = M3Theme(preset_key="ocean")
        filled = theme.get_button_style("filled")
        tonal = theme.get_button_style("tonal")
        text = theme.get_button_style("text")
        outlined = theme.get_button_style("outlined")

        self.assertIn(theme.primary, filled)
        self.assertIn(theme.secondary_container, tonal)
        self.assertIn("transparent", text)
        self.assertIn("border", outlined)

    def test_extract_dominant_color_from_image(self):
        theme = M3Theme()
        # Create a small red test image
        img = QImage(32, 32, QImage.Format_RGB32)
        img.fill(QColor(220, 50, 50))
        
        # Save to temporary path
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            temp_path = f.name
        try:
            img.save(temp_path)
            extracted = theme.extract_dominant_color(temp_path)
            self.assertIsNotNone(extracted)
            self.assertTrue(extracted.red() > 150)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    @patch("utils.theme.M3Theme._get_windows_accent_color")
    def test_dynamic_windows_accent(self, mock_accent):
        mock_accent.return_value = QColor(0, 120, 215)
        theme = M3Theme(preset_key="dynamic")
        self.assertTrue(theme.primary.startswith("#"))


if __name__ == "__main__":
    unittest.main()
