from __future__ import annotations

import json

from PySide6 import QtCore, QtWidgets

from services.planner import PlannerService
from services.db import connect, connect_profile
from ui_dialogs import AddRecipeDialog, ItemPickerDialog


class PlannerWorker(QtCore.QObject):
    finished = QtCore.Signal(object, object)

    def __init__(
        self,
        *,
        db_path,
        profile_db_path,
        target_item_id: int,
        target_qty: int,
        use_inventory: bool,
        enabled_tiers: list[str],
        crafting_6x6_unlocked: bool,
    ) -> None:
        super().__init__()
        self._db_path = db_path
        self._profile_db_path = profile_db_path
        self._target_item_id = target_item_id
        self._target_qty = target_qty
        self._use_inventory = use_inventory
        self._enabled_tiers = enabled_tiers
        self._crafting_6x6_unlocked = crafting_6x6_unlocked

    @QtCore.Slot()
    def run(self) -> None:
        content_conn = None
        profile_conn = None
        try:
            content_conn = connect(self._db_path, read_only=True)
            profile_path = self._profile_db_path or ":memory:"
            profile_conn = connect_profile(profile_path)
            planner = PlannerService(content_conn, profile_conn)
            result = planner.plan(
                self._target_item_id,
                self._target_qty,
                use_inventory=self._use_inventory,
                enabled_tiers=self._enabled_tiers,
                crafting_6x6_unlocked=self._crafting_6x6_unlocked,
            )
            self.finished.emit(result, None)
        except Exception as exc:
            self.finished.emit(None, exc)
        finally:
            if content_conn is not None:
                content_conn.close()
            if profile_conn is not None:
                profile_conn.close()


