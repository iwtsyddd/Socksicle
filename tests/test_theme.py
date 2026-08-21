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


class XDGPortalThemeTest(unittest.TestCase):
    """Unit tests for FreeDesktop XDG Desktop Portal theme integration."""

    @patch("utils.theme.read_portal_setting")
    def test_portal_color_scheme_dark(self, mock_read):
        mock_read.return_value = 1
        from utils.theme import get_portal_color_scheme
        self.assertEqual(get_portal_color_scheme(), 1)

    @patch("utils.theme.read_portal_setting")
    def test_portal_color_scheme_light(self, mock_read):
        mock_read.return_value = 2
        from utils.theme import get_portal_color_scheme
        self.assertEqual(get_portal_color_scheme(), 2)

    @patch("utils.theme.read_portal_setting")
    def test_portal_color_scheme_no_preference(self, mock_read):
        mock_read.return_value = 0
        from utils.theme import get_portal_color_scheme
        self.assertEqual(get_portal_color_scheme(), 0)

    @patch("utils.theme.read_portal_setting")
    def test_portal_color_scheme_error(self, mock_read):
        mock_read.return_value = None
        from utils.theme import get_portal_color_scheme
        self.assertIsNone(get_portal_color_scheme())

    @patch("utils.theme.read_portal_setting")
    def test_portal_accent_color_float_tuple(self, mock_read):
        mock_read.return_value = (0.2, 0.6, 1.0)
        from utils.theme import get_portal_accent_color
        color = get_portal_accent_color()
        self.assertIsNotNone(color)
        self.assertTrue(color.isValid())
        self.assertAlmostEqual(color.redF(), 0.2, places=2)
        self.assertAlmostEqual(color.greenF(), 0.6, places=2)
        self.assertAlmostEqual(color.blueF(), 1.0, places=2)

    @patch("utils.theme.read_portal_setting")
    def test_portal_accent_color_int_tuple(self, mock_read):
        mock_read.return_value = (50, 150, 250)
        from utils.theme import get_portal_accent_color
        color = get_portal_accent_color()
        self.assertIsNotNone(color)
        self.assertTrue(color.isValid())
        self.assertEqual(color.red(), 50)
        self.assertEqual(color.green(), 150)
        self.assertEqual(color.blue(), 250)

    @patch("utils.theme.read_portal_setting")
    def test_portal_accent_color_hex_string(self, mock_read):
        mock_read.return_value = "#FF5722"
        from utils.theme import get_portal_accent_color
        color = get_portal_accent_color()
        self.assertIsNotNone(color)
        self.assertEqual(color.name().upper(), "#FF5722")

    @patch("utils.theme.read_portal_setting")
    def test_portal_accent_color_invalid(self, mock_read):
        mock_read.return_value = "invalid_color"
        from utils.theme import get_portal_accent_color
        color = get_portal_accent_color()
        self.assertIsNone(color)

    def test_read_portal_setting_with_mock_bus(self):
        from utils.theme import read_portal_setting
        from unittest.mock import MagicMock

        fake_bus = MagicMock()
        fake_bus.isConnected.return_value = True

        with patch("PySide6.QtDBus.QDBusInterface") as mock_iface_cls:
            mock_iface = MagicMock()
            mock_iface.isValid.return_value = True
            mock_reply = MagicMock()
            mock_reply.isValid.return_value = True
            mock_reply.arguments.return_value = [1]
            mock_iface.call.return_value = mock_reply
            mock_iface_cls.return_value = mock_iface

            val = read_portal_setting("org.freedesktop.appearance", "color-scheme", bus=fake_bus)
            self.assertEqual(val, 1)
            mock_iface.call.assert_called_once_with("Read", "org.freedesktop.appearance", "color-scheme")

    def test_read_portal_setting_bus_disconnected(self):
        from utils.theme import read_portal_setting
        from unittest.mock import MagicMock

        fake_bus = MagicMock()
        fake_bus.isConnected.return_value = False
        val = read_portal_setting("org.freedesktop.appearance", "color-scheme", bus=fake_bus)
        self.assertIsNone(val)

    @patch("sys.platform", "linux")
    @patch("utils.theme.M3Theme._get_linux_portal_accent_color")
    def test_linux_dynamic_applies_portal_accent(self, mock_portal_accent):
        mock_portal_accent.return_value = QColor("#E91E63")
        theme = M3Theme(preset_key="dynamic")
        self.assertEqual(theme.preset_key, "dynamic")
        self.assertTrue(theme.primary.startswith("#"))
        mock_portal_accent.assert_called()

    @patch("sys.platform", "linux")
    @patch("utils.theme.M3Theme._get_linux_portal_accent_color", return_value=None)
    @patch("utils.theme.M3Theme.get_wallpaper_path", return_value=None)
    def test_linux_dynamic_fallback_to_lavender(self, mock_wp, mock_portal):
        theme = M3Theme(preset_key="dynamic")
        self.assertEqual(theme.preset_key, "dynamic")
        self.assertEqual(theme._current_seed_hex, PRESET_SEEDS["lavender"].name().lower())

    @patch("sys.platform", "linux")
    @patch("utils.theme.M3Theme._get_linux_portal_accent_color")
    def test_check_system_accent_changed_on_linux(self, mock_portal_accent):
        mock_portal_accent.return_value = QColor("#00FF00")
        theme = M3Theme(preset_key="dynamic")
        self.assertFalse(theme.check_system_accent_changed())

        # Simulate user changing accent color in system settings
        mock_portal_accent.return_value = QColor("#FF0000")
        self.assertTrue(theme.check_system_accent_changed())

    @patch("utils.platform_utils.is_linux", return_value=True)
    @patch("utils.theme.get_portal_color_scheme")
    def test_platform_utils_linux_dark_mode(self, mock_scheme, mock_is_linux):
        from utils.platform_utils import linux_dark_mode
        mock_scheme.return_value = 1
        self.assertTrue(linux_dark_mode())

        mock_scheme.return_value = 2
        self.assertFalse(linux_dark_mode())

        mock_scheme.return_value = 0
        self.assertIsNone(linux_dark_mode())

        mock_scheme.return_value = None
        self.assertIsNone(linux_dark_mode())


if __name__ == "__main__":
    unittest.main()
