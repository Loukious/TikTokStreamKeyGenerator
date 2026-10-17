"""User-triggered LIVE campaign listing and visit reporting."""
import threading
from datetime import datetime, timezone

from PySide6.QtCore import Qt, Signal
from Libs.campaign_cache import load_viewed_ids, save_viewed_ids
from Libs.gui_tasks import BackgroundTask, Work
from Libs.fluent_ui import (LineEdit as QLineEdit, PushButton as QPushButton,
                            TableWidget as QTableWidget, ComboBox as QComboBox,
                            AccentDialog as QDialog, style_controls)
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QLabel,
    QTableWidgetItem, QVBoxLayout,
)
from qfluentwidgets import IndeterminateProgressRing


def _date(seconds):
    if not seconds:
        return ''
    try:
        return datetime.fromtimestamp(seconds, timezone.utc).strftime('%Y-%m-%d %H:%M')
    except (ValueError, OSError, OverflowError):
        return ''


class CampaignsDialog(QDialog):
    completed = Signal(str, object)
    failed = Signal(str, str)

    def __init__(self, stream_factory, *, kind, priority_region='', viewed_cache_path='', parent=None, auto_refresh=True):
        super().__init__(parent)
        self.stream_factory = stream_factory
        self.priority_region = priority_region
        self.viewed_cache_path = viewed_cache_path
        self.campaigns, self.visible_campaigns = [], []
        self.user_id = ''
        self.sent = set()
        self.busy = True
        self.operation = ''
        self.setWindowTitle('LIVE Campaigns — ' + ('Android' if kind == 'mobile' else 'PC'))
        self.resize(1000, 580)
        layout = QVBoxLayout(self)
        note = QLabel('Campaigns available to your signed-in account. Dates are UTC.\n'
                      'Double-click a campaign to mark it as viewed. '
                      'Viewing does not enroll you or claim rewards.')
        note.setWordWrap(True)
        layout.addWidget(note)
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Search title or activity ID')
        self.state = QComboBox()
        self.state.addItem('All states')
        self.refresh_button = QPushButton('Refresh')
        filters.addWidget(self.search, 1)
        filters.addWidget(self.state)
        filters.addWidget(self.refresh_button)
        layout.addLayout(filters)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(['Campaign', 'State', 'Starts (UTC)', 'Ends (UTC)', 'Activity ID', 'Viewed'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.setColumnWidth(4, 210)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        layout.addWidget(self.table, 1)
        self.status = QLabel('Ready')
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.PlainText)
        status_row = QHBoxLayout()
        self.spinner = IndeterminateProgressRing(self)
        self.spinner.setFixedSize(24, 24)
        status_row.addWidget(self.spinner)
        status_row.addWidget(self.status, 1)
        layout.addLayout(status_row)
        buttons = QHBoxLayout()
        self.view_button = QPushButton('Mark as viewed')
        self.close_button = QPushButton('Close')
        buttons.addWidget(self.view_button)
        buttons.addStretch(1)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)
        self.search.textChanged.connect(self.filter_campaigns)
        self.state.currentTextChanged.connect(self.filter_campaigns)
        self.table.itemSelectionChanged.connect(self.selection_changed)
        # Single clicks, keyboard selection and refreshes never send view events.
        self.table.cellDoubleClicked.connect(self.view_clicked)
        self.refresh_button.clicked.connect(self.refresh)
        self.view_button.clicked.connect(lambda: self.send_view())
        self.close_button.clicked.connect(self.reject)
        self.completed.connect(self.on_completed)
        self.failed.connect(self.on_failed)
        style_controls(self)
        self.update_controls()
        self.status.setText('Loading viewed campaigns…')
        def loaded(viewed):
            self.sent.update(viewed)
            self.busy = False
            self.status.setText('Ready')
            self.update_controls()
            if auto_refresh:
                self.refresh()
        BackgroundTask(self, Work(load_viewed_ids, viewed_cache_path), loaded,
                       lambda error: loaded(set())).start()

    def selected_campaign(self):
        row = self.table.currentRow()
        return self.visible_campaigns[row] if 0 <= row < len(self.visible_campaigns) else None

    def update_controls(self):
        self.spinner.setVisible(self.busy)
        selected = self.selected_campaign()
        self.refresh_button.setEnabled(not self.busy)
        self.search.setEnabled(not self.busy)
        self.state.setEnabled(not self.busy)
        self.table.setEnabled(not self.busy)
        self.close_button.setEnabled(not self.busy)
        self.view_button.setEnabled(not self.busy and bool(self.user_id and selected
                                    and selected.activity_id.isascii() and selected.activity_id.isdigit()
                                    and (self.user_id, selected.activity_id) not in self.sent))

    def filter_campaigns(self, *_):
        query = self.search.text().strip().casefold()
        state = self.state.currentText()
        self.visible_campaigns = [c for c in self.campaigns
                                  if (not query or query in (c.title + ' ' + c.activity_id).casefold())
                                  and (state == 'All states' or state == c.state)]
        self.table.setRowCount(0)
        for c in self.visible_campaigns:
            row = self.table.rowCount()
            self.table.insertRow(row)
            viewed = 'Yes' if (self.user_id, c.activity_id) in self.sent else ''
            for column, value in enumerate((c.title, c.state, _date(c.start_time), _date(c.end_time), c.activity_id, viewed)):
                item = QTableWidgetItem(value)
                item.setToolTip('\n'.join(filter(None, (c.title, c.description))) if column == 0 else value)
                self.table.setItem(row, column, item)
        if self.visible_campaigns:
            self.table.selectRow(0)
        self.update_controls()

    def selection_changed(self):
        self.update_controls()

    def view_clicked(self, row, _column=0):
        if not self.busy and 0 <= row < len(self.visible_campaigns):
            self.table.selectRow(row)
            self.send_view(self.visible_campaigns[row])

    def _run(self, operation, action):
        if self.busy:
            return
        self.busy = True
        self.operation = operation
        self.status.setText('Loading campaigns…' if operation == 'list' else 'Sending view…')
        self.update_controls()
        def worker():
            try:
                with self.stream_factory() as stream:
                    result = action(stream)
                self.completed.emit(operation, result)
            except Exception as exc:
                self.failed.emit(operation, str(exc))
        threading.Thread(target=worker, daemon=True).start()

    def refresh(self):
        self._run('list', lambda stream: stream.getCampaigns(priority_region=self.priority_region))

    def send_view(self, selected=None):
        selected = selected or self.selected_campaign()
        if (self.busy or not self.user_id or not selected
                or not selected.activity_id.isascii() or not selected.activity_id.isdigit()
                or (self.user_id, selected.activity_id) in self.sent):
            return
        user_id, activity_id = self.user_id, selected.activity_id
        def action(stream):
            stream.reportCampaignView(activity_id, expected_user_id=user_id, priority_region=self.priority_region)
            return user_id, activity_id
        self._run('view', action)

    def on_completed(self, operation, result):
        self.busy = False
        self.operation = ''
        if operation == 'list':
            self.user_id = result['user_id']
            self.campaigns = result['campaigns']
            previous = self.state.currentText()
            self.state.blockSignals(True)
            self.state.clear()
            self.state.addItems(['All states'] + sorted({c.state for c in self.campaigns}))
            if previous in {c.state for c in self.campaigns}:
                self.state.setCurrentText(previous)
            self.state.blockSignals(False)
            self.filter_campaigns()
            self.status.setText(f'{len(self.campaigns)} campaigns/banners returned for account {self.user_id}.'
                                if self.campaigns else 'No campaigns returned for this account.')
        else:
            self.sent.add(tuple(result))
            for row, campaign in enumerate(self.visible_campaigns):
                if (self.user_id, campaign.activity_id) in self.sent:
                    self.table.item(row, 5).setText('Yes')
            self.busy = True
            self.status.setText('Saving viewed campaigns…')
            def saved(error=''):
                self.busy = False
                self.status.setText('TikTok accepted the view event. Campaign task credit is determined by TikTok.' + error)
                self.update_controls()
            BackgroundTask(self, Work(save_viewed_ids, self.viewed_cache_path, set(self.sent)),
                           lambda result: saved(), lambda error: saved(
                               ' Could not save the viewed cache; this view is remembered only for this session.')).start()
        self.update_controls()

    def on_failed(self, operation, message):
        self.busy = False
        self.operation = ''
        if operation == 'list':
            # Old rows must not allow a write after account/authentication errors.
            self.user_id = ''
            self.campaigns = []
            self.filter_campaigns()
        suffix = ' The event was not retried automatically; receipt may be unconfirmed.' if operation == 'view' else ''
        self.status.setText(message + suffix)
        self.update_controls()

    def reject(self):
        if not self.busy:
            super().reject()

    def closeEvent(self, event):
        if self.busy:
            event.ignore()
        else:
            super().closeEvent(event)