class PlannerTab(QtWidgets.QWidget):
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.planner = PlannerService(app.conn, app.profile_conn)
        self._planner_thread: QtCore.QThread | None = None
        self._planner_worker: PlannerWorker | None = None
        self._planner_mode: str | None = None

        self.target_item_id = None
        self.target_item_kind = None
        self.last_plan_run = False
        self.last_plan_used_inventory = False
        self.build_steps: list = []
        self.build_step_checks: list[QtWidgets.QCheckBox] = []
        self.build_step_labels: list[QtWidgets.QLabel] = []
        self.build_step_dependencies: list[set[int]] = []
        self.build_completed_steps: set[int] = set()
        self.build_base_inventory: dict[int, int] = {}
        self.build_step_byproducts: dict[int, list[tuple[int, int]]] = {}

        root_layout = QtWidgets.QVBoxLayout(self)
        root_layout.setContentsMargins(8, 8, 8, 8)
        root_layout.addWidget(
            QtWidgets.QLabel("Plan a target item into a shopping list and optional process steps.")
        )

        controls_widget = QtWidgets.QWidget()
        controls_layout = QtWidgets.QGridLayout(controls_widget)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.addWidget(controls_widget)

        controls_layout.addWidget(QtWidgets.QLabel("Target Item:"), 0, 0)
        self.target_item_name = QtWidgets.QLabel("(none)")
        self.target_item_name.setMinimumWidth(240)
        controls_layout.addWidget(self.target_item_name, 0, 1)
        self.btn_pick_item = QtWidgets.QPushButton("Select…")
        self.btn_pick_item.clicked.connect(self.pick_target_item)
        controls_layout.addWidget(self.btn_pick_item, 0, 2)

        controls_layout.addWidget(QtWidgets.QLabel("Quantity:"), 1, 0)
        self.target_qty_entry = QtWidgets.QLineEdit("1")
        self.target_qty_entry.setFixedWidth(80)
        controls_layout.addWidget(self.target_qty_entry, 1, 1, alignment=QtCore.Qt.AlignmentFlag.AlignLeft)
        self.target_qty_unit = QtWidgets.QLabel("")
        controls_layout.addWidget(self.target_qty_unit, 1, 2)

        self.use_inventory_checkbox = QtWidgets.QCheckBox("Use Inventory Data")
        self.use_inventory_checkbox.setChecked(True)
        controls_layout.addWidget(self.use_inventory_checkbox, 2, 0, 1, 2)

        self.show_steps_checkbox = QtWidgets.QCheckBox("Show Process Steps")
        self.show_steps_checkbox.setChecked(False)
        self.show_steps_checkbox.toggled.connect(self._toggle_steps)
        controls_layout.addWidget(self.show_steps_checkbox, 3, 0, 1, 2)

        btns_layout = QtWidgets.QVBoxLayout()
        self.btn_plan = QtWidgets.QPushButton("Plan")
        self.btn_build = QtWidgets.QPushButton("Build")
        self.btn_clear = QtWidgets.QPushButton("Clear")
        self.btn_save_plan = QtWidgets.QPushButton("Save Plan…")
        self.btn_load_plan = QtWidgets.QPushButton("Load Plan…")
        self.btn_plan.clicked.connect(self.run_plan)
        self.btn_build.clicked.connect(self.run_build)
        self.btn_clear.clicked.connect(self.clear_results)
        self.btn_save_plan.clicked.connect(self.save_plan)
        self.btn_load_plan.clicked.connect(self.load_plan)
        for btn in (self.btn_plan, self.btn_build, self.btn_clear, self.btn_save_plan, self.btn_load_plan):
            btns_layout.addWidget(btn)
        btns_layout.addStretch(1)
        controls_layout.addLayout(btns_layout, 0, 3, 4, 1)
        controls_layout.setColumnStretch(1, 1)

        self.main_splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        root_layout.addWidget(self.main_splitter, stretch=1)

        self.results_splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        self.main_splitter.addWidget(self.results_splitter)

        self.shopping_group = QtWidgets.QGroupBox("Shopping List")
        shopping_layout = QtWidgets.QVBoxLayout(self.shopping_group)
        shopping_header = QtWidgets.QHBoxLayout()
        shopping_layout.addLayout(shopping_header)
        shopping_header.addStretch(1)
        self.btn_save_shopping = QtWidgets.QPushButton("Save…")
        self.btn_copy_shopping = QtWidgets.QPushButton("Copy")
        self.btn_save_shopping.clicked.connect(
            lambda: self._save_text(self.shopping_text, "shopping_list.txt")
        )
        self.btn_copy_shopping.clicked.connect(
            lambda: self._copy_text(self.shopping_text, "Shopping list is empty.")
        )
        shopping_header.addWidget(self.btn_copy_shopping)
        shopping_header.addWidget(self.btn_save_shopping)
        self.shopping_text = QtWidgets.QTextEdit()
        self.shopping_text.setReadOnly(True)
        shopping_layout.addWidget(self.shopping_text, stretch=1)
        self._set_text(self.shopping_text, "Run a plan to see required items.")

        self.steps_group = QtWidgets.QGroupBox("Process Steps")
        steps_layout = QtWidgets.QVBoxLayout(self.steps_group)
        steps_header = QtWidgets.QHBoxLayout()
        steps_layout.addLayout(steps_header)
        steps_header.addStretch(1)
        self.btn_save_steps = QtWidgets.QPushButton("Save…")
        self.btn_copy_steps = QtWidgets.QPushButton("Copy")
        self.btn_save_steps.clicked.connect(
            lambda: self._save_text(self.steps_text, "process_steps.txt")
        )
        self.btn_copy_steps.clicked.connect(
            lambda: self._copy_text(self.steps_text, "Process steps are empty.")
        )
        steps_header.addWidget(self.btn_copy_steps)
        steps_header.addWidget(self.btn_save_steps)
        self.steps_text = QtWidgets.QTextEdit()
        self.steps_text.setReadOnly(True)
        steps_layout.addWidget(self.steps_text, stretch=1)
        self._set_text(self.steps_text, "Run a plan to see steps.")

        self.results_splitter.addWidget(self.shopping_group)
        self.results_splitter.addWidget(self.steps_group)

        self.build_group = QtWidgets.QGroupBox("Build Steps")
        build_layout = QtWidgets.QVBoxLayout(self.build_group)
        build_header = QtWidgets.QHBoxLayout()
        build_layout.addLayout(build_header)
        build_header.addWidget(QtWidgets.QLabel("Check off each step as you complete it."))
        build_header.addStretch(1)
        self.btn_reset_checks = QtWidgets.QPushButton("Reset Checks")
        self.btn_reset_checks.clicked.connect(self.reset_build_steps)
        build_header.addWidget(self.btn_reset_checks)

        self.build_scroll_area = QtWidgets.QScrollArea()
        self.build_scroll_area.setWidgetResizable(True)
        build_layout.addWidget(self.build_scroll_area, stretch=1)
        self.build_steps_container = QtWidgets.QWidget()
        self.build_steps_layout = QtWidgets.QVBoxLayout(self.build_steps_container)
        self.build_steps_layout.setContentsMargins(4, 4, 4, 4)
        self.build_steps_layout.setSpacing(6)
        self.build_steps_layout.addStretch(1)
        self.build_scroll_area.setWidget(self.build_steps_container)
        self._set_build_placeholder("Run a plan, then click Build to get step-by-step instructions.")

        self.main_splitter.addWidget(self.build_group)
        self.main_splitter.setStretchFactor(0, 2)
        self.main_splitter.setStretchFactor(1, 1)
        self.results_splitter.setStretchFactor(0, 1)
        self.results_splitter.setStretchFactor(1, 1)

        self._toggle_steps_visibility(persist=False)
        self._restore_state()

    def pick_target_item(self) -> None:
        if not self.app.items:
            QtWidgets.QMessageBox.information(self, "No items", "There are no items to plan against.")
            return
        dlg = ItemPickerDialog(self.app, title="Pick target item", parent=self)
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted or not dlg.result:
            return
        self.target_item_id = dlg.result["id"]
        self.target_item_kind = dlg.result["kind"]
        self.target_item_name.setText(dlg.result["name"])
        self.target_qty_unit.setText(self._unit_for_kind(self.target_item_kind))
        self._persist_state()

    def run_plan(self) -> None:
        if self.target_item_id is None:
            QtWidgets.QMessageBox.information(self, "Select an item", "Choose a target item first.")
            return
        qty = self._parse_target_qty(show_errors=True)
        if qty is None:
            return
        self._start_plan_worker(qty, mode="plan")

    def on_inventory_changed(self) -> None:
        if not self.last_plan_run or not self.last_plan_used_inventory or not self.use_inventory_checkbox.isChecked():
            return
        if self.target_item_id is None:
            return
        qty = self._parse_target_qty(show_errors=False)
        if qty is None:
            self.app.status_bar.showMessage("Planner not updated: invalid quantity.")
            return
        self._run_plan_with_qty(qty, set_status=False)
        self._refresh_build_inventory()
        self._refresh_build_steps_on_inventory_change(qty)

    def _parse_target_qty(self, *, show_errors: bool) -> int | None:
        raw_qty = self.target_qty_entry.text().strip()
        if raw_qty == "":
            if show_errors:
                QtWidgets.QMessageBox.critical(self, "Invalid quantity", "Enter a whole number.")
            return None
        try:
            qty_float = float(raw_qty)
        except ValueError:
            if show_errors:
                QtWidgets.QMessageBox.critical(self, "Invalid quantity", "Enter a whole number.")
            return None
        if not qty_float.is_integer() or qty_float <= 0:
            if show_errors:
                QtWidgets.QMessageBox.critical(self, "Invalid quantity", "Enter a whole number.")
            return None
        return int(qty_float)

    def _run_plan_with_qty(self, qty: int, *, set_status: bool) -> None:
        if not self._has_recipes():
            QtWidgets.QMessageBox.information(self, "No recipes", "There are no recipes to plan against.")
            if set_status:
                self.app.status_bar.showMessage("Planner failed: missing recipes")
            return

        result = self.planner.plan(
            self.target_item_id,
            qty,
            use_inventory=self.use_inventory_checkbox.isChecked(),
            enabled_tiers=self.app.get_enabled_tiers(),
            crafting_6x6_unlocked=self.app.is_crafting_6x6_unlocked(),
        )

        self._apply_plan_result(result, set_status=set_status)

    def _apply_plan_result(self, result, *, set_status: bool) -> None:
        if result.errors:
            filtered_errors = self._filter_plan_errors(result)
            if filtered_errors:
                self._handle_plan_errors(filtered_errors)
                self._set_text(self.shopping_text, "")
                self._set_text(self.steps_text, "")
                self.last_plan_run = False
                self.last_plan_used_inventory = False
                self._persist_state()
                return

        if not result.shopping_list:
            self._set_text(self.shopping_text, "Nothing needed. Inventory already covers this request.")
        else:
            lines = [f"{name} × {qty} {unit}" for name, qty, unit in result.shopping_list]
            self._set_text(self.shopping_text, "\n".join(lines))

        if result.steps:
            steps_lines = []
            for idx, step in enumerate(result.steps, start=1):
                inputs = ", ".join([f"{name} × {qty} {unit}" for _item_id, name, qty, unit in step.inputs])
                input_names = " + ".join([name for _item_id, name, _qty, _unit in step.inputs]) if step.inputs else "(none)"
                steps_lines.append(
                    f"{idx}. {input_names} → {step.output_item_name} "
                    f"(x{step.multiplier}, output {step.output_qty})\n"
                    f"   Inputs: {inputs if inputs else '(none)'}"
                )
            self._set_text(self.steps_text, "\n\n".join(steps_lines))
        else:
            self._set_text(self.steps_text, "No process steps generated.")

        self.last_plan_run = True
        self.last_plan_used_inventory = self.use_inventory_checkbox.isChecked()
        if set_status:
            self.app.status_bar.showMessage("Planner run complete")
        self._persist_state()

    def run_build(self) -> None:
        if self.target_item_id is None:
            QtWidgets.QMessageBox.information(self, "Select an item", "Choose a target item first.")
            return
        qty = self._parse_target_qty(show_errors=True)
        if qty is None:
            return
        if not self._has_recipes():
            QtWidgets.QMessageBox.information(self, "No recipes", "There are no recipes to plan against.")
            self.app.status_bar.showMessage("Build failed: missing recipes")
            return
        self._start_plan_worker(qty, mode="build")

    def _start_plan_worker(self, qty: int, *, mode: str) -> None:
        if self._planner_thread is not None:
            return
        if self.target_item_id is None:
            return

        self.planner = PlannerService(self.app.conn, self.app.profile_conn)
        self._set_planning_state(True, mode=mode)
        self._planner_mode = mode

        self._planner_thread = QtCore.QThread(self)
        self._planner_worker = PlannerWorker(
            db_path=self.app.db_path,
            profile_db_path=self.app.profile_db_path,
            target_item_id=self.target_item_id,
            target_qty=qty,
            use_inventory=self.use_inventory_checkbox.isChecked(),
            enabled_tiers=self.app.get_enabled_tiers(),
            crafting_6x6_unlocked=self.app.is_crafting_6x6_unlocked(),
        )
        self._planner_worker.moveToThread(self._planner_thread)
        self._planner_thread.started.connect(self._planner_worker.run)
        self._planner_worker.finished.connect(
            self._on_plan_worker_finished,
            QtCore.Qt.ConnectionType.QueuedConnection,
        )
        self._planner_worker.finished.connect(self._planner_thread.quit)
        self._planner_thread.finished.connect(self._planner_thread.deleteLater)
        self._planner_thread.finished.connect(self._cleanup_plan_worker)
        self._planner_thread.start()

    def _cleanup_plan_worker(self) -> None:
        if self._planner_worker is not None:
            self._planner_worker.deleteLater()
        self._planner_worker = None
        self._planner_thread = None
        self._planner_mode = None

    def _set_planning_state(self, active: bool, *, mode: str) -> None:
        for btn in (self.btn_plan, self.btn_build, self.btn_clear, self.btn_save_plan, self.btn_load_plan):
            btn.setEnabled(not active)
        if active:
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
            label = "Building plan..." if mode == "build" else "Planning..."
            self.app.status_bar.showMessage(label)
        else:
            QtWidgets.QApplication.restoreOverrideCursor()

    def _on_plan_worker_finished(self, result, error) -> None:
        mode = self._planner_mode or "plan"
        self._set_planning_state(False, mode=mode)
        if error is not None:
            QtWidgets.QMessageBox.critical(
                self,
                "Planner error",
                f"Planner failed unexpectedly.\n\nDetails: {error}",
            )
            self.app.status_bar.showMessage("Planner failed")
            return
        if result is None:
            self.app.status_bar.showMessage("Planner failed")
            return

        if mode == "plan":
            self._apply_plan_result(result, set_status=True)
            self.clear_build_steps(persist=False)
        elif mode == "build":
            self._apply_build_result(result)
        else:
            self.app.status_bar.showMessage("Planner complete")

    def _apply_build_result(self, result) -> None:
        if result.errors:
            self._handle_plan_errors(result.errors)
            self.clear_build_steps(persist=False)
            return

        self.build_base_inventory = self.planner.load_inventory() if self.use_inventory_checkbox.isChecked() else {}
        self.build_completed_steps = set()
        self.build_step_byproducts = {}

        self.build_steps = result.steps
        self._build_step_dependencies()
        self._render_build_steps()
        self._recalculate_build_steps()
        self.app.status_bar.showMessage("Build steps ready")

    def _build_step_dependencies(self) -> None:
        producers: dict[int, list[int]] = {}
        for idx, step in enumerate(self.build_steps):
            producers.setdefault(step.output_item_id, []).append(idx)

        self.build_step_dependencies = []
        for step in self.build_steps:
            deps: set[int] = set()
            for item_id, _name, _qty, _unit in step.inputs:
                deps.update(producers.get(item_id, []))
            self.build_step_dependencies.append(deps)

    def _clear_layout(self, layout: QtWidgets.QLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _render_build_steps(self) -> None:
        self._clear_layout(self.build_steps_layout)
        self.build_step_checks = []
        self.build_step_labels = []

        if not self.build_steps:
            self._set_build_placeholder("No build steps generated.")
            return

        for idx, step in enumerate(self.build_steps, start=1):
            row = QtWidgets.QWidget()
            row_layout = QtWidgets.QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            chk = QtWidgets.QCheckBox()
            chk.stateChanged.connect(lambda _state, i=idx - 1: self._on_build_step_toggle(i))
            label = QtWidgets.QLabel(self._format_build_step(idx, step))
            label.setWordWrap(True)
            row_layout.addWidget(chk)
            row_layout.addWidget(label, stretch=1)
            self.build_steps_layout.addWidget(row)
            self.build_step_checks.append(chk)
            self.build_step_labels.append(label)

        self.build_steps_layout.addStretch(1)

    def _format_build_step(self, idx: int, step) -> str:
        total_output = step.output_qty * step.multiplier
        input_lines = [f"{name} × {qty} {unit}" for _item_id, name, qty, unit in step.inputs]
        inputs_text = ", ".join(input_lines) if input_lines else "(none)"
        method = (step.method or "machine").strip().lower()
        if method == "emptying":
            machine_line = "Emptying container"
        elif method == "crafting":
            station = step.station_item_name or "(none)"
            grid = step.grid_size or ""
            grid_label = f" ({grid})" if grid else ""
            machine_line = f"Crafting{grid_label} at {station}"
        else:
            machine_name = step.machine_item_name or step.machine or "(unknown)"
            machine_line = f"Machine: {machine_name}"
        circuit_text = "(none)" if step.circuit in (None, "") else step.circuit
        return (
            f"{idx}. Inputs: {inputs_text}\n"
            f"   {machine_line}\n"
            f"   Circuit: {circuit_text}\n"
            f"   Output: {step.output_item_name} × {total_output} {step.output_unit}"
        )

    def _set_build_placeholder(self, text: str) -> None:
        self._clear_layout(self.build_steps_layout)
        label = QtWidgets.QLabel(text)
        label.setWordWrap(True)
        self.build_steps_layout.addWidget(label)
        self.build_steps_layout.addStretch(1)
        self.build_step_checks = []
        self.build_step_labels = []

    def _on_build_step_toggle(self, idx: int) -> None:
        if idx < 0 or idx >= len(self.build_steps):
            return
        checkbox = self.build_step_checks[idx]
        if checkbox.isChecked():
            if self.use_inventory_checkbox.isChecked() and not self._apply_step_inventory(idx):
                checkbox.blockSignals(True)
                checkbox.setChecked(False)
                checkbox.blockSignals(False)
                return
            self.build_completed_steps.add(idx)
            self._mark_dependency_chain(idx)
        else:
            if self.use_inventory_checkbox.isChecked() and idx in self.build_completed_steps:
                if not self._apply_step_inventory(idx, reverse=True):
                    checkbox.blockSignals(True)
                    checkbox.setChecked(True)
                    checkbox.blockSignals(False)
                    return
            self.build_completed_steps.discard(idx)
        self._recalculate_build_steps()

    def _mark_dependency_chain(self, idx: int) -> None:
        stack = list(self.build_step_dependencies[idx])
        while stack:
            dep = stack.pop()
            if dep in self.build_completed_steps:
                continue
            self.build_completed_steps.add(dep)
            stack.extend(self.build_step_dependencies[dep])

    def _effective_build_inventory(self) -> dict[int, int]:
        inventory = dict(self.build_base_inventory)
        for idx in self.build_completed_steps:
            if idx < 0 or idx >= len(self.build_steps):
                continue
            step = self.build_steps[idx]
            qty = step.output_qty * step.multiplier
            inventory[step.output_item_id] = inventory.get(step.output_item_id, 0) + qty
        return inventory

    def _recalculate_build_steps(self) -> None:
        inventory = self._effective_build_inventory()
        for idx, step in enumerate(self.build_steps):
            needed = step.output_qty * step.multiplier
            auto_done = inventory.get(step.output_item_id, 0) >= needed
            is_done = auto_done or idx in self.build_completed_steps
            checkbox = self.build_step_checks[idx]
            checkbox.blockSignals(True)
            checkbox.setChecked(is_done)
            checkbox.blockSignals(False)
            label = self.build_step_labels[idx]
            label.setStyleSheet("color: #777;" if is_done else "")

    def _refresh_build_inventory(self) -> None:
        if not self.build_steps:
            return
        if self.use_inventory_checkbox.isChecked():
            self.build_base_inventory = self.planner.load_inventory()
        else:
            self.build_base_inventory = {}
        self._recalculate_build_steps()

    def _refresh_build_steps_on_inventory_change(self, qty: int) -> None:
        if not self.build_steps or not self.use_inventory_checkbox.isChecked():
            return
        if not self._has_recipes():
            return

        previous_steps = list(self.build_steps)
        previous_completed = set(self.build_completed_steps)
        previous_byproducts = dict(self.build_step_byproducts)

        result = self.planner.plan(
            self.target_item_id,
            qty,
            use_inventory=self.use_inventory_checkbox.isChecked(),
            enabled_tiers=self.app.get_enabled_tiers(),
            crafting_6x6_unlocked=self.app.is_crafting_6x6_unlocked(),
        )
        if result.errors:
            self.app.status_bar.showMessage("Build steps not updated: missing recipe")
            return
        self.build_base_inventory = self.planner.load_inventory()
        self.build_steps = result.steps
        if self._step_signatures_match(previous_steps, self.build_steps):
            self.build_completed_steps = {
                idx for idx in previous_completed if 0 <= idx < len(self.build_steps)
            }
            self.build_step_byproducts = {
                idx: byproducts
                for idx, byproducts in previous_byproducts.items()
                if 0 <= idx < len(self.build_steps)
            }
        else:
            self.build_completed_steps = set()
            self.build_step_byproducts = {}
        self._build_step_dependencies()
        self._render_build_steps()
        self._recalculate_build_steps()

    def _step_signatures_match(self, before: list, after: list) -> bool:
        if len(before) != len(after):
            return False
        return [self._build_step_signature(step) for step in before] == [
            self._build_step_signature(step) for step in after
        ]

    def _build_step_signature(self, step) -> tuple:
        inputs = tuple(sorted(item_id for item_id, _name, _qty, _unit in step.inputs))
        return (
            step.recipe_id,
            step.output_item_id,
            step.output_qty,
            inputs,
        )

    def _apply_step_inventory(self, idx: int, *, reverse: bool = False) -> bool:
        step = self.build_steps[idx]
        if reverse:
            inventory = self.planner.load_inventory()
            output_qty = step.output_qty * step.multiplier
            missing_outputs = []
            available_output = inventory.get(step.output_item_id, 0)
            if available_output < output_qty:
                missing_outputs.append((step.output_item_name, output_qty, step.output_unit, available_output))
            applied_byproducts = self.build_step_byproducts.get(idx, [])
            missing_byproducts = []
            for item_id, qty in applied_byproducts:
                available = inventory.get(item_id, 0)
                if available < qty:
                    item = next((item for item in self.app.items if item["id"] == item_id), None)
                    name = item["name"] if item else f"Item {item_id}"
                    unit = self._unit_for_kind(item["kind"] if item else None)
                    missing_byproducts.append((name, qty, unit, available))
            if missing_outputs or missing_byproducts:
                missing_lines = [
                    f"{name}: need {qty} {unit}, have {available}"
                    for name, qty, unit, available in missing_outputs + missing_byproducts
                ]
                message = "You don't have enough inventory to undo this step:\n\n" + "\n".join(
                    missing_lines
                )
                QtWidgets.QMessageBox.information(
                    self,
                    "Build step blocked",
                    message,
                )
                return False
        else:
            inventory = self._effective_build_inventory()
            missing = []
            for item_id, name, qty, unit in step.inputs:
                available = inventory.get(item_id, 0)
                if available < qty:
                    missing.append((item_id, name, qty, unit, available))

            if missing:
                missing_lines = [
                    f"{name}: need {qty} {unit}, have {available}"
                    for _item_id, name, qty, unit, available in missing
                ]
                message = "You don't have enough inventory to complete this step:\n\n" + "\n".join(
                    missing_lines
                )
                ok = QtWidgets.QMessageBox.question(
                    self,
                    "Missing inventory",
                    f"{message}\n\nAdd missing items to inventory?",
                )
                if ok != QtWidgets.QMessageBox.StandardButton.Yes:
                    QtWidgets.QMessageBox.information(
                        self,
                        "Build step blocked",
                        "Step not checked off due to missing inventory.",
                    )
                    return False

                for item_id, name, qty, unit, available in missing:
                    add_qty, ok = QtWidgets.QInputDialog.getInt(
                        self,
                        "Add inventory",
                        f"Add how many {name} ({unit})?\nMissing {qty - available} {unit}.",
                        max(qty - available, 0),
                        0,
                        1_000_000_000,
                    )
                    if ok and add_qty:
                        self._adjust_inventory_qty(item_id, add_qty)

                self.build_base_inventory = self.planner.load_inventory()
                inventory = self._effective_build_inventory()
                still_missing = [
                    (item_id, name, qty, unit, inventory.get(item_id, 0))
                    for item_id, name, qty, unit, _available in missing
                    if inventory.get(item_id, 0) < qty
                ]
                if still_missing:
                    QtWidgets.QMessageBox.information(
                        self,
                        "Build step blocked",
                        "Step not checked off due to missing inventory.",
                    )
                    return False

        direction = -1 if reverse else 1
        byproduct_ok, byproducts = self._collect_step_byproducts(idx, direction)
        if not byproduct_ok:
            return False

        adjustments = [
            (item_id, -qty * direction) for item_id, _name, qty, _unit in step.inputs
        ]
        output_qty = step.output_qty * step.multiplier
        adjustments.append((step.output_item_id, output_qty * direction))
        adjustments.extend(byproducts)

        try:
            self.app.profile_conn.execute("BEGIN")
            for item_id, delta in adjustments:
                self._adjust_inventory_qty(item_id, delta, commit=False)
            self.app.profile_conn.commit()
        except Exception as exc:
            self.app.profile_conn.rollback()
            QtWidgets.QMessageBox.critical(
                self,
                "Inventory update failed",
                f"Could not update inventory for this step.\n\nDetails: {exc}",
            )
            return False
        if direction < 0:
            self.build_step_byproducts.pop(idx, None)
        elif byproducts:
            self.build_step_byproducts[idx] = [(item_id, qty) for item_id, qty in byproducts]

        self.build_base_inventory = self.planner.load_inventory()
        return True

    def _collect_step_byproducts(self, idx: int, direction: int) -> tuple[bool, list[tuple[int, int]]]:
        if direction < 0:
            applied = self.build_step_byproducts.get(idx, [])
            return True, [(item_id, -qty) for item_id, qty in applied]

        step = self.build_steps[idx]
        applied: list[tuple[int, int]] = []
        for item_id, name, qty, unit, chance in step.byproducts:
            if chance >= 100:
                applied.append((item_id, qty))
                continue
            ok = QtWidgets.QMessageBox.question(
                self,
                "Byproduct check",
                f"Did this step produce any {name} ({unit})?",
            )
            if ok != QtWidgets.QMessageBox.StandardButton.Yes:
                continue
            add_qty, ok = QtWidgets.QInputDialog.getInt(
                self,
                "Add byproduct",
                f"How many {name} ({unit}) were produced?",
                0,
                0,
                1_000_000_000,
            )
            if not ok:
                return False, []
            if add_qty:
                applied.append((item_id, add_qty))
        return True, applied

    def _adjust_inventory_qty(self, item_id: int, delta: int, *, commit: bool = True) -> None:
        item = next((item for item in self.app.items if item["id"] == item_id), None)
        if not item:
            return
        column = "qty_liters" if (item["kind"] or "").strip().lower() == "fluid" else "qty_count"
        row = self.app.profile_conn.execute(
            f"SELECT {column} FROM inventory WHERE item_id=?",
            (item_id,),
        ).fetchone()
        current = 0
        if row and row[column] is not None:
            try:
                current = int(float(row[column]))
            except (TypeError, ValueError):
                current = 0
        new_qty = max(current + delta, 0)
        if new_qty <= 0:
            self.app.profile_conn.execute("DELETE FROM inventory WHERE item_id=?", (item_id,))
        else:
            count_val = new_qty if column == "qty_count" else None
            liter_val = new_qty if column == "qty_liters" else None
            self.app.profile_conn.execute(
                "INSERT INTO inventory(item_id, qty_count, qty_liters) VALUES(?, ?, ?) "
                "ON CONFLICT(item_id) DO UPDATE SET qty_count=excluded.qty_count, qty_liters=excluded.qty_liters",
                (item_id, count_val, liter_val),
            )
        if commit:
            self.app.profile_conn.commit()

    def reset_build_steps(self) -> None:
        if not self.build_steps:
            return
        self.build_completed_steps = set()
        self.build_step_byproducts = {}
        self._recalculate_build_steps()

    def clear_build_steps(self, *, persist: bool = True) -> None:
        self.build_steps = []
        self.build_completed_steps = set()
        self.build_step_dependencies = []
        self.build_base_inventory = {}
        self.build_step_byproducts = {}
        self._set_build_placeholder("Run a plan, then click Build to get step-by-step instructions.")
        if persist:
            self._persist_state()

    def _handle_plan_errors(self, errors: list[str]) -> None:
        message = "\n".join(errors)
        if self.app.editor_enabled:
            ok = QtWidgets.QMessageBox.question(
                self,
                "Planner warning",
                f"{message}\n\nWould you like to add a recipe now?",
            )
            if ok == QtWidgets.QMessageBox.StandardButton.Yes:
                dlg = AddRecipeDialog(self.app, parent=self)
                dlg.exec()
        else:
            QtWidgets.QMessageBox.information(
                self,
                "Planner warning",
                f"{message}\n\nNotify the developer or switch to edit mode and add a recipe.",
            )
        self.app.status_bar.showMessage("Planner failed: missing recipe")

    def _filter_plan_errors(self, result) -> list[str]:
        if not self.use_inventory_checkbox.isChecked():
            return result.errors
        inventory = self.planner.load_inventory()
        missing_map = {item_id: (name, qty) for item_id, name, qty in result.missing_recipes}
        filtered = [err for err in result.errors if not err.startswith("No recipe found for ")]
        for item_id, (name, qty_needed) in missing_map.items():
            if inventory.get(item_id, 0) < qty_needed:
                filtered.append(f"No recipe found for {name}.")
        return filtered

    def _toggle_steps(self) -> None:
        self._toggle_steps_visibility()

    def _toggle_steps_visibility(self, *, persist: bool = True) -> None:
        self.steps_group.setVisible(self.show_steps_checkbox.isChecked())
        if persist:
            self._persist_state()

    def clear_results(self) -> None:
        self._set_text(self.shopping_text, "")
        self._set_text(self.steps_text, "")
        self.last_plan_run = False
        self.last_plan_used_inventory = False
        self.clear_build_steps(persist=False)
        self.app.status_bar.showMessage("Planner cleared")
        self._persist_state()

    def _set_text(self, widget: QtWidgets.QTextEdit, text: str) -> None:
        widget.setPlainText(text)

    def _copy_text(self, widget: QtWidgets.QTextEdit, empty_message: str) -> None:
        text = widget.toPlainText().strip()
        if not text:
            QtWidgets.QMessageBox.information(self, "Nothing to copy", empty_message)
            return
        QtWidgets.QApplication.clipboard().setText(text)
        self.app.status_bar.showMessage("Copied to clipboard")

    def _save_text(self, widget: QtWidgets.QTextEdit, default_name: str) -> None:
        text = widget.toPlainText().strip()
        if not text:
            QtWidgets.QMessageBox.information(self, "Nothing to save", "There is no content to save yet.")
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Save Planner Output",
            default_name,
            "Text Files (*.txt);;All Files (*)",
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(text)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Save failed", f"Could not save file.\n\nDetails: {exc}")
            return
        self.app.status_bar.showMessage(f"Saved planner output to {path}")

    def save_plan(self) -> None:
        state = self._current_state()
        if not state.get("shopping_text") and not state.get("steps_text"):
            QtWidgets.QMessageBox.information(self, "Nothing to save", "Run a plan or load content before saving.")
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Save Plan",
            "planner_plan.json",
            "Planner Plan (*.json);;All Files (*)",
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(state, handle, indent=2)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Save failed", f"Could not save plan.\n\nDetails: {exc}")
            return
        self.app.status_bar.showMessage(f"Saved planner plan to {path}")

    def load_plan(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Load Plan",
            "",
            "Planner Plan (*.json);;All Files (*)",
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Load failed", f"Could not read plan.\n\nDetails: {exc}")
            return
        if not isinstance(data, dict):
            QtWidgets.QMessageBox.critical(self, "Load failed", "Plan file is not valid.")
            return
        self._apply_loaded_state(data)
        self._persist_state()
        self.app.status_bar.showMessage(f"Loaded planner plan from {path}")

    def _persist_state(self) -> None:
        self.app.planner_state = self._current_state()

    def _current_state(self) -> dict[str, object]:
        return {
            "version": 1,
            "target_item_id": self.target_item_id,
            "target_item_kind": self.target_item_kind,
            "target_item_name": self.target_item_name.text(),
            "target_qty": self.target_qty_entry.text(),
            "target_unit": self.target_qty_unit.text(),
            "use_inventory": self.use_inventory_checkbox.isChecked(),
            "shopping_text": self.shopping_text.toPlainText().rstrip(),
            "steps_text": self.steps_text.toPlainText().rstrip(),
            "show_steps": self.show_steps_checkbox.isChecked(),
            "last_plan_run": self.last_plan_run,
            "last_plan_used_inventory": self.last_plan_used_inventory,
        }

    def _restore_state(self) -> None:
        state = getattr(self.app, "planner_state", {}) or {}
        if not state:
            return
        self._apply_loaded_state(state)

    def _apply_loaded_state(self, state: dict[str, object]) -> None:
        item_id = state.get("target_item_id")
        item_name = state.get("target_item_name") or "(none)"
        item_kind = state.get("target_item_kind")
        matched = None
        if item_id is not None:
            matched = next((item for item in self.app.items if item["id"] == item_id), None)
        if matched is None and item_name:
            matched = next((item for item in self.app.items if item["name"] == item_name), None)
        if matched:
            self.target_item_id = matched["id"]
            self.target_item_kind = matched["kind"]
            self.target_item_name.setText(matched["name"])
            self.target_qty_unit.setText(self._unit_for_kind(matched["kind"]))
        else:
            self.target_item_id = item_id if isinstance(item_id, int) else None
            self.target_item_kind = item_kind if isinstance(item_kind, str) else None
            self.target_item_name.setText(item_name)
            self.target_qty_unit.setText(state.get("target_unit") or "")

        self.target_qty_entry.setText(state.get("target_qty") or "1")
        self.use_inventory_checkbox.setChecked(bool(state.get("use_inventory", True)))
        self.show_steps_checkbox.setChecked(bool(state.get("show_steps", False)))
        self._toggle_steps_visibility(persist=False)
        self._set_text(self.shopping_text, state.get("shopping_text", ""))
        self._set_text(self.steps_text, state.get("steps_text", ""))
        self.last_plan_run = bool(state.get("last_plan_run", bool(state.get("shopping_text") or state.get("steps_text"))))
        self.last_plan_used_inventory = bool(state.get("last_plan_used_inventory", self.use_inventory_checkbox.isChecked()))

    def reset_state(self) -> None:
        self.target_item_id = None
        self.target_item_kind = None
        self.target_item_name.setText("(none)")
        self.target_qty_entry.setText("1")
        self.target_qty_unit.setText("")
        self.use_inventory_checkbox.setChecked(True)
        self.show_steps_checkbox.setChecked(False)
        self.last_plan_run = False
        self.last_plan_used_inventory = False
        self._toggle_steps_visibility(persist=False)
        self._set_text(self.shopping_text, "Run a plan to see required items.")
        self._set_text(self.steps_text, "Run a plan to see steps.")
        self.clear_build_steps(persist=False)

    def _has_recipes(self) -> bool:
        try:
            row = self.app.conn.execute("SELECT COUNT(1) AS c FROM recipes").fetchone()
        except Exception:
            return False
        return bool(row and int(row["c"] or 0) > 0)

    def _unit_for_kind(self, kind: str | None) -> str:
        return "L" if (kind or "").strip().lower() == "fluid" else "count"
