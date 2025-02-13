from __future__ import annotations

import abc
import re
import typing as typ

import PyQt5.QtCore as QtC
import PyQt5.QtGui as QtG
import PyQt5.QtWidgets as QtW

from app import data_access as da, model, queries, utils
from app.i18n import translate as _t
from .. import components

_Type = typ.TypeVar('_Type')


class Tab(abc.ABC, typ.Generic[_Type]):
    """This class represents a tab containing a single table.
    This is a generic class. _Type is the type of the values displayed in each row.
    """
    _OK = 0
    _DUPLICATE = 1
    _EMPTY = 2
    _FORMAT = 4

    def __init__(self, owner: QtW.QWidget, dao: da.TagsDao, title: str, addable: bool, deletable: bool, editable: bool,
                 columns_to_check: typ.List[typ.Tuple[int, bool]], search_columns: typ.List[int],
                 selection_changed: typ.Optional[typ.Callable[[None], None]] = None,
                 cell_changed: typ.Optional[typ.Callable[[int, int, str], None]] = None,
                 rows_deleted: typ.Optional[typ.Callable[[typ.List[_Type]], None]] = None):
        """Initializes this tab.

        :param owner: Tab’s owner.
        :param dao: The tag’s DAO.
        :param addable: If true rows can be added to this tab.
        :param deletable: If true rows can be deleted from this tab.
        :param editable: If true the contained table will be editable.
        :param columns_to_check: List of column indices that need content checking.
        :param search_columns: List of column indices in which searching is allowed.
        :param selection_changed: Action called when the selection changes.
        :param cell_changed: Action called when a cell has been edited. It takes the cell’s row, column and text.
        :param rows_deleted: Action called when rows have been deleted. It takes the list of deleted values.
        """
        self._initialized = False
        self._owner = owner
        self._tags_dao = dao
        self._title = title
        self._addable = addable
        self._deletable = deletable
        self._editable = editable
        self._columns_to_check: typ.Dict[int, bool] = {c: b for c, b in columns_to_check}
        self._search_columns = search_columns
        self._selection_changed = selection_changed
        self._cell_changed = cell_changed
        self._rows_deleted = rows_deleted

        # noinspection PyTypeChecker
        self._table: QtW.QTableWidget = None

        self._values = []
        self._changed_rows = set()
        self._added_rows = set()
        self._deleted_rows = set()

        self._dummy_type_id = -1

        self._valid = True

        # Use system colors
        self._DISABLED_COLOR = QtW.QApplication.palette().color(QtG.QPalette.Disabled, QtG.QPalette.Base)

    @abc.abstractmethod
    def init(self):
        """Initializes the inner table."""
        if self._table:
            self._initialized = False
            self._table.destroy()

        self._table = components.TranslatedTableWidget(parent=self._owner)
        self._table.setSelectionBehavior(QtW.QAbstractItemView.SelectRows)
        self._table.verticalHeader().setDefaultSectionSize(20)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setSortingEnabled(True)
        self._table.cellChanged.connect(self._cell_edited)
        if self._selection_changed is not None:
            self._table.itemSelectionChanged.connect(self._selection_changed)
        if not self._editable:
            self._table.setSelectionMode(QtW.QAbstractItemView.SingleSelection)
        else:
            delete_action = QtW.QAction(parent=self._owner)
            delete_action.setShortcut('Delete')
            delete_action.triggered.connect(self.delete_selected_rows)
            self._table.addAction(delete_action)

    @property
    def table(self) -> QtW.QTableWidget:
        """Returns the inner table."""
        return self._table

    @property
    def title(self) -> str:
        return self._title

    @property
    def addable(self) -> bool:
        return self._addable

    @property
    def deletable(self) -> bool:
        return self._deletable

    @property
    def selected_rows_number(self) -> int:
        """Returns the number of selected rows."""
        return len(self._table.selectionModel().selectedRows())

    @property
    def modified_rows_number(self) -> int:
        """Returns the number of changed/deleted/added rows."""
        return len(self._changed_rows) + len(self._added_rows) + len(self._deleted_rows)

    def add_row(self):
        """Adds an empty row in the table."""
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._initialized = False
        self._set_row(None, row)
        self._added_rows.add(row)
        self._initialized = True
        self._dummy_type_id -= 1

    def delete_selected_rows(self):
        """Deletes all selected rows."""
        selected_rows = {i.row() for i in self._table.selectionModel().selectedRows()}
        if len(selected_rows) > 0:
            if utils.gui.show_question(_t('dialog.edit_tags.delete_warning.text'), parent=self._owner):
                self._deleted_rows |= selected_rows - self._added_rows
                self._changed_rows -= selected_rows
                self._added_rows -= selected_rows
                to_delete = []
                for row in selected_rows:
                    to_delete.append(self.get_value(row))
                    self._table.setRowHidden(row, True)
                if self._rows_deleted is not None:
                    self._rows_deleted(to_delete)

    def search(self, query: str) -> typ.Optional[bool]:
        """Searches for a string inside the table.
        Starts the search from the currently selected row, or from the first one if none is selected.

        :param query: The string pattern to search for.
        :return: True if a match was found; False if none; None if the query has a syntax error.
        """
        if selected_rows := self._table.selectionModel().selectedIndexes():
            start_row = selected_rows[0].row() + 1
        else:
            start_row = 0

        for item in self._table.selectedItems():
            item.setSelected(False)

        # Check for any invalid \
        if re.search(r'((?<!\\)\\(?:\\\\)*)([^*?\\]|$)', query):
            return None

        # Escape regex meta-characters except * and ?
        pattern = re.sub(r'([\[\]()+{.^$])', r'\\\1', query)
        # Replace non-escaped '*' and '?' by a regex
        pattern = re.sub(r'((?<!\\)(?:\\\\)*)([*?])', r'\1.\2', pattern)
        pattern = f'^{pattern}$'
        regex = re.compile(pattern, re.IGNORECASE)

        row_count = self._table.rowCount()
        found = False
        for col in self._search_columns:
            for row in range(start_row, row_count):
                item = self._table.item(row, col)
                if regex.fullmatch(item.text()):
                    self._table.setFocus()
                    self._table.scrollToItem(item)
                    item.setSelected(True)
                    found = True
                    break
            if found:
                break

        return found

    @abc.abstractmethod
    def apply(self) -> bool:
        """Applies all changes.

        :return: True if all changes were applied.
        """
        pass

    def check_integrity(self) -> bool:
        """Checks table’s integrity.

        :return: True if all cells have valid values.
        """
        ok = True
        for col, check_duplicates in self._columns_to_check.items():
            ok &= self._check_column(col, check_duplicates)[0] == self._OK
            if not ok:
                break
        return ok

    @abc.abstractmethod
    def get_value(self, row: int) -> typ.Optional[_Type]:
        """Returns the value for the given row.

        :param row: The row.
        :return: The instanciated value.
        """
        pass

    @abc.abstractmethod
    def _set_row(self, value: typ.Optional[_Type], row: int):
        """Sets the value at the given row.

        :param value: The value.
        :param row: The row to set.
        """
        pass

    @abc.abstractmethod
    def _cell_edited(self, row: int, col: int):
        """Called when a table cell is edited.

        :param row: Cell’s row.
        :param col: Cell’s column.
        """
        pass

    def _check_column(self, column: int, check_duplicates: bool) -> typ.Tuple[int, int, str]:
        """Checks column’s integrity.

        :param column: The column to check.
        :param check_duplicates: Whether to check for any duplicate cell values.
        :return: A tuple with 3 values: table integrity which is one of OK, DUPLICATE, EMPTY or FORMAT; row of the
                 invalid cell or -1 if whole column is valid; the error message.
                 OK if all cells have valid values;
                 DUPLICATE if some cells have identical values;
                 EMPTY if a cell is empty;
                 FORMAT if a cell is not formatted correctly.
        """
        for row in range(self._table.rowCount()):
            if self._table.isRowHidden(row):
                continue

            if self._table.item(row, column).text().strip() == '':
                return self._EMPTY, row, _t('dialog.edit_tags.error.empty_cell')

            ok, message = self._check_cell_format(row, column)
            if not ok:
                return self._FORMAT, row, message

            if check_duplicates:
                cell_value = self._table.item(row, column).text()
                for r in range(self._table.rowCount()):
                    if self._table.isRowHidden(r):
                        continue
                    if r != row and self._table.item(r, column).text() == cell_value:
                        return self._DUPLICATE, r, _t('dialog.edit_tags.error.duplicate_value', row=row)
        return self._OK, -1, ''

    @abc.abstractmethod
    def _check_cell_format(self, row: int, col: int) -> (bool, str):
        """Checks the format of the cell at the given position.

        :param row: Cell’s row.
        :param col: Cell’s column.
        :return: True if the cell content's format is correct.
        """
        pass


