from __future__ import annotations

from PySide6.QtWidgets import QWidget


MODERN_WINDOW_STYLE = """
QWidget {
    background: #f4f1ea;
    color: #1f2a30;
    font-size: 13px;
}
QMainWindow, QDialog {
    background: #f4f1ea;
}
QLabel[role="hero"] {
    font-size: 20px;
    font-weight: 700;
    color: #17313b;
}
QLabel[role="muted"] {
    color: #5d6b71;
}
QLabel[role="hint"] {
    color: #35515b;
    background: #e8f0f0;
    border: 1px solid #c4d4d6;
    border-radius: 10px;
    padding: 10px 12px;
}
QLabel[role="warning"] {
    color: #7a4d18;
    background: #fff0d7;
    border: 1px solid #e0b36c;
    border-radius: 10px;
    padding: 10px 12px;
}
QGroupBox {
    border: 1px solid #d5dfdf;
    border-radius: 14px;
    margin-top: 14px;
    padding: 14px;
    background: #fbfaf6;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: #17313b;
}
QFrame[card="true"] {
    background: #fbfaf6;
    border: 1px solid #d5dfdf;
    border-radius: 14px;
}
QLineEdit, QPlainTextEdit, QListWidget, QComboBox, QSpinBox, QTabWidget::pane, QScrollArea {
    background: #fffdf9;
    border: 1px solid #cad6d8;
    border-radius: 10px;
}
QLineEdit, QComboBox, QSpinBox {
    min-height: 34px;
    padding: 4px 8px;
}
QPlainTextEdit, QListWidget {
    padding: 8px;
}
QPushButton {
    background: #1e6a78;
    color: white;
    border: none;
    border-radius: 10px;
    min-height: 36px;
    padding: 6px 12px;
    font-weight: 600;
}
QPushButton:hover {
    background: #195a66;
}
QPushButton:disabled {
    background: #9db1b6;
    color: #eef3f4;
}
QTabBar::tab {
    background: #e3e7e0;
    color: #294049;
    border-top-left-radius: 10px;
    border-top-right-radius: 10px;
    padding: 8px 14px;
    margin-right: 4px;
}
QTabBar::tab:selected {
    background: #fbfaf6;
    color: #17313b;
}
QProgressBar {
    border: 1px solid #cad6d8;
    border-radius: 9px;
    background: #eaf0f1;
    min-height: 18px;
    text-align: center;
}
QProgressBar::chunk {
    background: #1e6a78;
    border-radius: 8px;
}
QCheckBox {
    spacing: 8px;
}
QScrollArea {
    background: transparent;
}
QScrollArea > QWidget > QWidget {
    background: #f4f1ea;
}
QScrollBar:vertical {
    background: #e7eceb;
    width: 12px;
    margin: 8px 2px 8px 2px;
    border-radius: 6px;
}
QScrollBar::handle:vertical {
    background: #8aa7ae;
    min-height: 30px;
    border-radius: 6px;
}
QScrollBar:horizontal {
    background: #e7eceb;
    height: 12px;
    margin: 2px 8px 2px 8px;
    border-radius: 6px;
}
QScrollBar::handle:horizontal {
    background: #8aa7ae;
    min-width: 30px;
    border-radius: 6px;
}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {
    background: transparent;
    border: none;
}
"""


def apply_modern_window_style(widget: QWidget) -> None:
    widget.setStyleSheet(MODERN_WINDOW_STYLE)
