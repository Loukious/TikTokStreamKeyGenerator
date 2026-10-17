"""Account picker for Windows LIVE Studio cookie imports."""
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QTableWidgetItem, QVBoxLayout
from Libs.fluent_ui import AccentDialog, PrimaryPushButton, PushButton, TableWidget, style_controls
from Libs.studio_cookies import export_studio_account
from Libs.gui_tasks import BackgroundTask, Work
from qfluentwidgets import IndeterminateProgressRing


class StudioImportDialog(AccentDialog):
    def __init__(self, accounts, *, output_dir, parent=None):
        super().__init__(parent)
        self.accounts = accounts
        self.output_dir = output_dir
        self.saved_path = ''
        self.busy = False
        self.setWindowTitle('Import from TikTok LIVE Studio')
        self.resize(680, 380)
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        note = QLabel('Choose a saved LIVE Studio account. Its cookies will be saved beside this app.\n'
                      'Studio will keep its current account. Existing exports for this username are updated.')
        note.setTextFormat(Qt.PlainText)
        note.setWordWrap(True)
        layout.addWidget(note)
        self.table = TableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(['Account', 'Nickname', 'Studio'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        for account in accounts:
            row = self.table.rowCount()
            self.table.insertRow(row)
            for column, text in enumerate((('@' + account.username) if account.username else account.user_id,
                                           account.nickname, 'Current' if account.current else 'Saved')):
                item = QTableWidgetItem(text)
                if column == 0:
                    item.setToolTip('Account ID: ' + account.user_id)
                self.table.setItem(row, column, item)
        layout.addWidget(self.table, 1)
        self.destination = QLabel()
        self.destination.setTextFormat(Qt.PlainText)
        self.destination.setWordWrap(True)
        layout.addWidget(self.destination)
        self.error_label = QLabel()
        self.error_label.setTextFormat(Qt.PlainText)
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)
        buttons = QHBoxLayout()
        self.spinner = IndeterminateProgressRing(self)
        self.spinner.setFixedSize(24, 24)
        self.spinner.hide()
        buttons.addWidget(self.spinner)
        buttons.addStretch(1)
        cancel = PushButton('Cancel')
        cancel.clicked.connect(self.reject)
        self.import_button = PrimaryPushButton('Import selected')
        self.import_button.setDefault(True)
        self.import_button.clicked.connect(self.import_selected)
        buttons.addWidget(cancel)
        buttons.addWidget(self.import_button)
        layout.addLayout(buttons)
        self.table.itemSelectionChanged.connect(self.update_selection)
        if accounts:
            row = next((i for i, a in enumerate(accounts) if a.current), 0)
            self.table.selectRow(row)
        self.update_selection()
        style_controls(self)

    def selected_account(self):
        row = self.table.currentRow()
        return self.accounts[row] if 0 <= row < len(self.accounts) else None

    def update_selection(self):
        account = self.selected_account()
        self.import_button.setEnabled(account is not None and not self.busy)
        self.destination.setText(str(Path(self.output_dir) / account.filename) if account else '')
        self.error_label.clear()

    def import_selected(self):
        account = self.selected_account()
        if account is None or self.busy:
            return
        self.busy = True
        self.spinner.show()
        self.table.setEnabled(False)
        self.import_button.setEnabled(False)
        self.error_label.setText('Saving cookies…')
        BackgroundTask(self, Work(export_studio_account, account, self.output_dir),
                       self.on_imported, self.on_import_failed).start()

    def on_imported(self, path):
        self.busy = False
        self.spinner.hide()
        self.saved_path = path
        self.accept()

    def on_import_failed(self, error):
        self.busy = False
        self.spinner.hide()
        self.table.setEnabled(True)
        self.update_selection()
        self.error_label.setText(str(error))

    def reject(self):
        if not self.busy:
            super().reject()

    def closeEvent(self, event):
        if self.busy:
            event.ignore()
        else:
            super().closeEvent(event)