class TagTypesTab(Tab[model.TagType]):
    """This class represents a tab containing a table that displays all defined tag types."""

    def __init__(self, owner: QtW.QWidget, dao: da.TagsDao, editable: bool,
                 selection_changed: typ.Optional[typ.Callable[[None], None]] = None,
                 cell_changed: typ.Optional[typ.Callable[[int, int, str], None]] = None,
                 rows_deleted: typ.Optional[typ.Callable[[typ.List[_Type]], None]] = None):
        """Initializes this tab.

        :param owner: Tab’s owner.
        :param dao: The tag’s DAO.
        :param editable: If true the contained table will be editable.
        :param selection_changed: Action called when the selection changes.
        :param cell_changed: Action called when a cell has been edited. It takes the cell’s row, column and text.
        :param rows_deleted: Action called when rows have been deleted. It takes the list of deleted values.
        """
        super().__init__(
            owner,
            dao,
            _t('dialog.edit_tags.tab.tag_types.title'),
            addable=True,
            deletable=True,
            editable=editable,
            columns_to_check=[(1, True), (2, True)],
            search_columns=[1, 2],
            selection_changed=selection_changed,
            cell_changed=cell_changed,
            rows_deleted=rows_deleted
        )

    def init(self):
        super().init()

        self._dummy_type_id = -1

        self._table.setColumnCount(5)
        self._table.setColumnWidth(0, 30)
        self._table.setHorizontalHeaderLabels([
            _t('dialog.edit_tags.tab.tag_types.table.header.type_id'),
            _t('dialog.edit_tags.tab.tag_types.table.header.label'),
            _t('dialog.edit_tags.tab.tag_types.table.header.symbol'),
            _t('dialog.edit_tags.tab.tag_types.table.header.color'),
            _t('dialog.edit_tags.tab.tags_common.table.header.usage'),
        ])

        self._values = self._tags_dao.get_all_tag_types(get_count=True)
        self._table.setRowCount(len(self._values))

        if self._values is not None:
            for i, (tag_type, count) in enumerate(self._values):
                tag_type.count = count
                self._set_row(tag_type, i)
        else:
            utils.gui.show_error(_t('popup.tag_types_load_error.text'), parent=self._owner)
            self._values = []

        self._initialized = True

    def apply(self) -> bool:
        ok = True

        to_keep = []
        for row in self._added_rows:
            res = self._tags_dao.add_type(self.get_value(row))
            if not res:
                to_keep.append(row)
            ok &= res
        self._added_rows = set(to_keep)

        to_keep = []
        for row in self._deleted_rows:
            res = self._tags_dao.delete_type(self.get_value(row).id)
            if not res:
                to_keep.append(row)
            ok &= res
        self._deleted_rows = set(to_keep)

        to_keep = []
        for row in self._changed_rows:
            res = self._tags_dao.update_type(self.get_value(row))
            if not res:
                to_keep.append(row)
            ok &= res
        self._changed_rows = set(to_keep)

        return ok

    def get_value(self, row: int) -> typ.Optional[model.TagType]:
        args = {}

        for i in range(self._table.columnCount()):
            cell = self._table.item(row, i)
            if cell is None:
                cell = self._table.cellWidget(row, i)
            arg = cell.whatsThis()
            if arg == '':
                continue
            if arg == 'color':
                args[arg] = cell.palette().button().color()
            else:
                args[arg] = cell.text() if arg != 'ident' else int(cell.text())

        try:
            return model.TagType(**args)
        except ValueError:
            return None

    def _cell_edited(self, row: int, col: int):
        if self._initialized and self._editable:
            if col != 3:
                status, invalid_row, message = self._check_column(col, self._columns_to_check.get(col, True))
                if status != self._OK:
                    utils.gui.show_error(message, parent=self._owner)

            if row not in self._added_rows:
                if self.get_value(row) != self._values[row]:
                    self._changed_rows.add(row)
                elif row in self._changed_rows:
                    self._changed_rows.remove(row)

            if self._cell_changed is not None:
                cell = self._table.item(row, col)
                if cell is None:
                    cell = self._table.cellWidget(row, col)
                self._cell_changed(row, col, cell.text())

    def _check_cell_format(self, row: int, col: int) -> (bool, str):
        text = self._table.item(row, col).text()
        if col == 1:
            return model.TagType.LABEL_PATTERN.match(text) is not None, \
                   _t('dialog.edit_tags.error.invalid_tag_name')
        if col == 2:
            return (model.TagType.SYMBOL_PATTERN.match(text) is not None,
                    _t('dialog.edit_tags.error.invalid_tag_type_symbol'))
        return True, ''

    def _set_row(self, tag_type: typ.Optional[model.TagType], row: int):
        defined = tag_type is not None
        id_item = _IntTableWidgetItem(str(tag_type.id) if defined else str(self._dummy_type_id))
        id_item.setWhatsThis('ident')
        # noinspection PyTypeChecker
        id_item.setFlags(id_item.flags() & ~QtC.Qt.ItemIsEditable & ~QtC.Qt.ItemIsSelectable)
        if self._editable:
            id_item.setBackground(self._DISABLED_COLOR)
        self._table.setItem(row, 0, id_item)

        label_item = QtW.QTableWidgetItem(tag_type.label if defined
                                          else _t('dialog.edit_tags.tab.tag_types.table.default_label'))
        label_item.setWhatsThis('label')
        if not self._editable:
            # noinspection PyTypeChecker
            label_item.setFlags(label_item.flags() & ~QtC.Qt.ItemIsEditable & ~QtC.Qt.ItemIsSelectable)
        self._table.setItem(row, 1, label_item)

        symbol_item = QtW.QTableWidgetItem(tag_type.symbol if defined else '§')
        symbol_item.setWhatsThis('symbol')
        if not self._editable:
            # noinspection PyTypeChecker
            symbol_item.setFlags(symbol_item.flags() & ~QtC.Qt.ItemIsEditable & ~QtC.Qt.ItemIsSelectable)
        self._table.setItem(row, 2, symbol_item)

        default_color = QtG.QColor(0, 0, 0)
        bg_color = tag_type.color if defined else default_color
        color_btn = QtW.QPushButton(tag_type.color.name() if defined else default_color.name(), parent=self._owner)
        color_btn.setWhatsThis('color')
        self._set_button_bg_color(color_btn, bg_color)
        color_btn.setFocusPolicy(QtC.Qt.NoFocus)
        color_btn.clicked.connect(self._show_color_picker)
        color_btn.setProperty('row', row)
        if not self._editable:
            color_btn.setEnabled(False)
        self._table.setCellWidget(row, 3, color_btn)

        # count property is added to tag argument before calling this method.
        # noinspection PyUnresolvedReferences
        number_item = _IntTableWidgetItem(str(tag_type.count if defined else 0))
        # noinspection PyTypeChecker
        number_item.setFlags(number_item.flags() & ~QtC.Qt.ItemIsEditable & ~QtC.Qt.ItemIsSelectable)
        if self._editable:
            number_item.setBackground(self._DISABLED_COLOR)
        self._table.setItem(row, 4, number_item)

    def _show_color_picker(self):
        """Shows a color picker then sets the event button to the selected color."""
        # noinspection PyTypeChecker
        button: QtW.QPushButton = self._owner.sender()
        # Set initial color to the button’s current background color
        color = QtW.QColorDialog.getColor(button.palette().button().color(), parent=self._owner)
        if color.isValid():
            row = button.property('row')
            button.setText(color.name())
            self._set_button_bg_color(button, color)
            self._cell_edited(row, 3)

    @staticmethod
    def _set_button_bg_color(button: QtW.QPushButton, color: QtG.QColor):
        button.setStyleSheet(
            f'background-color: {color.name()}; color: {utils.gui.font_color(color).name()}; border: none')


