"""Tests for font_utils and Windows-specific Noto Color Emoji font integration."""
import sys
from utils.font_utils import init_app_fonts, get_emoji_font_family
import utils.font_utils as fu


def test_init_app_fonts_on_windows(qapp, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    fu._EMOJI_FONT_FAMILY = None
    family = init_app_fonts()
    assert family == "Noto Color Emoji"
    assert get_emoji_font_family() == "Noto Color Emoji"


def test_init_app_fonts_on_linux_noops(qapp, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    fu._EMOJI_FONT_FAMILY = None
    family = init_app_fonts()
    assert family is None
    assert get_emoji_font_family() is None
