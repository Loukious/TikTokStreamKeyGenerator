"""Exercise animated menu opening through the actual dropdown click path."""
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from qfluentwidgets import MenuAnimationType
from Libs.fluent_ui import Action, CheckableMenu, DropDownPushButton, RoundMenu


class MenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def dispose(self, widget):
        widget.close()
        widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_both_menu_types_accept_animation_keywords(self):
        for cls in (RoundMenu, CheckableMenu):
            with self.subTest(menu=cls.__name__):
                menu = cls('Test')
                self.addCleanup(self.dispose, menu)
                menu.addAction(Action('Test action', menu))
                for animation in (MenuAnimationType.DROP_DOWN, MenuAnimationType.PULL_UP):
                    menu.exec(QPoint(30, 30), aniType=animation)
                    self.assertTrue(menu.isVisible())
                    self.assertIsNotNone(menu.aniManager)
                    menu.hide()

    def test_mouse_click_opens_both_dropdown_menu_types(self):
        for cls in (RoundMenu, CheckableMenu):
            with self.subTest(menu=cls.__name__):
                button = DropDownPushButton('Menu')
                self.addCleanup(self.dispose, button)
                menu = cls('Test', button)
                menu.addAction(Action('Test action', menu))
                button.setMenu(menu)
                button.show()
                self.app.processEvents()
                QTest.mouseClick(button, Qt.LeftButton)
                self.assertTrue(menu.isVisible())
                menu.hide()
                button.hide()


if __name__ == '__main__':
    unittest.main()
