"""Offline packaged-runtime check. Does not read user config or contact TikTok."""


def run(log=None):
    def checkpoint(message):
        print(message, file=log, flush=True)
    checkpoint('Packaged module imports completed')
    import importlib
    from pathlib import Path
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget
    from qfluentwidgets import IndeterminateProgressRing
    from Libs.fluent_ui import PushButton, LineEdit, TableWidget
    from Libs.signing_backend import is_development
    import websockets.sync.client
    import curl_cffi
    import tzdata
    import certifi

    if not Path(certifi.where()).is_file():
        raise RuntimeError('The packaged HTTPS certificate bundle is missing')
    if is_development():
        raise RuntimeError('Release smoke test requires the hosted signing backend')
    for name in ('mobile_device_gen', 'client_profiles', 'live_chat', 'campaign_ui',
                 'studio_import_ui', 'ffmpeg_sei_proxy', 'gui_tasks', 'error_reporting'):
        importlib.import_module('Libs.' + name)
    checkpoint('Creating QApplication')
    app = QApplication.instance() or QApplication([])
    widget = QWidget()
    layout = QVBoxLayout(widget)
    checkpoint('Creating Fluent widgets')
    for child in (PushButton('Runtime check'), LineEdit(), TableWidget(), IndeterminateProgressRing()):
        layout.addWidget(child)
    widget.show()
    QTimer.singleShot(100, app.quit)
    checkpoint('Entering the Qt event loop')
    result = app.exec()
    checkpoint('Runtime check completed')
    return result
