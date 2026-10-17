"""Shared Fluent controls for the existing PySide6 application."""
from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QIcon, QLinearGradient, QPainter, QPalette
from PySide6.QtWidgets import QApplication, QDialog as QtDialog, QLabel, QGridLayout, QVBoxLayout, QWidget, QSizePolicy, QToolTip, QMessageBox as QtMessageBox
from qfluentwidgets import (
    Action, BodyLabel, CaptionLabel, CardWidget, CheckBox, CheckableMenu as FluentCheckableMenu, ComboBox as FluentComboBox,
    DropDownPushButton, EditableComboBox as FluentEditableComboBox,
    FluentIcon, FluentIconBase, LineEdit as FluentLineEdit,
    PrimaryPushButton as FluentPrimaryPushButton, PushButton, ScrollArea, PlainTextEdit,
    Pivot, RoundMenu as FluentRoundMenu, StrongBodyLabel, SubtitleLabel, TableWidget as FluentTableWidget, Theme, TitleLabel,
    ToolButton, isDarkTheme, qconfig, setCustomStyleSheet, setTheme, setThemeColor, themeColor,
)
from qfluentwidgets.components.widgets.table_view import TableItemDelegate
from qfluentwidgets.common.style_sheet import ThemeColor


def point_font(font, dpi=96):
    """Resolve pixel fonts before passing them to point-based Qt code."""
    result = QFont(font)
    if result.pointSizeF() <= 0:
        pixels = result.pixelSize()
        result.setPointSizeF(pixels * 72.0 / max(1, dpi) if pixels > 0 else 12.0)
    return result


def install_font_diagnostics(log_path):
    """Keep Qt warnings visible and record font-warning call sites."""
    import datetime
    import sys
    import traceback
    from pathlib import Path
    from PySide6.QtCore import qInstallMessageHandler

    def handler(kind, context, message):
        if 'QFont::setPointSize' in message:
            try:
                path = Path(log_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open('a', encoding='utf-8') as stream:
                    stream.write(datetime.datetime.now().isoformat() + ' ' + message + '\n')
                    stream.write(''.join(traceback.format_stack(limit=16)))
            except OSError:
                pass
        if previous is not None:
            previous(kind, context, message)
        elif sys.stderr is not None:
            sys.stderr.write(message + '\n')

    previous = qInstallMessageHandler(handler)
    return handler


class SystemFontTableDelegate(TableItemDelegate):
    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        font = QFont(self.parent().font())
        item_font = index.data(Qt.FontRole)
        if isinstance(item_font, QFont):
            font = item_font.resolve(font)
        option.font = point_font(font, self.parent().logicalDpiY())


class LineEdit(FluentLineEdit):
    """Keep Qt's text/parent constructor convention for existing call sites."""
    def __init__(self, text='', parent=None):
        if isinstance(text, QWidget):
            parent, text = text, ''
        super().__init__(parent)
        self.setText(str(text))


class ComboBox(FluentComboBox):
    def _createComboMenu(self):
        return _accent_menu(super()._createComboMenu())

    def addItem(self, text, userData=None):
        # Fluent's second positional argument is an icon; Qt's is userData.
        super().addItem(text, userData=userData)


class EditableComboBox(FluentEditableComboBox):
    def _createComboMenu(self):
        return _accent_menu(super()._createComboMenu())

    def addItem(self, text, userData=None):
        super().addItem(text, userData=userData)

    def setCurrentText(self, text):
        index = self.findText(text)
        if index >= 0:
            self.setCurrentIndex(index)
        else:
            self.setText(text)


class TableWidget(FluentTableWidget):
    def __init__(self, rows=0, columns=0, parent=None):
        if isinstance(rows, QWidget):
            parent, rows = rows, 0
        super().__init__(parent)
        self.setRowCount(rows)
        self.setColumnCount(columns)
        self.setItemDelegate(SystemFontTableDelegate(self))


def accent_foreground(background):
    """Choose the more readable of black/white for any system accent."""
    channels = (background.redF(), background.greenF(), background.blueF())
    linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in channels]
    luminance = sum(v * weight for v, weight in zip(linear, (0.2126, 0.7152, 0.0722)))
    return QColor('#000000' if (luminance + 0.05) / 0.05 >= 1.05 / (luminance + 0.05) else '#ffffff')


