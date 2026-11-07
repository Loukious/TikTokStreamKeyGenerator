"""Review and explicitly submit one account-bound LIVE violation appeal."""
from threading import Event

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout
from qfluentwidgets import IndeterminateProgressRing

from Libs.fluent_ui import AccentDialog, ComboBox, PlainTextEdit, PushButton, PrimaryPushButton, style_controls
from Libs.gui_tasks import BackgroundTask, Work, single_shot
from Libs.live_appeals import APPEAL_REASONS, LiveAppeals


def label(text):
    widget = QLabel(text)
    widget.setWordWrap(True)
    widget.setTextFormat(Qt.PlainText)
    return widget


class ViolationAppealDialog(AccentDialog):
    appeal_submitted = Signal(object)

    def __init__(self, stream_factory, record, *, priority_region='', is_current=lambda: True,
                 submitted=None, parent=None, auto_refresh=True):
        super().__init__(parent)
        self.stream_factory, self.record = stream_factory, record
        self.priority_region, self.is_current = priority_region, is_current
        self.submitted = submitted if submitted is not None else set()
        self.state, self.user_id = {}, ''
        self.busy, self.closed, self.needs_refresh = False, False, True
        self.invalidated = Event()
        self.setWindowTitle('LIVE violation appeal')
        self.resize(740, 570)
        self.setMinimumSize(620, 520)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        self.heading = label('Loading violation details…')
        layout.addWidget(self.heading)
        self.details = PlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setAccessibleName('Violation details')
        layout.addWidget(self.details, 1)
        self.eligibility = label('TikTok determines whether this violation can be appealed.')
        layout.addWidget(self.eligibility)
        self.reason_label = label('Reason for your appeal')
        self.reason = ComboBox()
        self.reason.setAccessibleName('Appeal reason')
        self.reason.addItem('Select a reason', '')
        for title, key in APPEAL_REASONS:
            self.reason.addItem(title, key)
        layout.addWidget(self.reason_label)
        layout.addWidget(self.reason)
        self.explanation = PlainTextEdit()
        self.explanation.setPlaceholderText('Explain your appeal when selecting Other (up to 140 characters)')
        self.explanation.setAccessibleName('Appeal explanation')
        self.explanation.setMaximumHeight(110)
        layout.addWidget(self.explanation)
        self.character_count = label('')
        layout.addWidget(self.character_count)
        self.status = label('Refresh to check the current status.')
        row = QHBoxLayout()
        self.spinner = IndeterminateProgressRing(self)
        self.spinner.setFixedSize(24, 24)
        row.addWidget(self.spinner)
        row.addWidget(self.status, 1)
        layout.addLayout(row)
        footer = QHBoxLayout()
        self.refresh_button = PushButton('Refresh')
        self.official_button = PushButton('Open official details')
        self.submit_button = PrimaryPushButton('Submit appeal')
        self.close_button = PushButton('Close')
        for button in (self.refresh_button, self.official_button, self.submit_button, self.close_button):
            footer.addWidget(button)
        layout.addLayout(footer)
        self.refresh_button.clicked.connect(self.refresh)
        self.official_button.clicked.connect(self.open_official)
        self.submit_button.clicked.connect(self.submit)
        self.close_button.clicked.connect(self.reject)
        self.reason.currentIndexChanged.connect(self.update_controls)
        self.explanation.textChanged.connect(self.update_controls)
        self.context_timer = QTimer(self)
        self.context_timer.setInterval(300)
        self.context_timer.timeout.connect(self.update_controls)
        self.context_timer.start()
        style_controls(self)
        self.update_controls()
        if auto_refresh:
            single_shot(self, 0, self.refresh)

    def _current(self):
        if self.closed or not self.is_current():
            self.invalidated.set()
        return not self.invalidated.is_set()

    def _receipt_key(self):
        route = self.state.get('route', {})
        return self.user_id, route.get('kind'), route.get('submission_id', route.get('id'))

    def update_controls(self, *_):
        current = self._current()
        ready = current and not self.busy and not self.needs_refresh
        general = self.state.get('route', {}).get('kind') == 'general'
        can_submit = ready and self.state.get('can_submit', False) and self._receipt_key() not in self.submitted
        other = self.reason.currentData() == APPEAL_REASONS[-1][1]
        text = self.explanation.toPlainText().strip()
        length = len(text.encode('utf-16-le')) // 2
        self.character_count.setText(f'{length} / 140 characters' if general and other else '')
        for widget in (self.reason_label, self.reason, self.explanation, self.character_count):
            widget.setVisible(general)
        self.reason.setEnabled(can_submit and general)
        self.explanation.setEnabled(can_submit and general and other)
        valid = not general or (bool(self.reason.currentData()) and (not other or (0 < length <= 140)))
        self.submit_button.setEnabled(can_submit and valid)
        self.official_button.setEnabled(ready and bool(self.state.get('route', {}).get('official_url')))
        self.refresh_button.setEnabled(current and not self.busy)
        self.close_button.setEnabled(not self.busy)
        self.spinner.setVisible(self.busy)
        if not current:
            self.status.setText('The selected account changed. Close and reopen the violation.')

    def _run(self, method, *args, success=None):
        if self.busy or not self._current():
            self.update_controls()
            return
        self.busy = True
        self.status.setText('Submitting appeal…' if method == 'submit' else 'Checking violation details…')
        self.update_controls()
        factory, record, region, user_id = self.stream_factory, self.record, self.priority_region, self.user_id
        invalidated = self.invalidated
        def operation():
            with factory() as stream:
                service = LiveAppeals(stream, record, priority_region=region, expected_user_id=user_id,
                                      is_current=lambda: not invalidated.is_set())
                return getattr(service, method)(*args)
        def completed(result):
            self.busy = False
            if self._current():
                success(result)
            self.update_controls()
        def failed(error):
            self.busy = False
            self.needs_refresh = True
            self.status.setText(str(error) + (' Refresh status before trying again; submission was not confirmed.' if method == 'submit' else ''))
            self.update_controls()
        BackgroundTask(self, Work(operation), completed, failed).start()

    def _loaded(self, state):
        self.state = state
        self.user_id = state['user_id']
        self.needs_refresh = False
        punish = state['record'].get('punish_info') or {}
        live = state['record'].get('live_info') or {}
        self.heading.setText(punish.get('punish_title') or 'LIVE violation')
        detail = state.get('detail') or {}
        reasons = detail.get('violation_reason') or []
        snapshot_reason = '\n'.join(r for r in reasons if isinstance(r, str))
        lines = ['Status: ' + state.get('status', 'Unavailable'),
                 punish.get('punish_reason') or punish.get('moderation_info') or detail.get('moderation_info') or snapshot_reason,
                 'LIVE: ' + str(live['title']) if live.get('title') else '',
                 'Affected feature: ' + detail['subfeature_name'] if detail.get('subfeature_name') else '']
        self.details.setPlainText('\n'.join(line for line in lines if line))
        self.eligibility.setText(state.get('reason') or ('Submit to request a review of this restriction.'
            if state['route']['kind'] == 'snapshot' else 'Select the reason that describes your appeal.'))
        if self._receipt_key() in self.submitted:
            self.status.setText('Appeal submitted. TikTok will review it; Refresh checks the result.')
        else:
            self.status.setText('Current details loaded.')

    def refresh(self):
        self._run('load', success=self._loaded)

    def submit(self):
        if not self.submit_button.isEnabled():
            return
        def saved(result):
            self._loaded(result['state'])
            self.submitted.add(self._receipt_key())
            self.status.setText(result.get('refresh_warning') or 'Appeal submitted. TikTok will review it; Refresh checks the result.')
            self.appeal_submitted.emit(result)
        self._run('submit', self.state['route'], self.reason.currentData(), self.explanation.toPlainText(), success=saved)

    def open_official(self):
        if not self.official_button.isEnabled():
            return
        def opened(state):
            self._loaded(state)
            url = state.get('route', {}).get('official_url')
            if url and QDesktopServices.openUrl(QUrl(url)):
                self.status.setText('Opened TikTok’s official details. Sign in to the same account if requested. No appeal was submitted by this app.')
            else:
                self.status.setText('Could not open TikTok’s official details.')
        self._run('load', success=opened)

    def reject(self):
        if self.busy:
            return
        self.closed = True
        self.invalidated.set()
        self.context_timer.stop()
        super().reject()

    def closeEvent(self, event):
        if self.busy:
            event.ignore()
        else:
            self.closed = True
            self.invalidated.set()
            self.context_timer.stop()
            super().closeEvent(event)
