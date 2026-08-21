"""Material You (Material Design 3 / M3) Theme Engine for Socksicle.

Provides dynamic tonal color generation, cross-platform wallpaper
and Windows/Linux/macOS system accent color extraction, and curated
Material 3 preset palettes.
"""
import ctypes
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage

log = logging.getLogger("theme")

THEME_PRESETS = {
    "dynamic": "Dynamic (Wallpaper / System)",
    "lavender": "Amethyst Lavender",
    "ocean": "Oceanic Azure",
    "emerald": "Emerald Forest",
    "coral": "Sunset Coral",
    "amoled": "AMOLED Pure Dark",
}

PRESET_SEEDS = {
    "lavender": QColor("#D0BCFF"),
    "ocean": QColor("#4BA3E3"),
    "emerald": QColor("#4CAF50"),
    "coral": QColor("#FF7043"),
    "amoled": QColor("#9E9E9E"),
}


def _unwrap_dbus_variant(raw):
    """Unwrap nested QDBusVariant / QVariant wrappers to raw Python types."""
    while hasattr(raw, "variant"):
        raw = raw.variant()
    return raw


def _parse_portal_accent_color(raw) -> QColor | None:
    """Parse raw portal accent-color setting into a valid QColor."""
    if raw is None:
        return None
    raw = _unwrap_dbus_variant(raw)
    if isinstance(raw, QColor) and raw.isValid():
        return raw

    if isinstance(raw, (tuple, list)) and len(raw) >= 3:
        try:
            r, g, b = float(raw[0]), float(raw[1]), float(raw[2])
            if 0.0 <= r <= 1.0 and 0.0 <= g <= 1.0 and 0.0 <= b <= 1.0:
                return QColor.fromRgbF(r, g, b)
            elif 0 <= r <= 255 and 0 <= g <= 255 and 0 <= b <= 255:
                return QColor(int(r), int(g), int(b))
        except (ValueError, TypeError):
            pass

    if isinstance(raw, str):
        s = raw.strip()
        c = QColor(s)
        if c.isValid():
            return c

    return None


def read_portal_setting(namespace: str, key: str, bus=None):
    """Read a setting from org.freedesktop.portal.Settings via D-Bus session bus."""
    try:
        if bus is None:
            try:
                from PySide6.QtDBus import QDBusConnection
                bus = QDBusConnection.sessionBus()
            except (ImportError, AttributeError) as e:
                log.debug("PySide6.QtDBus unavailable for portal settings: %s", e)
                return None
        if not hasattr(bus, "isConnected") or not bus.isConnected():
            return None

        from PySide6.QtDBus import QDBusInterface
        iface = QDBusInterface(
            "org.freedesktop.portal.Desktop",
            "/org/freedesktop/portal/desktop",
            "org.freedesktop.portal.Settings",
            bus,
        )
        if not iface.isValid():
            return None

        reply = iface.call("Read", namespace, key)
        if not reply.isValid() or not reply.arguments():
            return None

        return _unwrap_dbus_variant(reply.arguments()[0])
    except Exception as e:
        log.debug("Failed to read portal setting %s/%s: %s", namespace, key, e)
        return None


def get_portal_accent_color(bus=None) -> QColor | None:
    """Read accent color from XDG Desktop Portal Settings."""
    try:
        raw = read_portal_setting("org.freedesktop.appearance", "accent-color", bus=bus)
        return _parse_portal_accent_color(raw)
    except Exception as e:
        log.debug("Failed to read portal accent color: %s", e)
        return None


def get_portal_color_scheme(bus=None) -> int | None:
    """Read color scheme from XDG Desktop Portal Settings.

    Returns:
        0: No preference
        1: Prefer dark
        2: Prefer light
        None: Unavailable / error
    """
    try:
        raw = read_portal_setting("org.freedesktop.appearance", "color-scheme", bus=bus)
        if raw is not None:
            return int(raw)
    except (ValueError, TypeError, Exception) as e:
        log.debug("Failed to read portal color scheme: %s", e)
    return None


