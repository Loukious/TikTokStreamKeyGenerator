"""Execute generator workflows synchronously only in deterministic unit tests."""
from Libs.gui_tasks import Work


def drive_workflow(workflow):
    result, error = None, None
    while True:
        try:
            work = workflow.throw(error) if error is not None else workflow.send(result)
        except StopIteration as done:
            return done.value
        assert isinstance(work, Work)
        try:
            result, error = work.run(), None
        except Exception as exc:
            result, error = None, exc


def wait_until(predicate, seconds=3):
    import time
    from PySide6.QtTest import QTest
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        QTest.qWait(10)
    if not predicate():
        raise AssertionError('Qt operation did not complete')
