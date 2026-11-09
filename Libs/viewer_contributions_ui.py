"""Viewer contribution cards with cancellable reads and bounded inline emotes."""
import base64
import html
from threading import Event

from PySide6.QtCore import QByteArray, QBuffer, QDateTime, QIODevice, QLocale, Qt, QTimer, QUrl
from PySide6.QtGui import QImageReader, QPixmap, QTextDocument
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QApplication, QGridLayout, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import IndeterminateProgressRing, TextBrowser

from Libs.fluent_ui import AccentDialog, PushButton, point_font, style_controls
from Libs.gui_tasks import BackgroundTask, Work, single_shot
from Libs.viewer_contributions import ViewerContributions, emote_url, watch_time_text


def label(text=''):
    widget = QLabel(text)
    widget.setTextFormat(Qt.PlainText)
    widget.setWordWrap(True)
    return widget


class ContributionComments(TextBrowser):
    """HTML is generated locally; remote content cannot load document resources."""
    MAX_IMAGE_BYTES = 512 * 1024

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.setAccessibleName('Latest viewer comments')
        font = point_font(QApplication.font())
        self.setFont(font)
        self.document().setDefaultFont(font)
        self.network = QNetworkAccessManager(self)
        self.pending = set()
        self.images = {}
        self.urls = {}
        self.comments = None
        self.generation = 0
        self.anchorClicked.connect(self.preview_emote)
        self.highlighted.connect(self.emote_tooltip)

    def loadResource(self, kind, name):
        return self.images.get(name.toString())

    def cancel_images(self):
        self.generation += 1
        for reply in tuple(self.pending):
            reply.abort()
        self.pending.clear()

    def set_comments(self, comments):
        self.cancel_images()
        self.comments = comments
        self.images.clear()
        self.urls.clear()
        self.setToolTip('')
        for parts in comments or []:
            for part in parts:
                url = emote_url(part.get('emote_url'))
                if url and url not in self.urls and len(self.urls) < 20:
                    self.urls[url] = f'contribution-emote:{len(self.urls)}'
        self.render_comments()
        for url, key in self.urls.items():
            self.fetch_emote(url, key)

    def render_comments(self):
        if self.comments is None:
            self.setPlainText('TikTok did not return recent comments.')
            return
        if not self.comments:
            self.setPlainText('No recent comments.')
            return
        size = max(20, self.fontMetrics().height())
        rows = []
        for parts in self.comments:
            content = []
            for part in parts:
                key = self.urls.get(part.get('emote_url'))
                if key in self.images:
                    content.append(f'<a href="{key}"><img src="{key}" width="{size}" height="{size}" alt="[Emote]"></a>')
                else:
                    content.append(html.escape(part.get('text', '')).replace('\n', '<br>'))
            rows.append('<p>' + (''.join(content) or '(Empty comment)') + '</p>')
        position = self.verticalScrollBar().value()
        self.setHtml(''.join(rows))
        self.verticalScrollBar().setValue(position)

    def fetch_emote(self, url, key):
        request = QNetworkRequest(QUrl(url))
        # This manager has no host-account cookies. Redirects are not followed.
        request.setAttribute(QNetworkRequest.RedirectPolicyAttribute, QNetworkRequest.ManualRedirectPolicy)
        request.setAttribute(QNetworkRequest.CookieLoadControlAttribute, QNetworkRequest.Manual)
        request.setAttribute(QNetworkRequest.CookieSaveControlAttribute, QNetworkRequest.Manual)
        request.setTransferTimeout(8000)
        reply = self.network.get(request)
        reply.setReadBufferSize(self.MAX_IMAGE_BYTES + 1)
        self.pending.add(reply)
        generation, content = self.generation, bytearray()
        timer = QTimer(reply)
        timer.setSingleShot(True)
        timer.timeout.connect(reply.abort)
        timer.start(8000)

        def read():
            if generation != self.generation:
                return
            content.extend(bytes(reply.readAll()))
            if len(content) > self.MAX_IMAGE_BYTES:
                reply.abort()

        def finished():
            timer.stop()
            self.pending.discard(reply)
            try:
                if generation != self.generation or reply.error() != QNetworkReply.NoError:
                    return
                read()
                if len(content) > self.MAX_IMAGE_BYTES or reply.attribute(QNetworkRequest.HttpStatusCodeAttribute) != 200:
                    return
                buffer = QBuffer()
                buffer.setData(QByteArray(content))
                buffer.open(QIODevice.ReadOnly)
                reader = QImageReader(buffer)
                size = reader.size()
                if (bytes(reader.format()).lower() not in (b'png', b'jpeg', b'gif', b'webp')
                        or not size.isValid() or size.width() > 2048 or size.height() > 2048):
                    return
                reader.setScaledSize(size.scaled(160, 160, Qt.KeepAspectRatio))
                image = reader.read()
                if not image.isNull():
                    self.images[key] = image
                    self.document().addResource(QTextDocument.ImageResource, QUrl(key), image)
                    self.render_comments()
            finally:
                reply.deleteLater()

        reply.readyRead.connect(read)
        reply.finished.connect(finished)

    def emote_tooltip(self, url):
        image = self.images.get(url.toString())
        if image is None:
            self.setToolTip('')
            return
        buffer = QBuffer()
        buffer.open(QIODevice.WriteOnly)
        image.scaled(88, 88, Qt.KeepAspectRatio, Qt.SmoothTransformation).save(buffer, 'PNG')
        encoded = base64.b64encode(bytes(buffer.data())).decode('ascii')
        self.setToolTip(f'<img src="data:image/png;base64,{encoded}" alt="Emote preview">')

    def preview_emote(self, url):
        image = self.images.get(url.toString())
        if image is None:
            return
        dialog = AccentDialog(self)
        dialog.setWindowTitle('Emote preview')
        layout = QVBoxLayout(dialog)
        preview = QLabel()
        preview.setAccessibleName('Viewer comment emote')
        preview.setAlignment(Qt.AlignCenter)
        preview.setPixmap(QPixmap.fromImage(image).scaled(160, 160, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        layout.addWidget(preview)
        close = PushButton('Close')
        close.clicked.connect(dialog.reject)
        layout.addWidget(close)
        style_controls(dialog)
        dialog.exec()
        dialog.deleteLater()


class ViewerContributionsDialog(AccentDialog):
    def __init__(self, stream_factory, *, room_id, viewer_id, viewer_name='', expected_user_id='',
                 priority_region='', is_current=lambda: True, parent=None, auto_refresh=True):
        super().__init__(parent)
        self.stream_factory = stream_factory
        self.room_id, self.viewer_id = str(room_id), str(viewer_id)
        self.user_id, self.priority_region = str(expected_user_id), priority_region
        self.is_current = is_current
        self.invalidated = Event()
        self.busy, self.closed = False, False
        self.state = None
        self.setWindowTitle('Contributions to this LIVE')
        font_scale = max(1.0, point_font(QApplication.font()).pointSizeF() / 12.0)
        available_height = self.screen().availableGeometry().height() - 60
        self.resize(560, min(round(610 * font_scale), max(610, available_height)))
        self.setMinimumSize(420, 430)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)
        self.viewer_label = label(viewer_name or f'Viewer {self.viewer_id}')
        font = point_font(self.viewer_label.font())
        font.setBold(True)
        self.viewer_label.setFont(font)
        layout.addWidget(self.viewer_label)
        self.identity_label = label(f'Viewer lookup: {self.viewer_id}')
        layout.addWidget(self.identity_label)
        self.toggle = PushButton('Contributions to this LIVE ▾')
        self.toggle.setCheckable(True)
        self.toggle.setChecked(True)
        layout.addWidget(self.toggle, 0, Qt.AlignLeft)
        self.content = QWidget()
        content = QVBoxLayout(self.content)
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(12)
        self.follow_label = label()
        self.follow_label.hide()
        content.addWidget(self.follow_label)
        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(12)
        self.metrics = {}
        for index, (key, title) in enumerate((('watch_duration', 'Watch time'), ('like_count', 'Likes'),
                                             ('share_count', 'Shares'), ('comment_count', 'Comments'))):
            cell = QVBoxLayout()
            cell.setSpacing(4)
            cell.addWidget(label(title))
            value = label('Unavailable')
            value.setAccessibleName(title)
            value.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            value_font = point_font(value.font())
            value_font.setPointSizeF(value_font.pointSizeF() * 1.2)
            value_font.setBold(True)
            value.setFont(value_font)
            value.setMinimumHeight(value.fontMetrics().height() + 2)
            self.metrics[key] = value
            cell.addWidget(value)
            grid.addLayout(cell, index // 2, index % 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        content.addLayout(grid)
        content.addWidget(label('Latest comments'))
        self.comments = ContributionComments(self)
        self.comments.setMinimumHeight(100)
        content.addWidget(self.comments, 1)
        self.comment_note = label('Up to the last 10 comments, as reported by TikTok.')
        content.addWidget(self.comment_note)
        layout.addWidget(self.content, 1)
        self.toggle.toggled.connect(self.toggle_content)
        self.status = label('Refresh to load this viewer’s contributions.')
        self.spinner = IndeterminateProgressRing(self)
        self.spinner.setFixedSize(24, 24)
        status_row = QHBoxLayout()
        status_row.addWidget(self.spinner)
        status_row.addWidget(self.status, 1)
        layout.addLayout(status_row)
        footer = QHBoxLayout()
        footer.setSpacing(10)
        self.refresh_button, self.close_button = PushButton('Refresh'), PushButton('Close')
        footer.addWidget(self.refresh_button)
        footer.addStretch(1)
        footer.addWidget(self.close_button)
        layout.addLayout(footer)
        self.refresh_button.clicked.connect(self.refresh)
        self.close_button.clicked.connect(self.reject)
        self.context_timer = QTimer(self)
        self.context_timer.setInterval(250)
        self.context_timer.timeout.connect(self.update_controls)
        self.context_timer.start()
        style_controls(self)
        self.update_controls()
        if auto_refresh:
            single_shot(self, 0, self.refresh)

    def toggle_content(self, expanded):
        self.content.setVisible(expanded)
        self.toggle.setText('Contributions to this LIVE ' + ('▾' if expanded else '▸'))

    def _current(self):
        if self.closed or not self.is_current():
            self.invalidated.set()
        return not self.invalidated.is_set()

    def clear_data(self):
        self.state = None
        self.follow_label.clear()
        self.follow_label.hide()
        for widget in self.metrics.values():
            widget.setText('Unavailable')
        self.comments.set_comments(None)

    def update_controls(self):
        current = self._current()
        self.refresh_button.setEnabled(current and not self.busy and bool(self.room_id))
        self.spinner.setVisible(self.busy and current)
        if not current:
            if self.state is not None or self.comments.pending:
                self.clear_data()
            self.status.setText('The account or LIVE changed. Close this window and reopen it for the current session.')

    def refresh(self):
        if self.busy or not self._current():
            self.update_controls()
            return
        self.busy = True
        self.comments.cancel_images()
        self.status.setText('Refreshing… Previous values remain visible until the request finishes.'
                            if self.state else 'Loading viewer contributions…')
        self.update_controls()
        factory, room, viewer, owner, region = (self.stream_factory, self.room_id, self.viewer_id,
                                               self.user_id, self.priority_region)
        invalidated = self.invalidated

        def operation():
            with factory() as stream:
                return ViewerContributions(stream, room_id=room, expected_user_id=owner,
                    priority_region=region, is_current=lambda: not invalidated.is_set()).load(viewer)

        def completed(state):
            self.busy = False
            if not self._current():
                self.update_controls()
                return
            self.user_id = state['account_id']
            # Resolve once, then keep Refresh bound to the stable viewer ID.
            self.viewer_id = state['viewer_id']
            self.identity_label.setText(f'User ID: {self.viewer_id}')
            if state.get('viewer_username'):
                handle = '@' + state['viewer_username']
                self.viewer_label.setText((state['viewer_name'] + ' · ' + handle)
                                          if state.get('viewer_name') else handle)
            self.state = state
            self.metrics['watch_duration'].setText(watch_time_text(state['watch_duration']))
            for key in ('like_count', 'share_count', 'comment_count'):
                value = state[key]
                self.metrics[key].setText(QLocale().toString(value) if value is not None else 'Unavailable')
            days = state['follow_days']
            self.follow_label.setText(f'Followed you for {QLocale().toString(days)} ' + ('day' if days == 1 else 'days')
                                      if days is not None else '')
            self.follow_label.setVisible(days is not None)
            self.comments.set_comments(state['comments'])
            stamp = QLocale().toString(QDateTime.currentDateTime().time(), QLocale.ShortFormat)
            self.status.setText(f'Updated {stamp}. Watch time is reported in rounded minutes.'
                                + ('\n' + state['warning'] if state['warning'] else ''))
            self.update_controls()

        def failed(error):
            self.busy = False
            self.clear_data()
            self.status.setText(str(error))
            self.update_controls()

        BackgroundTask(self, Work(operation), completed, failed).start()

    def done(self, result):
        self.closed = True
        self.invalidated.set()
        self.context_timer.stop()
        self.comments.cancel_images()
        super().done(result)

    def closeEvent(self, event):
        self.done(0)
        event.accept()
