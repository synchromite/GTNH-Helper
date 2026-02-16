from __future__ import annotations

from PySide6 import QtCore, QtWidgets

_INSTALLED = False
_ORIG_MESSAGEBOX_FUNCS: dict[str, object] = {}
_ORIG_INPUT_FUNCS: dict[str, object] = {}


def _autosize_message_box(dialog: QtWidgets.QMessageBox, message: str) -> None:
    dialog.setTextFormat(QtCore.Qt.TextFormat.PlainText)
    dialog.setSizeGripEnabled(True)
    longest_line = max((len(line) for line in (message or "").splitlines()), default=40)
    approx_width = max(420, min(980, int(longest_line * 7.2) + 80))
    dialog.setMinimumWidth(approx_width)

    label = dialog.findChild(QtWidgets.QLabel, "qt_msgbox_label")
    if label is not None:
        label.setWordWrap(True)
        label.setMinimumWidth(max(200, approx_width - 50))

    layout = dialog.layout()
    if layout is not None:
        layout.setSizeConstraint(QtWidgets.QLayout.SizeConstraint.SetMinimumSize)


def _show_message_box(
    parent,
    title: str,
    message: str,
    *,
    icon: QtWidgets.QMessageBox.Icon,
    buttons: QtWidgets.QMessageBox.StandardButtons = QtWidgets.QMessageBox.StandardButton.Ok,
    default_button: QtWidgets.QMessageBox.StandardButton = QtWidgets.QMessageBox.StandardButton.NoButton,
) -> QtWidgets.QMessageBox.StandardButton:
    dialog = QtWidgets.QMessageBox(parent)
    dialog.setIcon(icon)
    dialog.setWindowTitle(title)
    dialog.setText(message)
    dialog.setStandardButtons(buttons)
    if default_button != QtWidgets.QMessageBox.StandardButton.NoButton:
        dialog.setDefaultButton(default_button)
    _autosize_message_box(dialog, message)
    dialog.adjustSize()
    return dialog.exec()


def _warning(parent, title, message, *args, **kwargs):
    buttons = kwargs.get("buttons")
    if buttons is None and args:
        buttons = args[0]
    if buttons is None:
        buttons = QtWidgets.QMessageBox.StandardButton.Ok
    return _show_message_box(parent, title, message, icon=QtWidgets.QMessageBox.Icon.Warning, buttons=buttons)


def _information(parent, title, message, *args, **kwargs):
    buttons = kwargs.get("buttons")
    if buttons is None and args:
        buttons = args[0]
    if buttons is None:
        buttons = QtWidgets.QMessageBox.StandardButton.Ok
    return _show_message_box(parent, title, message, icon=QtWidgets.QMessageBox.Icon.Information, buttons=buttons)


def _critical(parent, title, message, *args, **kwargs):
    buttons = kwargs.get("buttons")
    if buttons is None and args:
        buttons = args[0]
    if buttons is None:
        buttons = QtWidgets.QMessageBox.StandardButton.Ok
    return _show_message_box(parent, title, message, icon=QtWidgets.QMessageBox.Icon.Critical, buttons=buttons)


def _question(parent, title, message, *args, **kwargs):
    buttons = kwargs.get("buttons")
    if buttons is None and args:
        buttons = args[0]
    if buttons is None:
        buttons = QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No

    default_button = kwargs.get("defaultButton")
    if default_button is None and len(args) > 1:
        default_button = args[1]
    if default_button is None:
        default_button = QtWidgets.QMessageBox.StandardButton.No

    return _show_message_box(
        parent,
        title,
        message,
        icon=QtWidgets.QMessageBox.Icon.Question,
        buttons=buttons,
        default_button=default_button,
    )


def _autosize_input_dialog(dialog: QtWidgets.QInputDialog, minimum_width: int = 420) -> None:
    dialog.setSizeGripEnabled(True)
    dialog.setMinimumWidth(minimum_width)
    layout = dialog.layout()
    if layout is not None:
        layout.setSizeConstraint(QtWidgets.QLayout.SizeConstraint.SetMinimumSize)
    dialog.adjustSize()


def _get_text(parent, title, label, *args, **kwargs):
    echo = args[0] if len(args) >= 1 else QtWidgets.QLineEdit.EchoMode.Normal
    text = args[1] if len(args) >= 2 else ""

    dialog = QtWidgets.QInputDialog(parent)
    dialog.setWindowTitle(title)
    dialog.setLabelText(label)
    dialog.setInputMode(QtWidgets.QInputDialog.InputMode.TextInput)
    dialog.setTextEchoMode(echo)
    dialog.setTextValue(text)
    _autosize_input_dialog(dialog)
    ok = dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted
    return dialog.textValue(), ok


def _get_int(parent, title, label, *args, **kwargs):
    value = int(args[0]) if len(args) >= 1 else 0
    minimum = int(args[1]) if len(args) >= 2 else -2147483647
    maximum = int(args[2]) if len(args) >= 3 else 2147483647
    step = int(args[3]) if len(args) >= 4 else 1

    dialog = QtWidgets.QInputDialog(parent)
    dialog.setWindowTitle(title)
    dialog.setLabelText(label)
    dialog.setInputMode(QtWidgets.QInputDialog.InputMode.IntInput)
    dialog.setIntRange(minimum, maximum)
    dialog.setIntStep(step)
    dialog.setIntValue(value)
    _autosize_input_dialog(dialog)
    ok = dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted
    return dialog.intValue(), ok


def _get_item(parent, title, label, items, *args, **kwargs):
    current = int(args[0]) if len(args) >= 1 else 0
    editable = bool(args[1]) if len(args) >= 2 else False

    dialog = QtWidgets.QInputDialog(parent)
    dialog.setWindowTitle(title)
    dialog.setLabelText(label)
    dialog.setInputMode(QtWidgets.QInputDialog.InputMode.TextInput)
    dialog.setComboBoxItems([str(v) for v in items])
    dialog.setComboBoxEditable(editable)
    if items:
        current = max(0, min(current, len(items) - 1))
        dialog.setTextValue(str(items[current]))
    _autosize_input_dialog(dialog)
    ok = dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted
    return dialog.textValue(), ok


def install_dialog_sizing_hooks() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    _ORIG_MESSAGEBOX_FUNCS.update(
        {
            "warning": QtWidgets.QMessageBox.warning,
            "information": QtWidgets.QMessageBox.information,
            "critical": QtWidgets.QMessageBox.critical,
            "question": QtWidgets.QMessageBox.question,
        }
    )
    QtWidgets.QMessageBox.warning = staticmethod(_warning)
    QtWidgets.QMessageBox.information = staticmethod(_information)
    QtWidgets.QMessageBox.critical = staticmethod(_critical)
    QtWidgets.QMessageBox.question = staticmethod(_question)

    _ORIG_INPUT_FUNCS.update(
        {
            "getText": QtWidgets.QInputDialog.getText,
            "getInt": QtWidgets.QInputDialog.getInt,
            "getItem": QtWidgets.QInputDialog.getItem,
        }
    )
    QtWidgets.QInputDialog.getText = staticmethod(_get_text)
    QtWidgets.QInputDialog.getInt = staticmethod(_get_int)
    QtWidgets.QInputDialog.getItem = staticmethod(_get_item)

    _INSTALLED = True