class PrimaryPushButton(FluentPrimaryPushButton):
    """Keep text/icons readable when the user's accent is bright or pale."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        qconfig.themeChanged.connect(self._restyle_accent)
        qconfig.themeColorChanged.connect(self._restyle_accent)
        self._restyle_accent()

    def _background(self):
        if self.isPressed:
            return (ThemeColor.DARK_2 if isDarkTheme() else ThemeColor.LIGHT_3).color()
        if self.isHover:
            return (ThemeColor.DARK_1 if isDarkTheme() else ThemeColor.LIGHT_1).color()
        return themeColor()

    def _restyle_accent(self, *_):
        colors = (ThemeColor.PRIMARY,
                  ThemeColor.DARK_1 if isDarkTheme() else ThemeColor.LIGHT_1,
                  ThemeColor.DARK_2 if isDarkTheme() else ThemeColor.LIGHT_3)
        css = '\n'.join('PrimaryPushButton' + state + ':enabled { color: ' +
                        accent_foreground(color.color()).name() + '; }'
                        for state, color in zip(('', ':hover', ':pressed'), colors))
        setCustomStyleSheet(self, css, css)

    def _drawIcon(self, icon, painter, rect, state=QIcon.Off):
        if isinstance(icon, FluentIconBase) and self.isEnabled():
            foreground = accent_foreground(self._background())
            icon = icon.icon(Theme.LIGHT if foreground == QColor('#000000') else Theme.DARK)
            PushButton._drawIcon(self, icon, painter, rect, state)
        else:
            super()._drawIcon(icon, painter, rect, state)


class SystemTheme(QObject):
    """Mirror Qt's native appearance and accent without masking the accent role."""
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.hints = app.styleHints()
        self.accent = QColor(app.palette().color(QPalette.Accent))
        self.surface_colors = self._surface_colors(app.palette())
        self.applying = False
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(0)
        self.timer.timeout.connect(self.sync)
        self.hints.colorSchemeChanged.connect(self.schedule)
        app.paletteChanged.connect(self.palette_changed)
        self.sync()

    def schedule(self, *_):
        # Qt emits colorSchemeChanged before installing its new native palette.
        # Let the current event finish, then apply both settings together.
        if not self.applying:
            self.timer.start()

    def palette_changed(self, palette):
        if self.applying:
            return
        accent = palette.color(QPalette.Accent)
        changed = False
        if accent.isValid() and accent.alpha() and accent != self.accent:
            self.accent = QColor(accent)
            changed = True
        surfaces = self._surface_colors(palette)
        if surfaces != self.surface_colors:
            self.surface_colors = surfaces
            changed = True
        if changed:
            self.schedule()

    @staticmethod
    def _surface_colors(palette):
        return tuple(palette.color(role).rgba() for role in
                     (QPalette.Window, QPalette.WindowText, QPalette.Base, QPalette.Text,
                      QPalette.Button, QPalette.ButtonText))

    def sync(self):
        if self.applying:
            return
        self.applying = True
        try:
            fallback = Theme.DARK if self.app.palette().color(QPalette.Window).lightnessF() < 0.5 else Theme.LIGHT
            theme = {Qt.ColorScheme.Dark: Theme.DARK, Qt.ColorScheme.Light: Theme.LIGHT}.get(
                self.hints.colorScheme(), fallback)
            if qconfig.get(qconfig.themeMode) != theme:
                setTheme(theme, save=False, lazy=True)
            if self.accent.isValid() and self.accent.alpha() and qconfig.get(qconfig.themeColor) != self.accent:
                setThemeColor(self.accent, save=False, lazy=True)
            _apply_palette()
        finally:
            self.applying = False


