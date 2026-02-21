import os

import pytest

QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from services.db import connect_profile
from ui_dialogs import StorageUnitDialog


def _get_app() -> QtWidgets.QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def test_storage_unit_dialog_hides_container_managed_fields() -> None:
    _get_app()

    class DummyApp:
        def __init__(self) -> None:
            self.profile_conn = connect_profile(":memory:")

    dialog = StorageUnitDialog(DummyApp())

    assert not hasattr(dialog, "container_item_combo")
    labels = [label.text() for label in dialog.findChildren(QtWidgets.QLabel)]
    assert any("managed in the Containers" in text for text in labels)

    dialog.deleteLater()


def test_storage_unit_dialog_uses_default_storage_kind_options() -> None:
    _get_app()

    class DummyApp:
        def __init__(self) -> None:
            self.profile_conn = connect_profile(":memory:")

    dialog = StorageUnitDialog(DummyApp())

    labels = [dialog.kind_combo.itemText(i) for i in range(dialog.kind_combo.count())]
    values = [dialog.kind_combo.itemData(i) for i in range(dialog.kind_combo.count())]
    assert labels == ["Item Storage", "Gas Storage", "Liquid Storage"]
    assert values == ["item", "gas", "fluid"]

    dialog.deleteLater()
