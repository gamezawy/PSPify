# PSPify - Retro Game to PSP Homebrew Converter
# Copyright (C) 2026 Mahmoud Etman (Ruzzar)
# Licensed under the GNU General Public License v3 (see LICENSE).

"""
One import point for Qt.

PSPify runs on PyQt6 (preferred) and on PyQt5 (legacy build for old Windows).
Every other module imports Qt names from here, so the differences between the
two bindings live in this single file:

* scoped enums   Qt6 only has ``Qt.AlignmentFlag.AlignCenter``; Qt5 also has the
                 short form. ``_enum()`` finds whichever exists.
* exec()         ``exec_()`` on Qt5, ``exec()`` on Qt6.
* high DPI       automatic on Qt6, opt-in attributes on Qt5.

Set the environment variable PSPIFY_QT=5 to force PyQt5 when both are installed.
"""

import os

QT_API = 0
if os.environ.get("PSPIFY_QT") != "5":
    try:
        from PyQt6 import QtCore, QtGui, QtWidgets
        QT_API = 6
    except ImportError:
        pass
if not QT_API:
    try:
        from PyQt5 import QtCore, QtGui, QtWidgets
        QT_API = 5
    except ImportError as exc:
        raise ImportError("PSPify needs PyQt6 (or PyQt5). Install it with: pip install -r requirements-pyqt6.txt") from exc

# ---- classes ----------------------------------------------------------------
Qt = QtCore.Qt
QObject = QtCore.QObject
QThread = QtCore.QThread
QTimer = QtCore.QTimer
QSize = QtCore.QSize
QUrl = QtCore.QUrl
pyqtSignal = QtCore.pyqtSignal

QIcon = QtGui.QIcon
QPixmap = QtGui.QPixmap
QPalette = QtGui.QPalette
QColor = QtGui.QColor
QDesktopServices = QtGui.QDesktopServices

QApplication = QtWidgets.QApplication
QMainWindow = QtWidgets.QMainWindow
QWidget = QtWidgets.QWidget
QFrame = QtWidgets.QFrame
QLabel = QtWidgets.QLabel
QPushButton = QtWidgets.QPushButton
QCheckBox = QtWidgets.QCheckBox
QRadioButton = QtWidgets.QRadioButton
QButtonGroup = QtWidgets.QButtonGroup
QComboBox = QtWidgets.QComboBox
QLineEdit = QtWidgets.QLineEdit
QScrollArea = QtWidgets.QScrollArea
QStackedWidget = QtWidgets.QStackedWidget
QProgressBar = QtWidgets.QProgressBar
QVBoxLayout = QtWidgets.QVBoxLayout
QHBoxLayout = QtWidgets.QHBoxLayout
QGridLayout = QtWidgets.QGridLayout
QDialog = QtWidgets.QDialog
QFileDialog = QtWidgets.QFileDialog
QSizePolicy = QtWidgets.QSizePolicy


def _enum(owner, scope, name):
    """``Owner.Scope.Name`` on Qt6/new Qt5, ``Owner.Name`` on old Qt5 builds."""
    try:
        return getattr(getattr(owner, scope), name)
    except AttributeError:
        return getattr(owner, name)


# ---- enums used by the app --------------------------------------------------
AlignCenter = _enum(Qt, "AlignmentFlag", "AlignCenter")
AlignLeft = _enum(Qt, "AlignmentFlag", "AlignLeft")
AlignRight = _enum(Qt, "AlignmentFlag", "AlignRight")
AlignTop = _enum(Qt, "AlignmentFlag", "AlignTop")
AlignVCenter = _enum(Qt, "AlignmentFlag", "AlignVCenter")
FramelessWindowHint = _enum(Qt, "WindowType", "FramelessWindowHint")
DialogWindow = _enum(Qt, "WindowType", "Dialog")
ScrollBarAlwaysOff = _enum(Qt, "ScrollBarPolicy", "ScrollBarAlwaysOff")
KeepAspectRatio = _enum(Qt, "AspectRatioMode", "KeepAspectRatio")
SmoothTransformation = _enum(Qt, "TransformationMode", "SmoothTransformation")
PointingHandCursor = _enum(Qt, "CursorShape", "PointingHandCursor")
PlainText = _enum(Qt, "TextFormat", "PlainText")
RichText = _enum(Qt, "TextFormat", "RichText")
TextBrowserInteraction = _enum(Qt, "TextInteractionFlag", "TextBrowserInteraction")
TabFocus = _enum(Qt, "FocusPolicy", "TabFocus")
NoFrame = _enum(QFrame, "Shape", "NoFrame")
SizeExpanding = _enum(QSizePolicy, "Policy", "Expanding")
SizePreferred = _enum(QSizePolicy, "Policy", "Preferred")
SizeFixed = _enum(QSizePolicy, "Policy", "Fixed")
SizeIgnored = _enum(QSizePolicy, "Policy", "Ignored")
PaletteDisabled = _enum(QPalette, "ColorGroup", "Disabled")


def palette_role(name: str):
    """QPalette role by name, e.g. palette_role('Window')."""
    return _enum(QPalette, "ColorRole", name)


# ---- behaviour differences --------------------------------------------------
def exec_dialog(dialog) -> int:
    """Run a dialog modally (exec on Qt6, exec_ on Qt5)."""
    return dialog.exec() if hasattr(dialog, "exec") else dialog.exec_()


def exec_app(app) -> int:
    """Run the Qt event loop."""
    return app.exec() if hasattr(app, "exec") else app.exec_()


def prepare_high_dpi() -> None:
    """Qt5 needs these opt-ins before QApplication exists; Qt6 scales automatically."""
    if QT_API != 5:
        return
    for name in ("AA_EnableHighDpiScaling", "AA_UseHighDpiPixmaps"):
        try:
            QApplication.setAttribute(_enum(Qt, "ApplicationAttribute", name), True)
        except AttributeError:
            pass
