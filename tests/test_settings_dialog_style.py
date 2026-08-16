"""Ensure the Settings dialog combo-box stylesheet paints every region opaque.

On Linux (X11 without a compositor, and some Wayland popups) unpainted
stylesheet regions render as transparent holes over the ARGB backing store,
which made QComboBox dropdowns blank.  Every sub-region of the combo (the
drop-down button, the arrow, the popup frame and the item list) must carry an
explicit opaque background.
"""
from PySide6.QtWidgets import QWidget

from utils.theme import M3Theme
from ui.settings_dialog import SettingsDialog


class _FakeParent(QWidget):
    def __init__(self):
        super().__init__()
        self.settings = {}


def _dialog_stylesheet(qapp):
    parent = _FakeParent()
    dlg = SettingsDialog(parent=parent, theme=M3Theme(preset_key="lavender"))
    return dlg.container.styleSheet()


def _rule(stylesheet, selector):
    start = stylesheet.index(selector)
    end = stylesheet.index("}", start)
    return stylesheet[start:end]


def test_drop_down_has_opaque_background(qapp):
    ss = _dialog_stylesheet(qapp)
    rule = _rule(ss, "QComboBox::drop-down {")
    assert "background-color:" in rule
    assert "border: none;" in rule
    assert "border-left: 1px solid" in rule
    assert "border-top-right-radius: 10px;" in rule
    assert "border-bottom-right-radius: 10px;" in rule


def test_drop_down_hover_and_pressed_stay_opaque(qapp):
    ss = _dialog_stylesheet(qapp)
    for selector in ("QComboBox::drop-down:hover {", "QComboBox::drop-down:pressed {"):
        rule = _rule(ss, selector)
        assert "background-color:" in rule


def test_popup_list_is_opaque(qapp):
    ss = _dialog_stylesheet(qapp)
    view = _rule(ss, "QComboBox QAbstractItemView {")
    assert "background-color:" in view
    assert "selection-background-color:" in view
    assert "selection-color:" in view
    frame = _rule(ss, "QComboBox QFrame {")
    assert "background-color:" in frame


def test_container_rule_is_scoped(qapp):
    ss = _dialog_stylesheet(qapp)
    assert "QFrame#SettingsContainer {" in ss
    assert "QComboBox QAbstractItemView {" in ss