class M3Theme:
    """Material 3 (Material You) Theme Manager."""

    def __init__(self, preset_key: str = "dynamic"):
        self.preset_key = preset_key
        self.is_amoled = preset_key == "amoled"
        self._init_defaults()
        self.apply_theme(preset_key)

    def _init_defaults(self):
        """Default Material 3 dark tokens (Lavender fallback)."""
        self.primary = "#D0BCFF"
        self.on_primary = "#381E72"
        self.primary_container = "#4F378B"
        self.on_primary_container = "#EADDFF"

        self.secondary = "#CCC2DC"
        self.on_secondary = "#332D41"
        self.secondary_container = "#4A4458"
        self.on_secondary_container = "#E8DEF8"

        self.tertiary = "#EFB8C8"
        self.on_tertiary = "#492532"
        self.tertiary_container = "#633B48"
        self.on_tertiary_container = "#FFD8E4"

        # Tonal Surface Levels (M3 Dark)
        self.surface = "#141218"
        self.surface_dim = "#141218"
        self.surface_bright = "#3B383E"
        self.surface_container_lowest = "#0F0D13"
        self.surface_container_low = "#1D1B20"
        self.surface_container = "#211F26"
        self.surface_container_high = "#2B2930"
        self.surface_container_highest = "#36343B"

        self.on_surface = "#E6E0E9"
        self.on_surface_variant = "#CAC4D0"
        self.outline = "#938F99"
        self.outline_variant = "#49454F"

        self.error = "#F2B8B5"
        self.on_error = "#601410"
        self.error_container = "#8C1D18"
        self.on_error_container = "#F9DEDC"

        self.success = "#81C784"
        self.on_success = "#1B5E20"
        self.success_container = "#2E7D32"

    def _get_linux_portal_accent_color(self, bus=None) -> QColor | None:
        """Read native Linux Accent Color from XDG Desktop Portal."""
        return get_portal_accent_color(bus=bus)

    def _get_linux_portal_color_scheme(self, bus=None) -> int | None:
        """Read native Linux Color Scheme preference from XDG Desktop Portal."""
        return get_portal_color_scheme(bus=bus)

    def apply_theme(self, preset_key: str = "dynamic"):
        """Apply a preset or extract dynamic color from desktop."""
        self.preset_key = preset_key
        self.is_amoled = preset_key == "amoled"

        if preset_key != "dynamic" and preset_key in PRESET_SEEDS:
            seed = PRESET_SEEDS[preset_key]
            self._current_seed_hex = seed.name().lower()
            self.generate_palette(seed)
            return

        # 1. Try Windows DWM accent color (native system theme)
        if sys.platform == "win32":
            accent = self._get_windows_accent_color()
            if accent:
                log.info("Applying dynamic theme from Windows accent color: %s", accent.name())
                self._current_seed_hex = accent.name().lower()
                self.generate_palette(accent)
                return

        # 2. Try Linux XDG Desktop Portal accent color
        if sys.platform.startswith("linux"):
            accent = self._get_linux_portal_accent_color()
            if accent:
                log.info("Applying dynamic theme from Linux XDG portal accent color: %s", accent.name())
                self._current_seed_hex = accent.name().lower()
                self.generate_palette(accent)
                return

        # 3. Try desktop wallpaper extraction
        wallpaper_path = self.get_wallpaper_path()
        if wallpaper_path and os.path.exists(wallpaper_path):
            color = self.extract_dominant_color(wallpaper_path)
            if color:
                log.info("Applying dynamic theme from wallpaper (%s): %s", wallpaper_path, color.name())
                self._current_seed_hex = color.name().lower()
                self.generate_palette(color)
                return

        # 4. Fallback to default Lavender M3
        seed = PRESET_SEEDS["lavender"]
        self._current_seed_hex = seed.name().lower()
        self.generate_palette(seed)

    def get_current_system_seed(self) -> QColor | None:
        """Get current dynamic system seed color without mutating theme."""
        if sys.platform == "win32":
            accent = self._get_windows_accent_color()
            if accent:
                return accent
        elif sys.platform.startswith("linux"):
            accent = self._get_linux_portal_accent_color()
            if accent:
                return accent
        wallpaper_path = self.get_wallpaper_path()
        if wallpaper_path and os.path.exists(wallpaper_path):
            color = self.extract_dominant_color(wallpaper_path)
            if color:
                return color
        return PRESET_SEEDS.get("lavender")

    def check_system_accent_changed(self) -> bool:
        """Check if Windows/system accent color or wallpaper changed in dynamic mode."""
        if getattr(self, "preset_key", "dynamic") != "dynamic":
            return False
        new_seed = self.get_current_system_seed()
        if new_seed:
            new_hex = new_seed.name().lower()
            if hasattr(self, "_current_seed_hex") and self._current_seed_hex and self._current_seed_hex != new_hex:
                log.info("System accent changed (%s -> %s). Hot-reloading theme!", self._current_seed_hex, new_hex)
                self.apply_theme("dynamic")
                return True
            self._current_seed_hex = new_hex
        return False

    def get_wallpaper_path(self) -> str | None:
        """Find the current desktop wallpaper across Windows, Linux, and macOS."""
        try:
            if sys.platform == "win32":
                return self._get_windows_wallpaper_path()
            elif sys.platform.startswith("linux"):
                return self._get_linux_wallpaper_path()
            elif sys.platform == "darwin":
                return self._get_macos_wallpaper_path()
        except Exception as e:
            log.debug("Failed to detect wallpaper path: %s", e)
        return None

    def _get_windows_accent_color(self) -> QColor | None:
        """Read native Windows Accent Color from DWM Registry."""
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\DWM"
            )
            val, _ = winreg.QueryValueEx(key, "AccentColor")
            # AccentColor is ABGR format uint32
            r = val & 0xFF
            g = (val >> 8) & 0xFF
            b = (val >> 16) & 0xFF
            return QColor(r, g, b)
        except Exception:
            try:
                import winreg
                key = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\DWM"
                )
                val, _ = winreg.QueryValueEx(key, "ColorizationColor")
                # ColorizationColor is ARGB
                a = (val >> 24) & 0xFF
                r = (val >> 16) & 0xFF
                g = (val >> 8) & 0xFF
                b = val & 0xFF
                return QColor(r, g, b)
            except Exception:
                pass
        return None

    def _get_windows_wallpaper_path(self) -> str | None:
        """Query wallpaper via Windows SystemParametersInfo / Registry / Transcoded cache."""
        # 1. Try Win32 SystemParametersInfoW
        try:
            buf = ctypes.create_unicode_buffer(512)
            # SPI_GETDESKWALLPAPER = 0x0073
            if ctypes.windll.user32.SystemParametersInfoW(0x0073, 512, buf, 0):
                path = buf.value
                if path and os.path.exists(path):
                    return path
        except Exception as e:
            log.debug("SystemParametersInfoW failed: %s", e)

        # 2. Try Registry HKCU\Control Panel\Desktop\Wallpaper
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop")
            val, _ = winreg.QueryValueEx(key, "Wallpaper")
            if val and os.path.exists(val):
                return val
        except Exception:
            pass

        # 3. Try cached TranscodedWallpaper in AppData
        try:
            appdata = os.environ.get("APPDATA", "")
            if appdata:
                transcoded = Path(appdata) / "Microsoft" / "Windows" / "Themes" / "TranscodedWallpaper"
                if transcoded.exists():
                    return str(transcoded)
        except Exception:
            pass
        return None

    def _get_linux_wallpaper_path(self) -> str | None:
        """Find wallpaper across GNOME, KDE Plasma, XFCE, Hyprland, Sway, and feh."""
        # 1. GNOME / Cinnamon
        for schema, key in (
            ("org.gnome.desktop.background", "picture-uri-dark"),
            ("org.gnome.desktop.background", "picture-uri"),
            ("org.cinnamon.desktop.background", "picture-uri"),
        ):
            try:
                out = subprocess.check_output(["gsettings", "get", schema, key], stderr=subprocess.DEVNULL).decode().strip().strip("'\"")
                if out and out != "''":
                    if out.startswith("file://"):
                        return unquote(urlparse(out).path)
                    if os.path.exists(out):
                        return out
            except Exception:
                pass

        # 2. KDE Plasma config
        try:
            plasma_cfg = Path.home() / ".config" / "plasma-org.kde.plasma.desktop-appletsrc"
            if plasma_cfg.exists():
                with open(plasma_cfg, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        if line.strip().startswith("Image="):
                            p = line.strip().split("=", 1)[1].strip()
                            if p.startswith("file://"):
                                p = unquote(urlparse(p).path)
                            if os.path.exists(p):
                                return p
        except Exception:
            pass

        # 3. Sway / Hyprland / feh (.fehbg / hyprpaper.conf)
        try:
            fehbg = Path.home() / ".fehbg"
            if fehbg.exists():
                with open(fehbg, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                    m = re.search(r"'(.*?)'", content) or re.search(r'"(.*?)"', content)
                    if m and os.path.exists(m.group(1)):
                        return m.group(1)
        except Exception:
            pass

        return None

    def _get_macos_wallpaper_path(self) -> str | None:
        """Query desktop picture via AppleScript on macOS."""
        try:
            cmd = ["osascript", "-e", 'tell application "Finder" to get POSIX path of (get desktop picture as alias)']
            out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode().strip()
            if out and os.path.exists(out):
                return out
        except Exception:
            pass
        return None

    def extract_dominant_color(self, image_path: str) -> QColor | None:
        """Extract a vibrant seed color using saturation & chroma scoring."""
        try:
            img = QImage(image_path)
            if img.isNull():
                return None

            # Scale to 64x64 for analysis
            small = img.scaled(64, 64, aspectMode=Qt.IgnoreAspectRatio, mode=Qt.SmoothTransformation)

            best_score = -1.0
            best_color = None

            for y in range(small.height()):
                for x in range(small.width()):
                    c = small.pixelColor(x, y)
                    sat = c.saturationF()
                    light = c.lightnessF()

                    # Filter out washed out or dark/black pixels
                    if 0.25 <= light <= 0.80 and sat >= 0.20:
                        # Score combines saturation and distance from extreme lightness
                        lightness_penalty = 1.0 - abs(light - 0.55) * 1.5
                        score = sat * max(0.2, lightness_penalty)
                        if score > best_score:
                            best_score = score
                            best_color = c

            if best_color:
                return best_color

            # Fallback to center region average
            center = small.pixelColor(32, 32)
            if center.lightnessF() > 0.1:
                return center

            return img.scaled(1, 1).pixelColor(0, 0)
        except Exception as e:
            log.debug("Error extracting dominant color: %s", e)
            return None

    def generate_palette(self, seed: QColor):
        """Generate Material You (M3) tonal palette from seed color."""
        h, s, l, a = seed.getHslF()

        # Helper to create tone with specific lightness and saturation factor
        def make_tone(lightness: float, sat_mult: float = 1.0, hue_shift: float = 0.0) -> QColor:
            adjusted_h = (h + hue_shift) % 1.0
            adjusted_s = max(0.0, min(1.0, s * sat_mult))
            return QColor.fromHslF(adjusted_h, adjusted_s, max(0.0, min(1.0, lightness)), a)

        # Primary (Tone 80 for Dark Mode)
        self.primary = make_tone(0.80, sat_mult=1.0).name()
        self.on_primary = make_tone(0.20, sat_mult=1.0).name()
        self.primary_container = make_tone(0.30, sat_mult=0.85).name()
        self.on_primary_container = make_tone(0.92, sat_mult=0.90).name()

        # Secondary (Desaturated version)
        self.secondary = make_tone(0.78, sat_mult=0.45).name()
        self.on_secondary = make_tone(0.22, sat_mult=0.45).name()
        self.secondary_container = make_tone(0.28, sat_mult=0.40).name()
        self.on_secondary_container = make_tone(0.90, sat_mult=0.40).name()

        # Tertiary (Complementary Hue shifted +30 degrees)
        self.tertiary = make_tone(0.82, sat_mult=0.75, hue_shift=30.0 / 360.0).name()
        self.on_tertiary = make_tone(0.20, sat_mult=0.75, hue_shift=30.0 / 360.0).name()
        self.tertiary_container = make_tone(0.32, sat_mult=0.70, hue_shift=30.0 / 360.0).name()
        self.on_tertiary_container = make_tone(0.92, sat_mult=0.70, hue_shift=30.0 / 360.0).name()

        # Surfaces & Tonal Elevations
        if self.is_amoled:
            self.surface = "#000000"
            self.surface_dim = "#000000"
            self.surface_bright = "#1A1A1A"
            self.surface_container_lowest = "#000000"
            self.surface_container_low = "#0A0A0A"
            self.surface_container = "#121212"
            self.surface_container_high = "#1C1C1C"
            self.surface_container_highest = "#262626"
            self.surface_variant = "#1E1E1E"
        else:
            base_black = QColor("#0E0E12")
            # Tint surfaces slightly with seed hue
            self.surface = self._mix(base_black, seed, 0.04).name()
            self.surface_dim = self._mix(base_black, seed, 0.03).name()
            self.surface_bright = self._mix(QColor("#2C2C34"), seed, 0.06).name()
            self.surface_container_lowest = self._mix(QColor("#08080A"), seed, 0.03).name()
            self.surface_container_low = self._mix(QColor("#14141A"), seed, 0.05).name()
            self.surface_container = self._mix(QColor("#1A1A22"), seed, 0.07).name()
            self.surface_container_high = self._mix(QColor("#22222C"), seed, 0.09).name()
            self.surface_container_highest = self._mix(QColor("#2A2A36"), seed, 0.12).name()
            self.surface_variant = self.surface_container_highest

        # Text & Outlines
        self.on_surface = "#ECE6F0"
        self.on_surface_variant = "#CBC4CF"
        self.outline = self._mix(QColor("#8C8894"), seed, 0.15).name()
        self.outline_variant = self._mix(QColor("#44424B"), seed, 0.15).name()

        # Status & Feedback
        self.error = "#FFB4AB"
        self.on_error = "#690005"
        self.error_container = "#93000A"
        self.on_error_container = "#FFDAD6"

        self.success = "#85D996"
        self.on_success = "#003914"
        self.success_container = "#005320"

    def _mix(self, c1: QColor, c2: QColor, ratio: float) -> QColor:
        """Blend two QColors with a linear ratio."""
        r = c1.red() * (1 - ratio) + c2.red() * ratio
        g = c1.green() * (1 - ratio) + c2.green() * ratio
        b = c1.blue() * (1 - ratio) + c2.blue() * ratio
        return QColor(int(r), int(g), int(b))

    def get_button_style(self, variant="filled") -> str:
        """Return Material 3 button stylesheet for various roles."""
        if variant == "filled":
            return f"""
                QPushButton {{
                    background-color: {self.primary};
                    color: {self.on_primary};
                    border-radius: 20px;
                    padding: 0px 24px;
                    height: 40px;
                    font-size: 14px;
                    font-weight: 600;
                    border: none;
                    outline: none;
                }}
                QPushButton:hover {{
                    background-color: {self.on_surface_variant};
                    color: {self.surface};
                }}
                QPushButton:pressed {{
                    background-color: {self.outline};
                }}
                QPushButton:disabled {{
                    background-color: rgba(255, 255, 255, 0.12);
                    color: rgba(255, 255, 255, 0.38);
                }}
            """
        elif variant == "tonal":
            return f"""
                QPushButton {{
                    background-color: {self.secondary_container};
                    color: {self.on_secondary_container};
                    border-radius: 14px;
                    padding: 0px 16px;
                    height: 36px;
                    font-size: 13px;
                    font-weight: 600;
                    border: none;
                    outline: none;
                }}
                QPushButton:hover {{
                    background-color: {self.surface_container_highest};
                }}
                QPushButton:pressed {{
                    background-color: {self.primary_container};
                    color: {self.on_primary_container};
                }}
            """
        elif variant == "text":
            return f"""
                QPushButton {{
                    color: {self.primary};
                    background: transparent;
                    border-radius: 18px;
                    padding: 0px 14px;
                    height: 36px;
                    font-size: 13px;
                    font-weight: 600;
                    border: none;
                    outline: none;
                }}
                QPushButton:hover {{
                    background-color: rgba(255, 255, 255, 0.08);
                }}
                QPushButton:pressed {{
                    background-color: rgba(255, 255, 255, 0.14);
                }}
            """
        elif variant == "outlined":
            return f"""
                QPushButton {{
                    background: transparent;
                    color: {self.primary};
                    border: 1px solid {self.outline_variant};
                    border-radius: 18px;
                    padding: 0px 16px;
                    height: 36px;
                    font-size: 13px;
                    font-weight: 600;
                    outline: none;
                }}
                QPushButton:hover {{
                    background-color: rgba(255, 255, 255, 0.06);
                    border-color: {self.primary};
                }}
            """
        return ""

