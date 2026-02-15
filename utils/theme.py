import subprocess
import os
import sys
from urllib.parse import unquote, urlparse
from PySide6.QtGui import QColor, QImage

class M3Theme:
    def __init__(self):
        # Default fallback (Purple M3)
        self.primary = "#D0BCFF"
        self.on_primary = "#381E72"
        self.primary_container = "#4F378B"
        self.on_primary_container = "#EADDFF"
        self.secondary_container = "#4A4458"
        self.on_secondary_container = "#E8DEF8"
        self.surface = "#1C1B1F"
        self.surface_variant = "#49454F"
        self.on_surface = "#E6E1E5"
        self.on_surface_variant = "#CAC4D0"
        self.outline = "#938F99"
        self.error = "#F2B8B5"
        
        # Try to adapt to wallpaper
        self.apply_wallpaper_theme()

    def apply_wallpaper_theme(self):
        path = self.get_wallpaper_path()
        if path and os.path.exists(path):
            color = self.extract_dominant_color(path)
            if color:
                self.generate_palette(color)

    def get_wallpaper_path(self):
        """Attempt to find the current wallpaper path (GNOME/Dark preferred)."""
        try:
            # Try GNOME Dark Mode Wallpaper first
            cmd = ["gsettings", "get", "org.gnome.desktop.background", "picture-uri-dark"]
            out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode().strip().strip("'")
            
            # If empty or default, try light mode
            if not out or out == "''":
                cmd = ["gsettings", "get", "org.gnome.desktop.background", "picture-uri"]
                out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode().strip().strip("'")
            
            # Parse file:// URI
            if out.startswith("file://"):
                path = unquote(urlparse(out).path)
                return path
            return out
        except:
            return None

    def extract_dominant_color(self, image_path):
        """
        Extract a vibrant/dominant color from the image using QImage.
        We scale it down to 1x1 to get the average, but to avoid muddy colors,
        we might look at the center or specific regions.
        Simple approach: Scale to 50x50 and find the most saturated pixel.
        """
        try:
            img = QImage(image_path)
            if img.isNull():
                return None
            
            # Scale down significantly to analyze
            small = img.scaled(50, 50, aspectMode=sys.modules['PySide6.QtCore'].Qt.IgnoreAspectRatio)
            
            max_saturation = -1
            best_color = None
            
            # Find the most saturated pixel to avoid grey/muddy averages
            for y in range(small.height()):
                for x in range(small.width()):
                    c = small.pixelColor(x, y)
                    # We prefer colors with reasonable brightness
                    if c.saturation() > max_saturation and 0.3 < c.lightnessF() < 0.8:
                        max_saturation = c.saturation()
                        best_color = c
            
            if best_color:
                return best_color
            
            # Fallback to simple average if no saturated pixel found
            avg = img.scaled(1, 1).pixelColor(0, 0)
            return avg
        except:
            return None

    def generate_palette(self, seed_color):
        """Generate a Dark M3 palette from a seed QColor."""
        
        # Helper to adjust lightness
        def tone(c, lightness):
            h, s, l, a = c.getHslF()
            return QColor.fromHslF(h, s, lightness, a)

        # 1. Primary: High lightness (pastel) for Dark Mode
        self.primary = tone(seed_color, 0.80).name()
        
        # 2. On Primary: Dark text
        self.on_primary = tone(seed_color, 0.20).name()
        
        # 3. Primary Container: Darker but colorful
        self.primary_container = tone(seed_color, 0.30).name()
        self.on_primary_container = tone(seed_color, 0.90).name()
        
        # 4. Secondary Container: Desaturated version of primary container
        sec_seed = QColor(seed_color)
        h, s, l, a = sec_seed.getHslF()
        sec_seed = QColor.fromHslF(h, max(0, s - 0.3), l, a) # Desaturate
        self.secondary_container = tone(sec_seed, 0.30).name()
        self.on_secondary_container = tone(sec_seed, 0.90).name()
        
        # 5. Surface: Very dark, slightly tinted with seed
        # Mix Black with 5% of seed color
        base = QColor("#121212")
        self.surface = self.mix_colors(base, seed_color, 0.05).name()
        
        # 6. Surface Variant: Slightly lighter
        self.surface_variant = self.mix_colors(base, seed_color, 0.12).name()
        
        # 7. Text colors
        self.on_surface = "#E6E1E5"
        self.on_surface_variant = "#CAC4D0"
        self.outline = "#938F99"

    def mix_colors(self, c1, c2, ratio):
        """Mix two QColors. ratio 0.0 = c1, 1.0 = c2"""
        r = c1.red() * (1 - ratio) + c2.red() * ratio
        g = c1.green() * (1 - ratio) + c2.green() * ratio
        b = c1.blue() * (1 - ratio) + c2.blue() * ratio
        return QColor(int(r), int(g), int(b))

    def get_button_style(self, variant="filled"):
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
                }}
                QPushButton:hover {{ background-color: {self.on_surface_variant}; color: {self.surface}; }}
                QPushButton:pressed {{ background-color: {self.outline}; }}
            """
        elif variant == "tonal":
            return f"""
                QPushButton {{
                    background-color: {self.secondary_container};
                    color: {self.on_secondary_container};
                    border-radius: 12px;
                    padding: 0px 16px;
                    height: 36px;
                    font-size: 13px;
                    font-weight: 600;
                    border: none;
                }}
                QPushButton:hover {{ background-color: {self.surface_variant}; }}
            """
        elif variant == "text":
            return f"""
                QPushButton {{
                    color: {self.primary};
                    background: transparent;
                    border-radius: 20px;
                    padding: 0px 12px;
                    height: 40px;
                    font-size: 14px;
                    font-weight: 600;
                    border: none;
                }}
                QPushButton:hover {{ background-color: rgba(255, 255, 255, 0.08); }}
            """
