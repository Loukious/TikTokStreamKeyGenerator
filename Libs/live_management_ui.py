"""User-triggered LIVE controls, with account-bound background operations."""
from threading import Event
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QTableWidgetItem,
    QVBoxLayout, QWidget, QStackedWidget,
)
from qfluentwidgets import Pivot, IndeterminateProgressRing

from Libs.fluent_ui import (
    AccentDialog, CheckBox, ComboBox, LineEdit, PlainTextEdit, PushButton,
    PrimaryPushButton, TableWidget, style_controls,
)
from Libs.gui_tasks import BackgroundTask, Work, single_shot
from Libs.live_management import LiveManagement
from Libs.viewer_contributions_ui import ViewerContributionsDialog
from Libs.viewer_contributions import parse_viewer_lookup


def note(text):
    label = QLabel(text)
    label.setWordWrap(True)
    label.setTextFormat(Qt.PlainText)
    return label


class LiveManagementDialog(AccentDialog):
    """Every write follows a button click, authoritative account binding and validation."""
    settings_applied = Signal(object)

    def __init__(self, stream_factory, *, room_id='', priority_region='', viewers=(),
                 is_current=lambda: True, parent=None, auto_refresh=True):
        super().__init__(parent)
        self.stream_factory = stream_factory
        self.room_id = str(room_id or '')
        self.priority_region = priority_region
        self.is_current = is_current
        self.user_id = ''
        self.busy = False
        self.closed = False
        self.invalidated = Event()
        self.state = {}
        self.words = []
        self.moderators = []
        self.templates = []
        self.loaded = set()
        self.setWindowTitle('Manage LIVE' if self.room_id else 'LIVE account tools')
        self.resize(820, 620)
        self.setMinimumSize(700, 540)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.addWidget(note('Changes here apply to the selected account and current LIVE. '
                              'New-room preferences are in Settings → Comments.'))
        self.navigation = Pivot(self)
        self.stack = QStackedWidget(self)
        self.pages = {}
        layout.addWidget(self.navigation)
        layout.addWidget(self.stack, 1)
        self._comments_page()
        self._words_page()
        self._viewers_page(viewers)
        self._moderators_page()
        self._about_page()
        self.navigation.currentItemChanged.connect(self._page_changed)
        self.navigation.setCurrentItem('comments')
        self.status = note('Refresh to load account permissions and current settings.')
        self.spinner = IndeterminateProgressRing(self)
        self.spinner.setFixedSize(24, 24)
        status_row = QHBoxLayout()
        status_row.addWidget(self.spinner)
        status_row.addWidget(self.status, 1)
        layout.addLayout(status_row)
        footer = QHBoxLayout()
        self.refresh_button = PushButton('Refresh')
        self.close_button = PushButton('Close')
        footer.addWidget(self.refresh_button)
        footer.addStretch(1)
        footer.addWidget(self.close_button)
        layout.addLayout(footer)
        self.refresh_button.clicked.connect(self.refresh)
        self.close_button.clicked.connect(self.reject)
        self.context_timer = QTimer(self)
        self.context_timer.setInterval(500)
        self.context_timer.timeout.connect(self.update_controls)
        self.context_timer.start()
        style_controls(self)
        self.update_controls()
        if auto_refresh:
            single_shot(self, 0, self.refresh)

    def _page(self, key, title):
        page = QWidget()
        page.setObjectName(key)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 12, 0, 0)
        self.pages[key] = page
        self.stack.addWidget(page)
        self.navigation.addItem(key, title)
        return layout

    @staticmethod
    def _table(headers):
        table = TableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        table.horizontalHeader().setStretchLastSection(True)
        return table

    def _comments_page(self):
        layout = self._page('comments', 'Comments')
        self.comment_controls = {}
        for key, label in (
            ('allow_comments', 'Allow comments'),
            ('filter_comments', 'Filter potentially unkind comments'),
            ('subscriber_only_chat', 'Subscriber / Super Fans-only chat'),
            ('star_comments', 'Allow Star Comments'),
        ):
            control = CheckBox(label)
            self.comment_controls[key] = control
            layout.addWidget(control)
            control.toggled.connect(self.update_controls)
        star_row = QHBoxLayout()
        star_row.addWidget(note('Who can send Star Comments'))
        self.star_group = ComboBox()
        self.star_group.setAccessibleName('Star Comments audience')
        for label, value in (('All viewers', 1), ('Gifter level', 2), ('Team member level', 3)):
            self.star_group.addItem(label, value)
        self.star_level = ComboBox()
        self.star_level.setAccessibleName('Minimum Star Comments level')
        for value in (0, 1, 10, 20, 30):
            self.star_level.addItem('All levels' if value == 0 else f'Level {value} or higher', value)
        star_row.addWidget(self.star_group, 1)
        star_row.addWidget(self.star_level, 1)
        layout.addLayout(star_row)
        self.star_group.currentIndexChanged.connect(self.update_controls)
        self.permission_note = note('Permissions have not been loaded.')
        layout.addWidget(self.permission_note)
        layout.addStretch(1)
        self.apply_comments_button = PrimaryPushButton('Apply to current LIVE')
        self.apply_comments_button.clicked.connect(self.apply_comments)
        layout.addWidget(self.apply_comments_button)

    def _words_page(self):
        layout = self._page('words', 'Blocked words')
        layout.addWidget(note('Blocked words are stored on TikTok. Up to 500 words, with 30 characters per word.'))
        self.word_table = self._table(['Word'])
        layout.addWidget(self.word_table, 1)
        row = QHBoxLayout()
        self.word_input = LineEdit()
        self.word_input.setPlaceholderText('Word or phrase to block')
        self.word_input.setMaxLength(30)
        self.add_word_button = PushButton('Add')
        self.remove_word_button = PushButton('Remove selected')
        row.addWidget(self.word_input, 1)
        row.addWidget(self.add_word_button)
        row.addWidget(self.remove_word_button)
        layout.addLayout(row)
        self.add_word_button.clicked.connect(self.add_word)
        self.remove_word_button.clicked.connect(self.remove_word)
        self.word_table.itemSelectionChanged.connect(self.update_controls)
        self.word_input.textChanged.connect(self.update_controls)

    def _viewers_page(self, viewers):
        layout = self._page('viewers', 'Viewers')
        layout.addWidget(note('Select a viewer or enter @username / user ID for contributions. Moderation uses numeric user IDs.'))
        self.viewer_table = self._table(['Viewer', 'User ID'])
        layout.addWidget(self.viewer_table, 1)
        for viewer in viewers:
            row = self.viewer_table.rowCount()
            self.viewer_table.insertRow(row)
            for column, value in enumerate((viewer.get('name', ''), viewer.get('id', ''))):
                self.viewer_table.setItem(row, column, QTableWidgetItem(str(value)))
        inputs = QHBoxLayout()
        self.viewer_id = LineEdit()
        self.viewer_id.setMaxLength(25)
        self.viewer_id.setPlaceholderText('@username or numeric user ID')
        self.viewer_id.setAccessibleName('Viewer username or user ID')
        self.viewer_id.setToolTip('Use @ before an all-digit username, for example @12345.')
        self.mute_duration = ComboBox()
        for label, seconds in (('5 seconds', 5), ('30 seconds', 30), ('1 minute', 60), ('5 minutes', 300), ('Entire LIVE', 0)):
            self.mute_duration.addItem(label, seconds)
        self.mute_duration.setCurrentIndex(3)
        inputs.addWidget(self.viewer_id, 1)
        inputs.addWidget(self.mute_duration)
        layout.addLayout(inputs)
        contributions = QHBoxLayout()
        self.contributions_button = PushButton('View contributions')
        self.contributions_button.clicked.connect(self.open_contributions)
        contributions.addWidget(self.contributions_button)
        contributions.addStretch(1)
        layout.addLayout(contributions)
        row = QHBoxLayout()
        self.viewer_buttons = {}
        for action, label in (('mute', 'Mute'), ('unmute', 'Unmute'), ('block', 'Block'), ('unblock', 'Unblock')):
            button = PushButton(label)
            button.clicked.connect(lambda checked=False, value=action: self.moderate(value))
            self.viewer_buttons[action] = button
            row.addWidget(button)
        layout.addLayout(row)
        self.viewer_table.itemSelectionChanged.connect(self._select_viewer)
        self.viewer_id.textChanged.connect(self.update_controls)

    def _moderators_page(self):
        layout = self._page('moderators', 'Moderators')
        layout.addWidget(note('Manage moderators for this account. TikTok determines their available permissions.'))
        self.moderator_table = self._table(['Moderator', 'User ID'])
        layout.addWidget(self.moderator_table, 1)
        row = QHBoxLayout()
        self.moderator_id = LineEdit()
        self.moderator_id.setMaxLength(20)
        self.moderator_id.setPlaceholderText('User ID to add as moderator')
        self.add_moderator_button = PushButton('Add')
        self.remove_moderator_button = PushButton('Remove selected')
        row.addWidget(self.moderator_id, 1)
        row.addWidget(self.add_moderator_button)
        row.addWidget(self.remove_moderator_button)
        layout.addLayout(row)
        self.add_moderator_button.clicked.connect(lambda: self.change_moderator(True))
        self.remove_moderator_button.clicked.connect(lambda: self.change_moderator(False))
        self.moderator_table.itemSelectionChanged.connect(self.update_controls)
        self.moderator_id.textChanged.connect(self.update_controls)

    def _about_page(self):
        layout = self._page('about', 'About me')
        layout.addWidget(note('Edit the introduction shown in your LIVE. TikTok may review changes.'))
        self.about_template = ComboBox()
        self.about_template.setAccessibleName('LIVE intro template')
        layout.addWidget(self.about_template)
        self.about_text = PlainTextEdit()
        self.about_text.setPlaceholderText('Introduce yourself and your LIVE')
        layout.addWidget(self.about_text, 1)
        self.about_limit = note('Load a template to see its limits.')
        layout.addWidget(self.about_limit)
        self.about_review = note('')
        layout.addWidget(self.about_review)
        row = QHBoxLayout()
        self.save_about_button = PrimaryPushButton('Save intro')
        self.clear_about_button = PushButton('Clear intro')
        row.addWidget(self.save_about_button)
        row.addWidget(self.clear_about_button)
        row.addStretch(1)
        layout.addLayout(row)
        self.save_about_button.clicked.connect(self.save_about)
        self.clear_about_button.clicked.connect(lambda: self._run('clear_about_me', success=lambda _: self.refresh()))
        self.about_template.currentIndexChanged.connect(self._update_about_limit)
        self.about_text.textChanged.connect(self.update_controls)

    def _page_changed(self, key):
        self.stack.setCurrentWidget(self.pages[key])
        if hasattr(self, 'status') and not self.busy and self.user_id and key not in self.loaded:
            self.refresh()

    def _current(self):
        if self.closed or not self.is_current():
            self.invalidated.set()
        return not self.invalidated.is_set()

    def update_controls(self, *_):
        if not hasattr(self, 'status'):
            return
        current = self._current()
        ready = current and not self.busy and bool(self.user_id)
        live = ready and bool(self.room_id)
        self.spinner.setVisible(self.busy)
        self.refresh_button.setEnabled(current and not self.busy)
        self.close_button.setEnabled(not self.busy)
        self.navigation.setEnabled(not self.busy)
        self.apply_comments_button.setEnabled(live and 'comments' in self.loaded)
        for key, widget in self.comment_controls.items():
            allowed = self.state.get(key) is not None
            if key == 'subscriber_only_chat':
                allowed = allowed and (self.state.get('subscriber_available') or self.state.get(key) is True)
            elif key == 'star_comments':
                allowed = allowed and (self.state.get('star_available') or self.state.get(key) is True)
            widget.setEnabled(live and bool(allowed))
        stars = live and bool(self.state.get('star_available')) and self.comment_controls['star_comments'].isChecked()
        self.star_group.setEnabled(stars)
        self.star_level.setEnabled(stars and self.star_group.currentData() in (2, 3))
        self.word_input.setEnabled(ready and 'words' in self.loaded)
        self.add_word_button.setEnabled(ready and 'words' in self.loaded and bool(self.word_input.text().strip()) and len(self.words) < 500)
        self.remove_word_button.setEnabled(ready and 0 <= self.word_table.currentRow() < len(self.words))
        self.viewer_id.setEnabled(live)
        self.mute_duration.setEnabled(live)
        try:
            lookup_kind, _ = parse_viewer_lookup(self.viewer_id.text())
            valid_lookup = True
        except ValueError:
            lookup_kind = ''
            valid_lookup = False
        for button in self.viewer_buttons.values():
            button.setEnabled(live and valid_lookup and lookup_kind == 'id')
        self.contributions_button.setEnabled(live and valid_lookup)
        moderator_id = self.moderator_id.text()
        self.add_moderator_button.setEnabled(ready and 'moderators' in self.loaded and moderator_id.isascii() and moderator_id.isdigit() and int(moderator_id) > 0)
        self.remove_moderator_button.setEnabled(ready and 0 <= self.moderator_table.currentRow() < len(self.moderators))
        self.moderator_id.setEnabled(ready)
        self.about_template.setEnabled(ready and 'about' in self.loaded)
        self.about_text.setEnabled(ready and 'about' in self.loaded)
        index = self.about_template.currentIndex()
        valid_template = 0 <= index < len(self.templates)
        limit = self.templates[index].get('max_length') if valid_template else None
        text = self.about_text.toPlainText().strip()
        single_input = valid_template and len(self.templates[index].get('input_boxes', [])) == 1
        self.save_about_button.setEnabled(ready and 'about' in self.loaded and single_input and bool(text)
                                         and (not limit or len(text.encode('utf-16-le')) // 2 <= limit))
        self.clear_about_button.setEnabled(ready and 'about' in self.loaded)
        if not current:
            self.status.setText('The account or LIVE changed. Close this window and reopen it for the current session.')

    def _run(self, method, *args, success=None, **kwargs):
        if self.busy or not self._current():
            self.update_controls()
            return
        if method != 'get_chat_settings' and not self.user_id:
            self.status.setText('Refresh account permissions before making changes.')
            return
        self.busy = True
        self.status.setText('Working…')
        self.update_controls()
        factory, room_id, region, user_id = self.stream_factory, self.room_id, self.priority_region, self.user_id
        invalidated = self.invalidated

        def operation():
            with factory() as stream:
                service = LiveManagement(stream, room_id=room_id, priority_region=region, expected_user_id=user_id,
                                         is_current=lambda: not invalidated.is_set())
                return getattr(service, method)(*args, **kwargs)

        def completed(result):
            self.busy = False
            if not self._current():
                self.update_controls()
                return
            if isinstance(result, dict) and result.get('user_id'):
                self.user_id = str(result['user_id'])
            self.status.setText('Saved.' if not method.startswith('get_') else 'Loaded.')
            if success:
                success(result)
            self.update_controls()

        def failed(error):
            self.busy = False
            self.status.setText(str(error))
            # A timed-out/partial mutation is not silently retried. Refresh
            # explicitly before applying again so the user sees current state.
            if method == 'update_chat_settings':
                self.loaded.discard('comments')
            self.update_controls()

        BackgroundTask(self, Work(operation), completed, failed).start()

    def refresh(self):
        if not self.user_id:
            self._run('get_chat_settings', success=self._bind_state)
            return
        key = self.navigation.currentRouteKey()
        operations = {'comments': ('get_chat_settings', self._load_state),
                      'words': ('get_words', self._load_words),
                      'moderators': ('get_moderators', self._load_moderators),
                      'about': ('get_about_me', self._load_about)}
        if key in operations:
            method, success = operations[key]
            self._run(method, success=success)
        else:
            self.status.setText('Use an exact @username or user ID to view contributions. Display names are not usernames.')

    def _bind_state(self, state):
        self._load_state(state)
        if self.navigation.currentRouteKey() != 'comments' and self.user_id:
            self.refresh()

    def _load_state(self, state):
        self.state = dict(state)
        for key, control in self.comment_controls.items():
            control.setChecked(state.get(key) is True)
        self.star_group.setCurrentIndex(self.star_group.findData(state.get('star_grant_group')))
        level = state.get('star_grant_level')
        if type(level) is int and level >= 0 and self.star_level.findData(level) < 0:
            self.star_level.addItem(f'Level {level} or higher', level)
        self.star_level.setCurrentIndex(self.star_level.findData(level))
        self.loaded.add('comments')
        self.permission_note.setText('\n'.join(filter(None, (
            '' if self.room_id else 'Start a LIVE to change its comments here. Configure new-room choices in Settings → Comments.',
            '' if state.get('subscriber_available') else state.get('subscriber_reason', 'Subscriber-only chat is unavailable.'),
            '' if state.get('star_available') else state.get('star_reason', 'Star Comments are unavailable.'),
            state.get('refresh_warning', ''),
        ))))

    def apply_comments(self):
        if 'comments' not in self.loaded:
            return
        changes = {key: control.isChecked() for key, control in self.comment_controls.items()
                   if control.isEnabled() and control.isChecked() != self.state.get(key)}
        if changes.get('subscriber_only_chat') and not self.comment_controls['allow_comments'].isChecked():
            self.status.setText('Allow comments before enabling subscriber-only chat.')
            return
        if self.star_group.isEnabled() and self.star_group.currentData() is not None:
            group = self.star_group.currentData()
            level = 0 if group == 1 else self.star_level.currentData()
            if level is None:
                self.status.setText('Choose a minimum Star Comments level.')
                return
            for key, value in (('star_grant_group', group), ('star_grant_level', level)):
                if value != self.state.get(key):
                    changes[key] = value
        if not changes:
            self.status.setText('No comment settings changed.')
            return
        def saved(state):
            self._load_state(state)
            self.settings_applied.emit(state)
            if state.get('refresh_warning'):
                self.status.setText(state['refresh_warning'])
        self._run('update_chat_settings', changes, success=saved)

    def _load_words(self, words):
        self.words = list(words)
        self.word_table.setRowCount(len(words))
        for row, word in enumerate(words):
            self.word_table.setItem(row, 0, QTableWidgetItem(word['word']))
        self.loaded.add('words')
        self.status.setText(f'{len(words)} / 500 blocked words')

    def add_word(self):
        word = self.word_input.text().strip()
        def saved(_):
            self.word_input.clear()
            self.refresh()
        self._run('add_word', word, success=saved)

    def remove_word(self):
        row = self.word_table.currentRow()
        if 0 <= row < len(self.words):
            self._run('delete_word', self.words[row]['id'], success=lambda _: self.refresh())

    def _select_viewer(self):
        item = self.viewer_table.item(self.viewer_table.currentRow(), 1)
        if item:
            self.viewer_id.setText(item.text())

    def moderate(self, action):
        self._run('moderate_user', self.viewer_id.text().strip(), action,
                  duration=self.mute_duration.currentData())

    def open_contributions(self):
        self.update_controls()
        if not self.contributions_button.isEnabled():
            return
        viewer_id = self.viewer_id.text().strip()
        name = ''
        for row in range(self.viewer_table.rowCount()):
            if self.viewer_table.item(row, 1).text() == viewer_id:
                name = self.viewer_table.item(row, 0).text()
                break
        dialog = ViewerContributionsDialog(self.stream_factory, room_id=self.room_id,
            viewer_id=viewer_id, viewer_name=name, expected_user_id=self.user_id,
            priority_region=self.priority_region, is_current=self._current, parent=self)
        dialog.exec()
        dialog.deleteLater()

    def _load_moderators(self, moderators):
        self.moderators = list(moderators)
        self.moderator_table.setRowCount(len(moderators))
        for row, moderator in enumerate(moderators):
            for column, value in enumerate((moderator['name'], moderator['id'])):
                self.moderator_table.setItem(row, column, QTableWidgetItem(str(value)))
        self.loaded.add('moderators')

    def change_moderator(self, enabled):
        row = self.moderator_table.currentRow()
        user_id = self.moderator_id.text().strip() if enabled else (
            self.moderators[row]['id'] if 0 <= row < len(self.moderators) else '')
        if user_id:
            self._run('set_moderator', user_id, enabled, success=lambda _: self.refresh())

    def _load_about(self, about):
        self.templates = list(about.get('templates') or [])
        self.about_template.blockSignals(True)
        self.about_template.clear()
        for template in self.templates:
            self.about_template.addItem(template['name'], template['id'])
        selected = self.about_template.findData(about.get('current_template_id'))
        if selected >= 0:
            self.about_template.setCurrentIndex(selected)
        self.about_template.blockSignals(False)
        self.about_text.setPlainText(about.get('content') or '')
        self.loaded.add('about')
        audit_status = str(about.get('audit_status', ''))
        self.about_review.setText({'2': 'Your intro is awaiting TikTok review.',
                                  '3': 'TikTok rejected this intro. Edit it and save again.'}.get(audit_status, ''))
        self.about_review.setVisible(bool(self.about_review.text()))
        self._update_about_limit()

    def _update_about_limit(self, *_):
        index = self.about_template.currentIndex()
        limit = self.templates[index].get('max_length') if 0 <= index < len(self.templates) else None
        self.about_limit.setText(f'Up to {limit} characters.' if limit else 'Select an available TikTok intro template.')
        self.update_controls()

    def save_about(self):
        index = self.about_template.currentIndex()
        if 0 <= index < len(self.templates):
            self._run('set_about_me', self.templates[index]['id'], self.about_text.toPlainText().strip(),
                      success=lambda _: self.refresh())

    def reject(self):
        if self.busy:
            return
        self.closed = True
        self.context_timer.stop()
        super().reject()

    def closeEvent(self, event):
        if self.busy:
            event.ignore()
            return
        self.closed = True
        self.context_timer.stop()
        super().closeEvent(event)