_TagType = typ.TypeVar('_TagType', model.Tag, model.CompoundTag)


class _TagsTab(Tab[_TagType], typ.Generic[_TagType], metaclass=abc.ABCMeta):
    """This class represents a tab containing a table that displays all defined tags."""
    COMBO_ITEM_PATTERN = re.compile(r'^(\d+) - (.+)$')

    def __init__(self, owner: QtW.QWidget, dao: da.TagsDao, title: str, addable: bool, editable: bool,
                 tag_class: typ.Type[_TagType], additional_columns: typ.List[typ.Tuple[str, bool]],
                 additional_search_columns: typ.List[int],
                 selection_changed: typ.Optional[typ.Callable[[None], None]] = None,
                 cell_changed: typ.Optional[typ.Callable[[int, int, str], None]] = None,
                 rows_deleted: typ.Optional[typ.Callable[[typ.List[_TagType]], None]] = None):
        """Initializes this tab.

        :param owner: Tab’s owner.
        :param dao: The tag’s DAO.
        :param title: Tab's title.
        :param addable: If true rows can be added to this tab.
        :param editable: If true the contained table will be editable.
        :param tag_class: Type of tags, either NORMAL or COMPOUND.
        :param additional_columns: Titles of additional columns. They will be inserted between label and type columns.
        :param additional_search_columns: List of column indices in which searching is allowed.
        :param selection_changed: Action called when the selection changes.
        :param cell_changed: Action called when a cell has been edited. It takes the cell’s row, column and text.
        :param rows_deleted: Action called when rows have been deleted. It takes the list of deleted values.
        """
        cols_to_check = [
            (1, True),
            *[(c, additional_columns[c - 2][1]) for c in range(2, 2 + len(additional_columns))]
        ]
        search_cols = [1, *map(lambda i: i + 2, additional_search_columns)]
        super().__init__(owner, dao, title, addable, True, editable, cols_to_check, search_cols,
                         selection_changed=selection_changed, cell_changed=cell_changed, rows_deleted=rows_deleted)
        self._tag_class = tag_class
        self._columns = [
            _t('dialog.edit_tags.tab.tags_common.table.header.tag_id'),
            _t('dialog.edit_tags.tab.tags_common.table.header.label'),
            *[c[0] for c in additional_columns],
            _t('dialog.edit_tags.tab.tags_common.table.header.type'),
            _t('dialog.edit_tags.tab.tags_common.table.header.usage'),
        ]
        self._type_column = 2 + len(additional_columns)
        self._tag_use_count_column = 1 + self._type_column

    def init(self):
        super().init()

        self._table.setColumnCount(len(self._columns))
        self._table.setColumnWidth(0, 30)
        self._table.setHorizontalHeaderLabels(self._columns)

        self._values = self._tags_dao.get_all_tags(self._tag_class, sort_by_label=True,
                                                   get_count=self._tag_class == model.Tag)
        self._table.setRowCount(len(self._values) if self._values is not None else 0)

        if self._values is not None:
            if self._tag_class == model.CompoundTag:  # Add dummy count
                self._values = [(v, 0) for v in self._values]
            for i, (tag, count) in enumerate(self._values):
                tag.count = count
                # noinspection PyTypeChecker
                self._set_row(tag, i)
        else:
            utils.gui.show_error(_t('popup.tags_load_error.text'), parent=self._owner)
            self._values = []

        self._initialized = True

    def apply(self) -> bool:
        ok = True

        to_keep = []
        for row in self._added_rows:
            res = self._tags_dao.add_compound_tag(self.get_value(row))
            if not res:
                to_keep.append(row)
            ok &= res
        self._added_rows = set(to_keep)

        to_keep = []
        for row in self._deleted_rows:
            res = self._tags_dao.delete_tag(self.get_value(row).id)
            if not res:
                to_keep.append(row)
            ok &= res
        self._deleted_rows = set(to_keep)

        to_keep = []
        for row in self._changed_rows:
            res = self._tags_dao.update_tag(self.get_value(row))
            if not res:
                to_keep.append(row)
            ok &= res
        self._changed_rows = set(to_keep)

        return ok

    def get_value(self, row: int) -> typ.Optional[_TagType]:
        args = {}

        for i in range(self._table.columnCount()):
            cell = self._table.item(row, i)
            if cell is None:
                cell = self._table.cellWidget(row, i)
            if cell is None:
                continue
            arg = cell.whatsThis()
            if arg == '':
                continue
            if arg == 'tag_type':
                if cell.currentIndex() != 0:
                    ident = self._id_from_combo(cell.currentText())
                    if ident is not None:
                        args[arg] = self._tags_dao.get_tag_type_from_id(ident)
            else:
                args[arg] = cell.text() if arg != 'ident' else int(cell.text())

        try:
            return self._tag_class(**args)
        except ValueError:
            return None

    def update_type_label(self, tag_type: model.TagType):
        """Updates the name of the given type in all comboboxes.

        :param tag_type: The type to update.
        """
        for tag_row in range(self._table.rowCount()):
            if not self._table.isRowHidden(tag_row):
                combo = self._table.cellWidget(tag_row, self._type_column)
                for i in range(combo.count()):
                    if combo.itemText(i).startswith(f'{tag_type.id} '):
                        combo.setItemText(i, self._get_combo_text(tag_type.id, tag_type.label))
                        break

    def delete_types(self, deleted_types: typ.List[model.TagType]):
        """Removes from all comboboxes the tag types that have been deleted.

        :param deleted_types: All deleted tag types.
        """
        for tag_type in deleted_types:
            ident, label = tag_type.id, tag_type.label
            for tag_row in range(self._table.rowCount()):
                combo = self._table.cellWidget(tag_row, self._type_column)
                current_type = self._label_from_combo(combo.currentText())
                combo.removeItem(combo.findText(self._get_combo_text(ident, label)))
                if current_type == label:
                    combo.setCurrentIndex(0)

    def _set_row(self, tag: typ.Optional[_TagType], row: int):
        defined = tag is not None
        id_item = _IntTableWidgetItem(str(tag.id if defined else self._dummy_type_id))
        id_item.setWhatsThis('ident')
        # noinspection PyTypeChecker
        id_item.setFlags(id_item.flags() & ~QtC.Qt.ItemIsEditable & ~QtC.Qt.ItemIsSelectable)
        if self._editable:
            id_item.setBackground(self._DISABLED_COLOR)
        self._table.setItem(row, 0, id_item)

        label_item = QtW.QTableWidgetItem(tag.label if defined else 'new_tag')
        label_item.setWhatsThis('label')
        self._table.setItem(row, 1, label_item)

        # Populate additional columns
        for j, column in enumerate(self._columns[2:-2]):
            value, cell_label = self._get_value_for_column(column, tag, not defined)
            item = QtW.QTableWidgetItem(value)
            item.setWhatsThis(cell_label)
            if not self._editable:
                # noinspection PyTypeChecker
                item.setFlags(item.flags() & ~QtC.Qt.ItemIsEditable & ~QtC.Qt.ItemIsSelectable)
            self._table.setItem(row, 2 + j, item)

        if not self._editable:
            # noinspection PyTypeChecker
            label_item.setFlags(label_item.flags() & ~QtC.Qt.ItemIsEditable & ~QtC.Qt.ItemIsSelectable)

            if defined and tag.type:
                text = tag.type.label
            else:
                text = _t('dialog.edit_tags.tab.tags_common.table.combo_no_type')
            type_item = QtW.QTableWidgetItem(text)
            font = type_item.font()
            font.setItalic(not defined or not tag.type)
            type_item.setFont(font)
            # noinspection PyTypeChecker
            type_item.setFlags(type_item.flags() & ~QtC.Qt.ItemIsEditable & ~QtC.Qt.ItemIsSelectable)
            self._table.setItem(row, self._type_column, type_item)
        else:
            combo = QtW.QComboBox(parent=self._owner)
            combo.currentIndexChanged.connect(self._combo_changed)
            combo.setWhatsThis('tag_type')
            combo.setProperty('row', row)
            combo.addItem(_t('dialog.edit_tags.tab.tags_common.table.combo_no_type'))
            for tag_type in self._tags_dao.get_all_tag_types():
                combo.addItem(self._get_combo_text(tag_type.id, tag_type.label))
            if defined and tag.type is not None:
                combo.setCurrentIndex(combo.findText(self._get_combo_text(tag.type.id, tag.type.label)))
            self._table.setCellWidget(row, self._type_column, combo)

        # count property is added to tag argument before calling this method.
        number_item = _IntTableWidgetItem(str(getattr(tag, 'count') if defined else 0))
        # noinspection PyTypeChecker
        number_item.setFlags(number_item.flags() & ~QtC.Qt.ItemIsEditable & ~QtC.Qt.ItemIsSelectable)
        if self._editable:
            number_item.setBackground(self._DISABLED_COLOR)
        self._table.setItem(row, self._tag_use_count_column, number_item)

    def _get_value_for_column(self, column_name: str, value: _TagType, default: bool) -> typ.Tuple[str, str]:
        """Returns the value for the given column and tag.

        :param column_name: Column’s name.
        :param value: The tag.
        :return: A tuple with the value and the cell label.
        """
        pass

    def _cell_edited(self, row: int, col: int):
        if self._initialized and self._editable:
            if col != self._type_column:
                status, invalid_row, message = self._check_column(col, self._columns_to_check.get(col, True))
                if status != self._OK:
                    utils.gui.show_error(message, parent=self._owner)

            if row not in self._added_rows:
                if self.get_value(row) != self._values[row][0]:
                    self._changed_rows.add(row)
                elif row in self._changed_rows:
                    self._changed_rows.remove(row)

            if self._cell_changed is not None:
                text = self._table.item(row, col).text() if col != self._type_column else \
                    self._table.cellWidget(row, col).currentText()
                self._cell_changed(row, col, text)

    def _check_cell_format(self, row: int, col: int) -> (bool, str):
        text = self._table.item(row, col).text()
        if col == 1:
            if model.Tag.LABEL_PATTERN.match(text) is None:
                return False, _t('dialog.edit_tags.error.invalid_tag_name')
            tag_id = int(self._table.item(row, 0).text())
            if self._tags_dao.tag_exists(tag_id, text):
                return False, _t('dialog.edit_tags.error.duplicate_tag_name')
        return True, ''

    def _combo_changed(self, _):
        """Called when a combobox changes."""
        if self._initialized:
            combo = self._owner.sender()
            self._cell_edited(combo.property('row'), self._type_column)

    def _label_from_combo(self, text: str) -> typ.Optional[str]:
        """Returns the label of the tag type represented by the given text from a combobox.

        :param text: The text to get the label from.
        :return: The type's label or None.
        """
        match = self.COMBO_ITEM_PATTERN.search(text)
        if match is not None:
            return match.group(2)
        return None

    def _id_from_combo(self, text: str) -> typ.Optional[int]:
        """Returns the ID of the tag type represented by the given text from a combobox.

        :param text: The text to get the ID from.
        :return: The ID or None.
        """
        match = self.COMBO_ITEM_PATTERN.search(text)
        if match is not None:
            return int(match.group(1))
        return None

    @staticmethod
    def _get_combo_text(ident: int, label: str) -> str:
        """Formats an ID and label to a combobox item label.

        :param ident: Type’s ID.
        :param label: Type’s label.
        :return: The formatted string.
        """
        return f'{ident} - {label}'


