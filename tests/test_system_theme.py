"""System appearance changes, inherited palette roles and accent contrast."""
import os
import unittest
from collections import Counter
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QObject, Qt, Signal, QCoreApplication, QEvent, QTimer, QPoint
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QWidget
from Libs import fluent_ui as ui


class AppearanceHints(QObject):
    colorSchemeChanged = Signal(Qt.ColorScheme)

    def __init__(self):
        super().__init__()
        self.scheme = Qt.ColorScheme.Light

    def colorScheme(self):
        return self.scheme

    def change(self, scheme):
        self.scheme = scheme
        self.colorSchemeChanged.emit(scheme)


class Desktop(QObject):
    paletteChanged = Signal(QPalette)

    def __init__(self):
        super().__init__()
        self.hints = AppearanceHints()
        self.colors = QPalette()
        self.colors.setColor(QPalette.Accent, QColor('#bf0077'))

    def styleHints(self):
        return self.hints

    def palette(self):
        return self.colors


def luminance(color):
    channels = (color.redF(), color.greenF(), color.blueF())
    linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in channels]
    return sum(v * w for v, w in zip(linear, (0.2126, 0.7152, 0.0722)))


class ThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.mode = ui.qconfig.get(ui.qconfig.themeMode)
        self.accent = QColor(ui.qconfig.get(ui.qconfig.themeColor))
        self.palette = QPalette(self.app.palette())
        self.addCleanup(self.restore)

    def restore(self):
        ui.setTheme(self.mode, save=False)
        ui.setThemeColor(self.accent, save=False)
        self.app.setPalette(self.palette)
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def desktop(self):
        desktop = Desktop()
        controller = ui.SystemTheme(desktop)
        self.addCleanup(desktop.deleteLater)
        self.addCleanup(controller.timer.stop)
        return desktop, controller

    def test_theme_and_accent_changes_are_coalesced_without_palette_feedback(self):
        desktop, controller = self.desktop()
        with patch.object(ui, 'setTheme') as theme, patch.object(ui, 'setThemeColor') as accent, \
             patch.object(ui, '_apply_palette', side_effect=lambda: desktop.paletteChanged.emit(desktop.colors)) as apply:
            desktop.hints.change(Qt.ColorScheme.Dark)
            desktop.hints.change(Qt.ColorScheme.Light)
            desktop.hints.change(Qt.ColorScheme.Dark)
            desktop.colors.setColor(QPalette.Accent, QColor('#00aa55'))
            desktop.paletteChanged.emit(desktop.colors)
            self.assertTrue(controller.timer.isActive())
            self.app.processEvents()
            theme.assert_called_once_with(ui.Theme.DARK, save=False, lazy=True)
            accent.assert_called_once_with(QColor('#00aa55'), save=False, lazy=True)
            apply.assert_called_once()
            self.app.processEvents()
            self.assertFalse(controller.timer.isActive())
            self.assertFalse(controller.applying)
            apply.assert_called_once()

    def test_changing_other_palette_roles_does_not_replace_system_accent(self):
        desktop, controller = self.desktop()
        desktop.colors.setColor(QPalette.Highlight, QColor('#ffff00'))
        desktop.paletteChanged.emit(desktop.colors)
        self.assertFalse(controller.timer.isActive())
        self.assertEqual(controller.accent, QColor('#bf0077'))

    def test_native_accent_stays_inherited_after_app_palette_is_applied(self):
        native = QPalette(self.app.palette())
        # Simulate a fresh default palette with all roles inherited.
        native.setResolveMask(0)
        self.app.setPalette(native)
        ui._apply_palette()
        self.assertFalse(self.app.palette().isBrushSet(QPalette.Active, QPalette.Accent))
        self.assertEqual(self.app.palette().color(QPalette.Accent), native.color(QPalette.Accent))
        self.assertEqual(self.app.palette().color(QPalette.Highlight), ui.themeColor())
        for role in (QPalette.Window, QPalette.WindowText, QPalette.Base, QPalette.Text, QPalette.ButtonText):
            self.assertFalse(self.app.palette().isBrushSet(QPalette.Active, role))
            self.assertEqual(self.app.palette().color(role), native.color(role))

    def test_palette_without_a_named_scheme_drives_the_whole_background_theme(self):
        desktop, controller = self.desktop()
        desktop.hints.scheme = Qt.ColorScheme.Unknown
        desktop.colors.setColor(QPalette.Window, QColor('#191919'))
        desktop.colors.setColor(QPalette.WindowText, QColor('#eeeeee'))
        desktop.paletteChanged.emit(desktop.colors)
        self.app.processEvents()
        self.assertEqual(ui.qconfig.theme, ui.Theme.DARK)
        self.assertEqual(controller.accent, QColor('#bf0077'))

    def test_bright_and_dark_accents_keep_primary_labels_and_selection_readable(self):
        container = QWidget()
        self.addCleanup(container.deleteLater)
        button = ui.PrimaryPushButton('Go Live', parent=container)
        tool = ui.ToolButton(parent=container)
        ui.style_controls(container)
        for mode in (ui.Theme.LIGHT, ui.Theme.DARK):
            ui.setTheme(mode, save=False)
            for color in ('#ffff00', '#ff00bb', '#00ff00', '#000000', '#ffffff', '#0078d4', '#c21c14'):
                with self.subTest(mode=mode, color=color):
                    ui.setThemeColor(color, save=False)
                    button.ensurePolished()
                    background = ui.themeColor()
                    foreground = button.palette().color(QPalette.ButtonText)
                    values = sorted((luminance(background), luminance(foreground)))
                    self.assertGreaterEqual((values[1] + 0.05) / (values[0] + 0.05), 4.5)
                    for shade in (ui.ThemeColor.DARK_1, ui.ThemeColor.DARK_2,
                                  ui.ThemeColor.LIGHT_1, ui.ThemeColor.LIGHT_3):
                        background = shade.color()
                        values = sorted((luminance(background), luminance(ui.accent_foreground(background))))
                        self.assertGreaterEqual((values[1] + 0.05) / (values[0] + 0.05), 4.5)
                    ui._apply_palette()
                    palette = self.app.palette()
                    values = sorted((luminance(palette.color(QPalette.Highlight)),
                                     luminance(palette.color(QPalette.HighlightedText))))
                    self.assertGreaterEqual((values[1] + 0.05) / (values[0] + 0.05), 4.5)
                    self.assertGreater(tool.font().pointSize(), 0)

    def test_offline_status_renders_the_workspace_background(self):
        window = ui.AccentWindow()
        self.addCleanup(window.deleteLater)
        window.resize(400, 120)
        badge = ui.LiveStatusBadge(window)
        badge.move(20, 40)
        window.show()
        for mode in (ui.Theme.LIGHT, ui.Theme.DARK):
            ui.setTheme(mode, save=False)
            for color in ('#0078d4', '#bf0077', '#00aa55'):
                with self.subTest(mode=mode, color=color):
                    ui.setThemeColor(color, save=False)
                    badge.hide()
                    self.app.processEvents()
                    underlying = window.grab().toImage()
                    badge.show()
                    self.app.processEvents()
                    rendered = window.grab().toImage()
                    point = badge.mapTo(window, QPoint(4, badge.height() // 2))
                    self.assertEqual(rendered.pixelColor(point), underlying.pixelColor(point))
                    foreground = QColor('#e6e6e6' if mode == ui.Theme.DARK else '#303030')
                    values = sorted((luminance(foreground), luminance(underlying.pixelColor(point))))
                    self.assertGreaterEqual((values[1] + .05) / (values[0] + .05), 4.5)

    def test_message_box_surface_and_buttons_follow_live_theme_changes(self):
        dialog = ui.AccentMessageBox()
        self.addCleanup(dialog.deleteLater)
        dialog.setText('An update is available.')
        dialog.setStandardButtons(ui.AccentMessageBox.Yes | ui.AccentMessageBox.No)
        dialog.setDefaultButton(ui.AccentMessageBox.Yes)
        dialog.show()
        previous = None
        for mode in (ui.Theme.LIGHT, ui.Theme.DARK):
            ui.setTheme(mode, save=False)
            for color in ('#0078d4', '#bf0077', '#000000', '#ffffff'):
                with self.subTest(mode=mode, color=color):
                    ui.setThemeColor(color, save=False)
                    self.app.processEvents()
                    image = dialog.grab().toImage()
                    background = image.pixelColor(8, 8)
                    top, bottom = ui._surface_colors(mode == ui.Theme.DARK)
                    for channel in ('red', 'green', 'blue'):
                        value = getattr(background, channel)()
                        ends = sorted((getattr(top, channel)(), getattr(bottom, channel)()))
                        self.assertGreaterEqual(value, ends[0] - 2)
                        self.assertLessEqual(value, ends[1] + 2)
                    self.assertNotEqual(dialog.styleSheet(), previous)
                    previous = dialog.styleSheet()
                    primary = dialog.button(ui.AccentMessageBox.Yes)
                    # Qt applies :default colors while painting; the generic
                    # widget palette does not include that pseudo-state.
                    rendered = primary.grab().toImage()
                    colors = Counter(rendered.pixelColor(x, y).name()
                                     for x in range(20, rendered.width() - 20)
                                     for y in range(8, rendered.height() - 8))
                    (background, _), (foreground, text_pixels) = colors.most_common(2)
                    self.assertEqual(background, ui.themeColor().name())
                    self.assertGreater(text_pixels, 5)
                    values = sorted((luminance(QColor(background)), luminance(QColor(foreground))))
                    self.assertGreaterEqual((values[1] + .05) / (values[0] + .05), 4.5)
        self.assertTrue(dialog.testOption(ui.AccentMessageBox.Option.DontUseNativeDialog))

    def test_update_prompt_is_themed_and_download_requires_yes(self):
        import TiktokStreamKeyGenerator as gui
        parent = QWidget()
        self.addCleanup(parent.deleteLater)
        info = {'latest': '2.0.0', 'current': '1.0.0', 'url': 'https://example.invalid/download'}
        for result in (ui.AccentMessageBox.No, ui.AccentMessageBox.Yes):
            with self.subTest(result=result):
                def respond(dialog):
                    self.assertIsInstance(dialog, ui.AccentMessageBox)
                    self.assertEqual(dialog.windowTitle(), 'Update Available')
                    self.assertTrue(dialog.button(ui.AccentMessageBox.Yes).isDefault())
                    self.assertIn('qlineargradient', dialog.styleSheet())
                    return result
                with patch.object(ui.AccentMessageBox, 'exec', respond), \
                     patch.object(gui.QDesktopServices, 'openUrl') as download:
                    gui.StreamKeyGeneratorWindow.handle_update_check(parent, info)
                if result == ui.AccentMessageBox.Yes:
                    self.assertEqual(download.call_args.args[0].toString(), info['url'])
                    download.assert_called_once()
                else:
                    download.assert_not_called()

    def test_message_box_convenience_methods_keep_standard_buttons_and_results(self):
        original_exec = ui.QtMessageBox.exec
        for method in ('critical', 'information', 'warning', 'question'):
            with self.subTest(method=method):
                observed = {}
                def respond(dialog):
                    observed['type'] = type(dialog)
                    observed['title'] = dialog.windowTitle()
                    observed['default'] = dialog.button(ui.AccentMessageBox.Yes).isDefault()
                    timer = QTimer(dialog)
                    timer.setSingleShot(True)
                    timer.timeout.connect(dialog.button(ui.AccentMessageBox.No).click)
                    timer.start(0)
                    return original_exec(dialog)
                with patch.object(ui.AccentMessageBox, 'exec', respond):
                    result = getattr(ui.AccentMessageBox, method)(None, 'Test', 'Message',
                                ui.AccentMessageBox.Yes | ui.AccentMessageBox.No, ui.AccentMessageBox.Yes)
                self.assertEqual(result, ui.AccentMessageBox.No)
                self.assertEqual(observed, {'type': ui.AccentMessageBox, 'title': 'Test', 'default': True})
                QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


if __name__ == '__main__':
    unittest.main()
