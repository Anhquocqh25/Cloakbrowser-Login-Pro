APP_STYLE = """
QWidget {
    background-color: #ffffff;
    color: #172033;
    font-size: 14px;
}
QMainWindow, QDialog { background-color: #ffffff; }

QWidget#topbar {
    background-color: #ffffff;
    border-bottom: 1px solid #e5e8ed;
}
QLineEdit, QSpinBox, QComboBox, QPlainTextEdit {
    background-color: #ffffff;
    color: #172033;
    border: 1px solid #d9dee7;
    border-radius: 7px;
    padding: 8px 10px;
    selection-background-color: #c8f2eb;
}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {
    border-color: #24aa96;
}
QLineEdit#profileSearch {
    background-color: #f7f8fa;
    border-color: transparent;
    padding: 9px 12px;
}

QPushButton, QToolButton {
    background-color: #ffffff;
    color: #273044;
    border: 1px solid #d9dee7;
    border-radius: 7px;
    padding: 7px 12px;
    font-weight: 500;
}
QPushButton:hover, QToolButton:hover {
    background-color: #f5f7f9;
    border-color: #bfc7d4;
}
QPushButton:disabled { color: #a8afbb; background-color: #f8f9fa; }
QPushButton#tabButton {
    background-color: #f2f4f7;
    border: none;
    color: #111827;
    padding: 9px 15px;
    font-weight: 600;
}
QPushButton#primaryButton {
    background-color: #159d89;
    border-color: #159d89;
    color: white;
    padding: 9px 16px;
    font-weight: 600;
}
QPushButton#primaryButton:hover { background-color: #0d8977; }
QPushButton#quietButton { border-color: transparent; color: #667085; }
QPushButton#runButton {
    background-color: #ffffff;
    color: #07947f;
    border: 1px solid #55c7b6;
    border-radius: 6px;
    padding: 0px;
}
QPushButton#runButton:hover { background-color: #eefbf8; }
QPushButton#stopButton {
    background-color: #fff5f5;
    color: #c53d45;
    border: 1px solid #ef9da3;
    border-radius: 6px;
    padding: 0px;
}
QPushButton#columnButton {
    background-color: #ffffff;
    color: #536073;
    border: 1px solid #d9dee7;
    border-radius: 8px;
    padding: 8px 13px;
}
QPushButton#columnButton:hover { background-color: #f6f8fa; }
QToolButton#moreButton {
    border-color: transparent;
    color: #667085;
    font-size: 15px;
    padding: 5px;
}
QLabel#profileCount { color: #98a0ad; padding-left: 4px; }

QFrame#sidebar {
    background-color: #f7f8fa;
    border-right: 1px solid #e4e7ec;
}
QLabel#brandTitle { color: #111827; font-size: 19px; font-weight: 700; }
QLabel#brandSubtitle { color: #98a0ad; font-size: 12px; }
QLabel#sidebarFooter { color: #a0a7b3; font-size: 12px; padding: 8px; }
QPushButton#navButton {
    background-color: transparent;
    border: none;
    border-radius: 8px;
    text-align: left;
    padding: 9px 13px;
    color: #5f6b7d;
    font-weight: 500;
}
QPushButton#navButton:hover { background-color: #eef1f4; color: #172033; }
QPushButton#navButton:checked {
    background-color: #e5f5f1;
    color: #087d6d;
    font-weight: 600;
}
QStackedWidget#pages { background-color: #ffffff; }
QLabel#pageTitle { color: #172033; font-size: 24px; font-weight: 700; }
QLabel#pageSubtitle { color: #8a94a5; font-size: 13px; }

QTableWidget#profilesTable, QTableWidget#dataTable {
    background-color: #ffffff;
    alternate-background-color: #ffffff;
    border: 1px solid #e3e6eb;
    border-radius: 9px;
    gridline-color: transparent;
    selection-background-color: #f2faf8;
    selection-color: #172033;
}
QTableWidget#profilesTable::item, QTableWidget#dataTable::item {
    border-bottom: 1px solid #e7e9ed;
    padding: 10px 14px;
}
QHeaderView::section {
    background-color: #ffffff;
    color: #8791a4;
    border: none;
    border-bottom: 1px solid #dfe3e8;
    padding: 10px 14px;
    font-weight: 500;
}
QLabel#readyStatus { color: #435066; }
QLabel#runningStatus { color: #07947f; font-weight: 600; }
QLabel#busyStatus { color: #c17a12; }

QFrame#settingsCard {
    background-color: #ffffff;
    border: 1px solid #e3e6eb;
    border-radius: 9px;
}
QLabel#settingLabel { color: #7f8999; font-size: 12px; padding-top: 8px; }

QMenu {
    background-color: #ffffff;
    color: #172033;
    border: 1px solid #d9dee7;
    border-radius: 7px;
    padding: 6px;
}
QMenu::item { padding: 8px 28px 8px 12px; border-radius: 5px; }
QMenu::item:selected { background-color: #eef7f5; }
QMenu::separator { height: 1px; background: #e5e8ed; margin: 5px 8px; }

QLabel#dialogTitle { color: #172033; font-size: 21px; font-weight: 700; }
QLabel#hintLabel {
    color: #667085;
    background-color: #f7f9fb;
    border: 1px solid #e1e5eb;
    border-radius: 7px;
    padding: 10px;
}
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 17px; height: 17px; }
QCheckBox#columnCheck {
    background-color: #ffffff;
    border-radius: 7px;
    padding: 6px 9px;
    color: #344054;
}
QCheckBox#columnCheck:hover { background-color: #f5f8f7; }
QLabel#columnSection {
    color: #98a0ad;
    font-size: 12px;
    font-weight: 600;
    padding: 8px 5px 3px 5px;
}
QScrollArea, QScrollArea > QWidget > QWidget { background-color: #ffffff; }
QStatusBar {
    background-color: #ffffff;
    color: #7d8798;
    border-top: 1px solid #eceef1;
    min-height: 25px;
}
"""
