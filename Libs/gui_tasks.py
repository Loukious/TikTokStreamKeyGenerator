"""Run blocking operations in workers; resume UI workflows on Qt's thread."""
import threading
from functools import wraps

from PySide6.QtCore import QObject, Qt, QTimer, Signal, Slot
from PySide6.QtWidgets import QHBoxLayout, QLabel
from qfluentwidgets import IndeterminateProgressRing
from Libs.fluent_ui import AccentDialog, PushButton


def single_shot(owner, delay, callback):
    """An owned timer cannot invoke callbacks after its window is destroyed."""
    timer = QTimer(owner)
    timer.setSingleShot(True)
    timer.timeout.connect(callback)
    timer.timeout.connect(timer.deleteLater)
    timer.start(delay)
    return timer


class Work:
    def __init__(self, function, *args, label='', **kwargs):
        self.function, self.args, self.kwargs, self.label = function, args, kwargs, label

    def run(self):
        return self.function(*self.args, **self.kwargs)


class BackgroundTask(QObject):
    completed = Signal(object, object)

    def __init__(self, owner, work, success, failure):
        super().__init__(owner)
        self.work, self.success, self.failure = work, success, failure
        self.completed.connect(self.deliver, Qt.QueuedConnection)

    def start(self):
        def worker():
            try:
                result, error = self.work.run(), None
            except Exception as exc:
                result, error = None, exc
            try:
                self.completed.emit(result, error)
            except RuntimeError:
                pass  # Owner was destroyed; no UI callbacks after destruction.
        try:
            threading.Thread(target=worker, daemon=True, name='gui-operation').start()
        except Exception as exc:
            self.completed.emit(None, exc)
        return self

    @Slot(object, object)
    def deliver(self, result, error):
        try:
            if error is None:
                self.success(result)
            else:
                self.failure(error)
        finally:
            self.deleteLater()


class BusyDialog(AccentDialog):
    def __init__(self, owner, text):
        super().__init__(owner)
        self.setWindowTitle('Please wait')
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowFlag(Qt.WindowCloseButtonHint, False)
        layout = QHBoxLayout(self)
        self.ring = IndeterminateProgressRing(self)
        self.ring.setFixedSize(32, 32)
        self.label = QLabel(text, self)
        self.label.setWordWrap(True)
        layout.addWidget(self.ring)
        layout.addWidget(self.label)
        self.cancel_button = PushButton('Cancel', self)
        self.cancel_button.hide()
        layout.addWidget(self.cancel_button)
        self.cancel_callback = None
        self.setMinimumWidth(340)

    def reject(self):
        if self.cancel_callback is not None:
            self.cancel_callback()


class ForegroundTask(QObject):
    def __init__(self, owner, workflow, label, cancellable=False):
        super().__init__(owner)
        self.owner, self.workflow = owner, workflow
        self.dialog = BusyDialog(owner, label)
        self.cancel_event = threading.Event()
        if cancellable:
            self.dialog.cancel_callback = self.cancel
            self.dialog.cancel_button.clicked.connect(self.cancel)
            self.dialog.cancel_button.show()

    def cancel(self):
        self.cancel_event.set()
        self.dialog.cancel_button.setEnabled(False)
        self.dialog.label.setText('Cancelling login…')

    def advance(self, result=None, error=None):
        self.dialog.hide()
        try:
            work = self.workflow.throw(error) if error is not None else self.workflow.send(result)
            if not isinstance(work, Work):
                raise TypeError('UI workflows must yield a Work operation')
        except StopIteration:
            self.finish()
            return
        except Exception as exc:
            self.finish()
            self.owner.show_error(exc)
            return
        if work.label:
            self.dialog.label.setText(work.label)
        self.dialog.show()
        BackgroundTask(self, work, self.advance,
                       lambda exc: self.advance(error=exc)).start()

    def finish(self):
        self.owner._foreground_task = None
        self.dialog.hide()
        self.dialog.deleteLater()
        self.owner.update_stream_controls()
        self.owner.sync_anchor_heartbeat_timer()
        self.owner.check_ffmpeg_proxy_health()
        if getattr(self.owner, '_close_after_task', False):
            single_shot(self.owner, 0, self.owner.close)
        self.deleteLater()


def foreground(label, *, cancellable=False):
    """Decorate a generator whose yielded calls run outside Qt's thread."""
    def decorate(function):
        @wraps(function)
        def start(owner, *args, **kwargs):
            if getattr(owner, '_foreground_task', None) is not None:
                return
            task = ForegroundTask(owner, function(owner, *args, **kwargs), label, cancellable)
            owner._foreground_task = task
            owner.anchor_heartbeat_timer.stop()
            owner.update_stream_controls()
            single_shot(task, 0, task.advance)
            return task
        return start
    return decorate


def wait_for_login_callback(event, cancel, timeout=180):
    import time
    deadline = time.monotonic() + timeout
    while not cancel.is_set() and time.monotonic() < deadline:
        if event.wait(timeout=min(0.1, max(0, deadline - time.monotonic()))):
            return True
    return False


def reap_processes(processes, reports=()):
    """Release detached child processes and logs without blocking Qt."""
    import os
    import signal
    for process, log in processes:
        try:
            if process is not None and process.poll() is None:
                try:
                    if os.name == 'nt':
                        process.send_signal(signal.CTRL_BREAK_EVENT)
                    else:
                        process.terminate()
                    process.wait(timeout=5)
                except Exception:
                    process.kill()
                    process.wait(timeout=5)
        except Exception:
            pass
        finally:
            if log is not None:
                try:
                    log.close()
                except Exception:
                    pass
    for path in reports:
        try:
            os.remove(path)
        except OSError:
            pass