class LiveStatusBadge(QLabel):
    """Compact session state, with readable text in either Fluent theme."""
    _LABELS = {'offline': 'Offline', 'live': 'LIVE', 'paused': 'Paused'}
    _COLORS = {
        'live': (('#e4f5e7', '#0f6b26'), ('#183b22', '#92e39e')),
        'paused': (('#fff4ce', '#6d4b00'), ('#493815', '#ffdf88')),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        font = point_font(QApplication.instance().font())
        font.setWeight(QFont.DemiBold)
        self.setFont(font)
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.set_state('offline')
        qconfig.themeChanged.connect(self._restyle)
        qconfig.themeColorChanged.connect(self._restyle)

    def set_state(self, state):
        self._state = state
        self.setText(self._LABELS[state])
        self.setAccessibleName('LIVE status: ' + self.text())
        self._restyle()

    def _restyle(self, *_):
        if self._state == 'offline':
            # Let the workspace's actual gradient show through instead of
            # placing a fixed gray tile over the desktop accent colors.
            surface = 'transparent'
            foreground = '#e6e6e6' if isDarkTheme() else '#303030'
        else:
            surface, foreground = self._COLORS[self._state][int(isDarkTheme())]
        height = max(28, self.fontMetrics().height() + 10)
        self.setFixedHeight(height)
        self.setFixedWidth(max(self.fontMetrics().horizontalAdvance(text)
                               for text in self._LABELS.values()) + 24)
        self.setStyleSheet(f'color: {foreground}; background-color: {surface}; '
                          f'border-radius: {height // 2}px; padding: 0 12px;')


def section(title, *, grid=False):
    card = CardWidget()
    shell = QVBoxLayout(card)
    shell.setContentsMargins(18, 16, 18, 18)
    shell.setSpacing(14)
    heading = StrongBodyLabel(title, card)
    shell.addWidget(heading)
    content = QWidget(card)
    shell.addWidget(content, 1)
    layout = QGridLayout(content) if grid else QVBoxLayout(content)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(10)
    return card, layout


def _surface_colors(dark):
    accent = qconfig.get(qconfig.themeColor)
    base = QColor('#12151c' if dark else '#fafbff')
    def tint(amount):
        return QColor(*(round(a * amount + b * (1 - amount)) for a, b in zip(
            (accent.red(), accent.green(), accent.blue()), (base.red(), base.green(), base.blue()))))
    return tint(0.18 if dark else 0.15), tint(0.08 if dark else 0.05)


class _AccentSurface:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        qconfig.themeChanged.connect(self._update_surface)
        qconfig.themeColorChanged.connect(self._update_surface)

    def _update_surface(self, *_):
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        top, bottom = _surface_colors(isDarkTheme())
        gradient = QLinearGradient(0, 0, self.width(), self.height())
        gradient.setColorAt(0, top)
        gradient.setColorAt(1, bottom)
        painter = QPainter(self)
        painter.fillRect(self.rect(), gradient)
        painter.end()


class AccentWindow(_AccentSurface, QWidget):
    """Opaque, softly tinted workspace that follows the desktop accent."""


class AccentDialog(_AccentSurface, QtDialog):
    """Use the workspace surface in app dialogs with a native title bar."""


class AccentMessageBox(QtMessageBox):
    """Qt message-box semantics with the workspace's theme and accent surface."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setOption(QtMessageBox.Option.DontUseNativeDialog, True)
        self.setFont(point_font(QApplication.instance().font()))
        qconfig.themeChanged.connect(self._restyle)
        qconfig.themeColorChanged.connect(self._restyle)
        self._restyle()

    def _restyle(self, *_):
        dark = isDarkTheme()
        top, bottom = _surface_colors(dark)
        foreground = '#f4f4f4' if dark else '#202020'
        button = bottom.lighter(125) if dark else bottom.darker(103)
        hover = button.lighter(115) if dark else button.darker(105)
        border = bottom.lighter(155) if dark else bottom.darker(118)
        accent = themeColor()
        self.setStyleSheet(
            'QMessageBox { background-color: qlineargradient('
            'x1: 0, y1: 0, x2: 1, y2: 1, stop: 0 ' + top.name() + ', stop: 1 ' + bottom.name() + '); }'
            f'QMessageBox QLabel, QMessageBox QCheckBox {{ background-color: transparent; color: {foreground}; }}'
            'QMessageBox QDialogButtonBox { background-color: transparent; }'
            f'QMessageBox QPushButton {{ background-color: {button.name()}; color: {foreground}; '
            f'border: 1px solid {border.name()}; border-radius: 5px; padding: 6px 16px; min-height: 24px; }}'
            f'QMessageBox QPushButton:hover {{ background-color: {hover.name()}; }}'
            f'QMessageBox QPushButton:default {{ background-color: {accent.name()}; '
            f'color: {accent_foreground(accent).name()}; border-color: {accent.name()}; }}'
        )

    @classmethod
    def _show_message(cls, icon, parent, title, text, buttons, defaultButton):
        dialog = cls(parent)
        dialog.setIcon(icon)
        dialog.setWindowTitle(title)
        dialog.setText(text)
        dialog.setStandardButtons(buttons)
        if defaultButton != QtMessageBox.NoButton:
            dialog.setDefaultButton(defaultButton)
        try:
            return QtMessageBox.StandardButton(dialog.exec())
        finally:
            dialog.deleteLater()

    @classmethod
    def critical(cls, parent, title, text, buttons=QtMessageBox.Ok, defaultButton=QtMessageBox.NoButton):
        return cls._show_message(QtMessageBox.Critical, parent, title, text, buttons, defaultButton)

    @classmethod
    def information(cls, parent, title, text, buttons=QtMessageBox.Ok, defaultButton=QtMessageBox.NoButton):
        return cls._show_message(QtMessageBox.Information, parent, title, text, buttons, defaultButton)

    @classmethod
    def warning(cls, parent, title, text, buttons=QtMessageBox.Ok, defaultButton=QtMessageBox.NoButton):
        return cls._show_message(QtMessageBox.Warning, parent, title, text, buttons, defaultButton)

    @classmethod
    def question(cls, parent, title, text, buttons=QtMessageBox.Yes | QtMessageBox.No, defaultButton=QtMessageBox.NoButton):
        return cls._show_message(QtMessageBox.Question, parent, title, text, buttons, defaultButton)


class _AccentMenuStyle(QObject):
    def __init__(self, menu):
        super().__init__(menu)
        qconfig.themeChanged.connect(self.update_style)
        qconfig.themeColorChanged.connect(self.update_style)
        self.update_style()

    def update_style(self, *_):
        def css(dark):
            top, bottom = _surface_colors(dark)
            return ('MenuActionListWidget { background-color: qlineargradient('
                    'x1: 0, y1: 0, x2: 1, y2: 1, stop: 0 ' + top.name() +
                    ', stop: 1 ' + bottom.name() + '); }')
        # Tint only the list: the outer transparent margins hold Fluent's shadow.
        setCustomStyleSheet(self.parent(), css(False), css(True))


def _accent_menu(menu):
    if not hasattr(menu, '_accent_surface_style'):
        menu._accent_surface_style = _AccentMenuStyle(menu)
    return menu


class RoundMenu(FluentRoundMenu):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _accent_menu(self)

    def exec(self, *args, **kwargs):
        # PySide can re-expose QMenu.exec on a further Python subclass unless
        # this method is explicit. Keep Fluent's animated, nonblocking popup.
        return FluentRoundMenu.exec(self, *args, **kwargs)


class CheckableMenu(FluentCheckableMenu):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _accent_menu(self)

    def exec(self, *args, **kwargs):
        return FluentCheckableMenu.exec(self, *args, **kwargs)


def _apply_palette():
    app = QApplication.instance()
    if app is None:
        return
    accent = themeColor()
    palette = QPalette(app.palette())
    # Keep backgrounds and foregrounds inherited from the OS. Explicitly
    # setting those roles masks subsequent native palette updates in Qt.
    for role, color in (
        (QPalette.Highlight, accent),
        (QPalette.HighlightedText, accent_foreground(accent)),
    ):
        palette.setColor(role, QColor(color))
    if palette == app.palette():
        return
    app.setPalette(palette)
    # Native labels with a font-only stylesheet keep their old stylesheet
    # palette when the theme changes. Refresh it along with Fluent controls.
    for widget in app.allWidgets():
        if type(widget) is QLabel:
            widget.setPalette(palette)
            widget.style().unpolish(widget)
            widget.style().polish(widget)


def configure_fluent_theme():
    app = QApplication.instance()
    if app is None or getattr(app, '_tiktok_fluent_configured', False):
        return
    app._tiktok_fluent_configured = True
    font = point_font(app.font())
    font.setPointSizeF(max(12.0, font.pointSizeF()))
    app.setFont(font)
    QToolTip.setFont(point_font(QToolTip.font(), app.primaryScreen().logicalDotsPerInch()))
    qconfig.themeChanged.connect(_apply_palette)
    qconfig.themeColorChanged.connect(_apply_palette)
    # Keep this role inherited: setting QPalette.Accent ourselves would prevent
    # Qt from updating it when the user changes the desktop accent color.
    app._tiktok_system_theme = SystemTheme(app)


def style_controls(container):
    """Respect the system font scale instead of Fluent's fixed pixel defaults."""
    app = QApplication.instance()
    if app is None:
        return
    font = point_font(app.font())
    for control in container.findChildren(QWidget):
        if isinstance(control, (FluentLineEdit, FluentComboBox, FluentEditableComboBox,
                                PushButton, PrimaryPushButton, ToolButton, CheckBox, FluentTableWidget, PlainTextEdit)):
            control.setFont(font)
            if isinstance(control, (FluentLineEdit, FluentComboBox, PushButton, PrimaryPushButton)):
                control.setMaximumHeight(16777215)
                control.setMinimumHeight(max(36, control.fontMetrics().height() + 16))
    _apply_palette()
