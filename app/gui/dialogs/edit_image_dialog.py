import os
import platform
import shutil
import subprocess
import typing as typ

import PyQt5.QtGui as QtG
import PyQt5.QtWidgets as QtW
from PyQt5.QtCore import Qt

from app import config, data_access as da, model, utils
from .dialog_base import Dialog
from .edit_tags_dialog import EditTagsDialog
from ..components import Canvas, EllipsisLabel


class EditImageDialog(Dialog):
    """This dialog is used to edit information on an image."""
    EDIT = 0
    ADD = 1
    REPLACE = 2

    _TITLES = ["Edit", "Add", "Replace"]

    def __init__(self, parent: typ.Optional[QtW.QWidget] = None, mode: int = EDIT, show_skip: bool = False):
        """
        Creates an edition dialog.

        :param parent: The widget this dialog is attached to.
        :param mode: Either EDIT, ADD or REPLACE.
        :param show_skip: If true a 'Skip' button will be added.
        """
        if mode not in (EditImageDialog.EDIT, EditImageDialog.ADD, EditImageDialog.REPLACE):
            raise ValueError(f"Unknown mode '{mode}'!")
        if show_skip and mode == EditImageDialog.REPLACE:
            raise ValueError("Cannot show skip button while on replace mode!")

        self._mode = mode
        self._show_skip = show_skip

        self._index = -1
        self._images: typ.List[model.Image] = []
        self._tags = {}

        super().__init__(parent=parent, title=self._get_title(), modal=True)

        self._destination = None
        self._tags_changed = False
        self._image_to_replace = None

        self._dao = da.ImageDao(config.CONFIG.database_path)
        self._tags_dialog = EditTagsDialog(parent=self, editable=False)

    def _init_body(self) -> QtW.QLayout:
        self.setGeometry(0, 0, 400, 400)

        body = QtW.QVBoxLayout()

        self._canvas = Canvas()
        self._canvas.image = None
        body.addWidget(self._canvas)

        middle = QtW.QHBoxLayout()
        middle.addStretch(1)

        self._dest_label = EllipsisLabel()
        middle.addWidget(self._dest_label)

        text = "Replace with…" if self._mode == EditImageDialog.REPLACE else "Move to…"
        self._dest_btn = QtW.QPushButton(text)
        # noinspection PyUnresolvedReferences
        self._dest_btn.clicked.connect(self._on_dest_button_clicked)
        middle.addWidget(self._dest_btn)
        b = QtW.QPushButton("Tags")
        # noinspection PyUnresolvedReferences
        b.clicked.connect(self._show_tags_dialog)
        middle.addWidget(b)
        b = QtW.QPushButton("Show in directory")
        # noinspection PyUnresolvedReferences
        b.clicked.connect(self._open_image_directory)
        middle.addWidget(b)

        body.addLayout(middle)

        class CustomTextEdit(QtW.QTextEdit):
            """Custom class to catch Ctrl+Enter events."""

            def __init__(self, dialog: EditImageDialog):
                super().__init__()
                self._dialog = dialog

            def keyPressEvent(self, e):
                # noinspection PyTypeChecker
                if e.key() in (Qt.Key_Return, Qt.Key_Enter) and e.modifiers() & Qt.ControlModifier:
                    self._dialog._ok_btn.click()
                else:
                    super().keyPressEvent(e)

        self._tags_input = CustomTextEdit(self)
        # noinspection PyUnresolvedReferences
        self._tags_input.textChanged.connect(self._text_changed)
        if self._mode == EditImageDialog.REPLACE:
            self._tags_input.setDisabled(True)
        body.addWidget(self._tags_input)

        self.setMinimumSize(400, 400)

        return body

    def _init_buttons(self) -> typ.List[QtW.QAbstractButton]:
        if self._mode == EditImageDialog.REPLACE:
            self._ok_btn.setDisabled(True)

        self._skip_btn = None
        if self._show_skip:
            self._skip_btn = QtW.QPushButton("Skip")
            # noinspection PyUnresolvedReferences
            self._skip_btn.clicked.connect(self._next)
            return [self._skip_btn]
        return []

    def _show_tags_dialog(self):
        self._tags_dialog.show()

    def _open_image_directory(self):
        """Shows the current image in the system's file explorer."""
        path = os.path.realpath(self._images[self._index].path)
        os_name = platform.system().lower()
        if os_name == "windows":
            subprocess.Popen(f'explorer /select,"{path}"')
        elif os_name == "linux":
            subprocess.Popen(["xdg-open", path])
        elif os_name == "darwin":  # OS-X
            subprocess.Popen(["open", path])

    def set_images(self, images: typ.List[model.Image], tags: typ.Dict[int, typ.List[model.Tag]]):
        """
        Sets the images to display. If more than one image are given, they will be displayed one after another when the
        user clicks on 'OK' or 'Skip'.

        :param images: The images to display.
        :param tags: The tags for each image.
        """
        self._index = 0
        self._images = sorted(images)
        self._tags = tags
        self._set(self._index)

    def set_image(self, image, tags):
        """
        Sets the image to display.

        :param image: The image to display.
        :param tags: The image's tags.
        """
        self.set_images([image], {image.id: tags})

    def _set(self, index: int):
        """Sets the current image."""
        image = self._images[index]

        if self._mode == EditImageDialog.REPLACE:
            self._tags_input.setDisabled(False)
        if self._mode != EditImageDialog.ADD:
            self._tags_input.clear()
            tags = []
            if image.id in self._tags:
                tags = sorted([tag.raw_label() for tag in self._tags[image.id]])
            self._tags_input.append(" ".join(tags))
        if self._mode == EditImageDialog.REPLACE:
            self._tags_input.setDisabled(True)
        self._tags_changed = False

        self._canvas.set_image(image.path)

        if self._skip_btn is not None:
            if self._index == len(self._images) - 1:
                self._skip_btn.setDisabled(True)
                self._ok_btn.setText("Finish")
            else:
                self._ok_btn.setText("Next")

        self.setWindowTitle(self._get_title())

    def _next(self):
        """Goes to the next image."""
        self._index += 1
        self._set(self._index)

    def _on_dest_button_clicked(self):
        """Opens a directory chooser then sets the destionation path to the one selected if any."""
        if self._mode == EditImageDialog.REPLACE:
            destination = utils.open_image_chooser(self)
        else:
            destination = utils.choose_directory(self)
        if destination is not None:
            if self._mode == EditImageDialog.REPLACE:
                img = self._images[0]
                if self._image_to_replace is None:
                    self._image_to_replace = img.path
                if self._image_to_replace == destination:
                    utils.show_error("Cannot replace image with itself!", parent=self)
                    return
                self._destination = destination
                self._ok_btn.setDisabled(False)
                self._images[0] = model.Image(img.id, self._destination)
                self._set(0)
            else:
                self._destination = destination
            self._dest_label.setText("Path: " + self._destination)
            self._dest_label.setToolTip(self._destination)

    def _text_changed(self):
        self._tags_changed = True

    def _get_tags(self) -> typ.List[model.Tag]:
        return [model.Tag.from_string(t) for t in self._tags_input.toPlainText().split()]

    def _ensure_no_compound_tags(self) -> bool:
        tags_dao = da.TagsDao(database=config.CONFIG.database_path)
        for tag in self._tags_input.toPlainText().split():
            t = tag if tag[0].isalnum() or tag[0] == "_" else tag[1:]
            if tags_dao.get_tag_class(t) == model.CompoundTag:
                return False
        return True

    def _get_error(self) -> typ.Optional[str]:
        try:
            tags = self._get_tags()
            if len(tags) == 0:
                return "No tags specified!"
            if not self._ensure_no_compound_tags():
                return "Compound tags are not allowed here!"
            return None
        except ValueError:
            return "Invalid tag format!"

    def _is_valid(self) -> bool:
        return self._get_error() is None

    def _apply(self) -> bool:
        tags = self._get_tags()

        image = self._images[self._index]
        new_path = self._get_new_path(image)

        if self._mode == EditImageDialog.ADD:
            ok = self._add(image, tags, new_path)
        elif self._mode == EditImageDialog.EDIT:
            ok = self._edit(image, tags, new_path)
        else:
            ok = self._replace()

        if ok:
            close = self._index == len(self._images) - 1
            if not close:
                self._next()
            super()._apply()
        else:
            text = "Could not apply changes!" if self._mode == EditImageDialog.EDIT else "Could not add image!"
            utils.show_error(text, parent=self)
            close = False

        return close

    def _get_new_path(self, image: model.Image) -> typ.Optional[str]:
        """
        Returns the new image path. It is obtained by appending the image name to the destination path.

        :param image: The image to move.
        :return: The new path.
        """
        if self._mode != EditImageDialog.REPLACE and self._destination is not None \
                and os.path.dirname(image.path) != self._destination:
            return utils.slashed(os.path.join(self._destination, os.path.basename(image.path)))
        else:
            return None

    def _add(self, image: model.Image, tags: typ.List[model.Tag], new_path: typ.Optional[str]) -> bool:
        """
        Adds an image to the database.

        :param image: The image to add.
        :param tags: Image's tags.
        :param new_path: If present the image will be moved in this directory.
        :return: True if everything went well.
        """
        ok = self._dao.add_image(image.path if new_path is None else new_path, tags)
        if new_path is not None and ok:
            ok = self._move_image(image.path, new_path)
        return ok

    def _edit(self, image: model.Image, tags: typ.List[model.Tag], new_path: typ.Optional[str]) -> bool:
        """
        Edits an image from the database.

        :param image: The image to edit.
        :param tags: Image's tags.
        :param new_path: If present the image will be moved in this directory.
        :return: True if everything went well.
        """
        if self._tags_changed:
            ok = self._dao.update_image_tags(image.id, tags)
        else:
            ok = True
        if ok and new_path is not None:
            ok = self._dao.update_image_path(image.id, new_path)
            if ok:
                ok = self._move_image(image.path, new_path)
        return ok

    def _replace(self) -> bool:
        """
        Replaces an image by another one. The old image is deleted. The new image will stay in its directory.

        :return: True if everything went well.
        """
        try:
            os.remove(self._image_to_replace)
        except FileNotFoundError:
            return False
        return self._dao.update_image_path(self._images[0].id, self._destination)

    def _move_image(self, path: str, new_path: str) -> bool:
        """
        Moves an image to a specific directory.

        :param path: Image's path.
        :param new_path: Path to the new directory.
        :return: True if the image was moved.
        """
        try:
            shutil.move(path, new_path)
            return True
        except FileExistsError:
            utils.show_error("File already exists in destination!", parent=self)
            return False

    def _get_title(self) -> str:
        return f"{self._TITLES[self._mode]} Image ({self._index + 1}/{len(self._images)})"

    def closeEvent(self, event: QtG.QCloseEvent):
        self._tags_dialog.close()
        super().closeEvent(event)