class TagsTab(_TagsTab[model.Tag]):
    def __init__(self, owner: QtW.QWidget, dao: da.TagsDao, editable: bool,
                 selection_changed: typ.Optional[typ.Callable[[None], None]] = None,
                 cell_changed: typ.Optional[typ.Callable[[int, int, str], None]] = None,
                 rows_deleted: typ.Optional[typ.Callable[[typ.List[model.Tag]], None]] = None):
        """Initializes this tab.

        :param owner: Tab’s owner.
        :param dao: The tag’s DAO.
        :param editable: If true the contained table will be editable.
        :param selection_changed: Action called when the selection changes.
        :param cell_changed: Action called when a cell has been edited. It takes the cell’s row, column and text.
        :param rows_deleted: Action called when rows have been deleted. It takes the list of deleted values.
        """
        super().__init__(
            owner,
            dao,
            _t('dialog.edit_tags.tab.tags.title'),
            addable=False,
            editable=editable,
            tag_class=model.Tag,
            additional_columns=[],
            additional_search_columns=[],
            selection_changed=selection_changed,
            cell_changed=cell_changed,
            rows_deleted=rows_deleted
        )


class CompoundTagsTab(_TagsTab[model.CompoundTag]):
    def __init__(self, owner: QtW.QWidget, dao: da.TagsDao, editable: bool,
                 selection_changed: typ.Optional[typ.Callable[[None], None]] = None,
                 cell_changed: typ.Optional[typ.Callable[[int, int, str], None]] = None,
                 rows_deleted: typ.Optional[typ.Callable[[typ.List[model.CompoundTag]], None]] = None):
        """Initializes this tab.

        :param owner: Tab’s owner.
        :param dao: The tag’s DAO.
        :param editable: If true the contained table will be editable.
        :param selection_changed: Action called when the selection changes.
        :param cell_changed: Action called when a cell has been edited. It takes the cell’s row, column and text.
        :param rows_deleted: Action called when rows have been deleted. It takes the list of deleted values.
        """
        super().__init__(
            owner,
            dao,
            _t('dialog.edit_tags.tab.compound_tags.title'),
            addable=True,
            editable=editable,
            tag_class=model.CompoundTag,
            additional_columns=[
                (_t('dialog.edit_tags.tab.compound_tags.table.header.definition'), False),
            ],
            additional_search_columns=[0],
            selection_changed=selection_changed,
            cell_changed=cell_changed,
            rows_deleted=rows_deleted
        )

    def init(self):
        super().init()
        self._table.setColumnHidden(self._tag_use_count_column, True)

    def _get_value_for_column(self, column_name: str, tag: model.CompoundTag, default: bool) -> typ.Tuple[str, str]:
        return (tag.definition if not default else ''), 'definition'

    def _check_cell_format(self, row: int, col: int) -> (bool, str):
        ok, message = super()._check_cell_format(row, col)
        if not ok:
            return False, message
        if col == 2:
            tag_label = self._table.item(row, 2).text()
            try:
                queries.query_to_sympy(tag_label, simplify=False)
            except ValueError as e:
                return False, str(e)
        return True, ''


class _IntTableWidgetItem(QtW.QTableWidgetItem):
    def __lt__(self, other: _IntTableWidgetItem):
        return int(self.text()) < int(other.text())
