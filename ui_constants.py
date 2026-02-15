SETTINGS_ENABLED_TIERS = "enabled_tiers"
SETTINGS_CRAFT_6X6_UNLOCKED = "crafting_6x6_unlocked"
SETTINGS_CRAFTING_GRIDS = "crafting_grids"
SETTINGS_THEME = "theme"
SETTINGS_TIER_LIST = "tier_list"
SETTINGS_MACHINE_TIER_FILTER = "machine_tier_filter"
SETTINGS_MACHINE_UNLOCKED_ONLY = "machine_unlocked_only"
SETTINGS_MACHINE_SORT_MODE = "machine_sort_mode"
SETTINGS_MACHINE_SEARCH = "machine_search"
SETTINGS_ACTIVE_STORAGE_ID = "active_storage_id"

DARK_STYLESHEET = """
QWidget {
    background-color: #1e1f22;
    color: #f0f0f0;
    font-size: 12px;
}
QMainWindow::separator {
    background: #3a3c40;
    width: 1px;
    height: 1px;
}
QMenuBar, QMenu, QMenuBar::item, QMenu::item {
    background-color: #1e1f22;
    color: #f0f0f0;
}
QMenu::item:selected, QMenuBar::item:selected {
    background-color: #2f3136;
}
QToolTip {
    background-color: #2b2d31;
    color: #ffffff;
    border: 1px solid #3a3c40;
}
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox, QDateEdit, QTimeEdit,
QDateTimeEdit, QDoubleSpinBox, QAbstractSpinBox {
    background-color: #2b2d31;
    color: #f0f0f0;
    border: 1px solid #3a3c40;
    border-radius: 4px;
    padding: 4px;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus,
QComboBox:focus, QDateEdit:focus, QTimeEdit:focus, QDateTimeEdit:focus,
QDoubleSpinBox:focus, QAbstractSpinBox:focus {
    border: 1px solid #4f8cff;
}
QPushButton, QToolButton {
    background-color: #2f3136;
    color: #f0f0f0;
    border: 1px solid #3a3c40;
    border-radius: 4px;
    padding: 6px 10px;
}
QPushButton:hover, QToolButton:hover {
    background-color: #3a3c40;
}
QPushButton:pressed, QToolButton:pressed {
    background-color: #4b4e54;
}
QTabWidget::pane {
    border: 1px solid #3a3c40;
    background-color: #1e1f22;
}
QTabBar::tab {
    background-color: #2b2d31;
    color: #f0f0f0;
    padding: 6px 12px;
    border: 1px solid #3a3c40;
    border-bottom: none;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background-color: #1e1f22;
}
QTabBar::tab:hover {
    background-color: #3a3c40;
}
QTreeView, QListView, QTableView, QTreeWidget, QTableWidget, QListWidget {
    background-color: #1f2124;
    alternate-background-color: #26282c;
    color: #f0f0f0;
    gridline-color: #3a3c40;
    border: 1px solid #3a3c40;
}
QHeaderView::section {
    background-color: #2b2d31;
    color: #f0f0f0;
    border: 1px solid #3a3c40;
    padding: 4px;
}
QCheckBox, QRadioButton {
    spacing: 6px;
}
QCheckBox::indicator, QRadioButton::indicator {
    width: 14px;
    height: 14px;
}
QCheckBox::indicator:unchecked, QRadioButton::indicator:unchecked {
    border: 1px solid #3a3c40;
    background-color: #1e1f22;
}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {
    border: 1px solid #4f8cff;
    background-color: #4f8cff;
}
QSlider::groove:horizontal {
    background-color: #3a3c40;
    height: 6px;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    background-color: #4f8cff;
    width: 14px;
    margin: -4px 0;
    border-radius: 7px;
}
QStatusBar {
    background-color: #1e1f22;
    color: #bfc3c9;
}
QScrollBar:vertical, QScrollBar:horizontal {
    background-color: #1e1f22;
}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
    background-color: #3a3c40;
    border-radius: 4px;
}
QScrollBar::add-line, QScrollBar::sub-line {
    background: none;
    border: none;
}
"""

LIGHT_STYLESHEET = """
QWidget {
    background-color: #f2f2f2;
    color: #1b1b1b;
    font-size: 12px;
}
QMainWindow::separator {
    background: #c9c9c9;
    width: 1px;
    height: 1px;
}
QMenuBar, QMenu, QMenuBar::item, QMenu::item {
    background-color: #f2f2f2;
    color: #1b1b1b;
}
QMenu::item:selected, QMenuBar::item:selected {
    background-color: #e2e2e2;
}
QToolTip {
    background-color: #ffffff;
    color: #1b1b1b;
    border: 1px solid #c9c9c9;
}
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox, QDateEdit, QTimeEdit,
QDateTimeEdit, QDoubleSpinBox, QAbstractSpinBox {
    background-color: #ffffff;
    color: #1b1b1b;
    border: 1px solid #c9c9c9;
    border-radius: 4px;
    padding: 4px;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus,
QComboBox:focus, QDateEdit:focus, QTimeEdit:focus, QDateTimeEdit:focus,
QDoubleSpinBox:focus, QAbstractSpinBox:focus {
    border: 1px solid #2f6feb;
}
QPushButton, QToolButton {
    background-color: #ededed;
    color: #1b1b1b;
    border: 1px solid #c9c9c9;
    border-radius: 4px;
    padding: 6px 10px;
}
QPushButton:hover, QToolButton:hover {
    background-color: #e0e0e0;
}
QPushButton:pressed, QToolButton:pressed {
    background-color: #d6d6d6;
}
QTabWidget::pane {
    border: 1px solid #c9c9c9;
    background-color: #f2f2f2;
}
QTabBar::tab {
    background-color: #e6e6e6;
    color: #1b1b1b;
    padding: 6px 12px;
    border: 1px solid #c9c9c9;
    border-bottom: none;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background-color: #f2f2f2;
}
QTabBar::tab:hover {
    background-color: #dedede;
}
QTreeView, QListView, QTableView, QTreeWidget, QTableWidget, QListWidget {
    background-color: #ffffff;
    alternate-background-color: #f5f5f5;
    color: #1b1b1b;
    gridline-color: #c9c9c9;
    border: 1px solid #c9c9c9;
}
QHeaderView::section {
    background-color: #ededed;
    color: #1b1b1b;
    border: 1px solid #c9c9c9;
    padding: 4px;
}
QCheckBox, QRadioButton {
    spacing: 6px;
}
QCheckBox::indicator, QRadioButton::indicator {
    width: 14px;
    height: 14px;
}
QCheckBox::indicator:unchecked, QRadioButton::indicator:unchecked {
    border: 1px solid #c9c9c9;
    background-color: #f2f2f2;
}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {
    border: 1px solid #2f6feb;
    background-color: #2f6feb;
}
QSlider::groove:horizontal {
    background-color: #c9c9c9;
    height: 6px;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    background-color: #2f6feb;
    width: 14px;
    margin: -4px 0;
    border-radius: 7px;
}
QStatusBar {
    background-color: #f2f2f2;
    color: #4a4a4a;
}
QScrollBar:vertical, QScrollBar:horizontal {
    background-color: #f2f2f2;
}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
    background-color: #c9c9c9;
    border-radius: 4px;
}
QScrollBar::add-line, QScrollBar::sub-line {
    background: none;
    border: none;
}
"""
