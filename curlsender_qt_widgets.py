from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QTextFormat
from PySide6.QtWidgets import (
    QFrame,
    QLayout,
    QLayoutItem,
    QPlainTextEdit,
    QSizePolicy,
    QStyle,
    QStyleOption,
    QTextEdit,
    QWidget,
)


class FlowLayout(QLayout):
    def __init__(self, parent: QWidget | None = None, *, h_spacing: int = 8, v_spacing: int = 8) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing

    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)

    def addItems(self, widgets: Iterable[QWidget]) -> None:
        for widget in widgets:
            self.addWidget(widget)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self) -> Qt.Orientations:
        return Qt.Orientations()

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    def _do_layout(self, rect: QRect, *, test_only: bool) -> int:
        margins = self.contentsMargins()
        effective = rect.adjusted(
            margins.left(),
            margins.top(),
            -margins.right(),
            -margins.bottom(),
        )
        x = effective.x()
        y = effective.y()
        line_height = 0

        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width() + self._h_spacing
            if line_height > 0 and next_x - self._h_spacing > effective.right() + 1:
                x = effective.x()
                y += line_height + self._v_spacing
                next_x = x + hint.width() + self._h_spacing
                line_height = 0

            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))

            x = next_x
            line_height = max(line_height, hint.height())

        used = y + line_height - rect.y() + margins.bottom()
        return max(used, 0)


class _LineNumberArea(QWidget):
    def __init__(self, editor: "CodeEditor") -> None:
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self._editor.line_number_area_width(), 0)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        self._editor.paint_line_number_area(event)


class CodeEditor(QPlainTextEdit):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._line_number_area = _LineNumberArea(self)
        self._colors: dict[str, str] = {
            "editor_bg": "#0d1115",
            "editor_fg": "#d9e2e8",
            "gutter_bg": "#11181d",
            "gutter_fg": "#5d7180",
            "focus": "#5f9eff",
            "select_bg": "#32757f",
            "select_fg": "#0a1416",
        }

        self.blockCountChanged.connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.cursorPositionChanged.connect(self.highlight_current_line)
        self.verticalScrollBar().rangeChanged.connect(self._sync_scrollbar_visibility)
        self.update_line_number_area_width(0)
        self.highlight_current_line()
        self._sync_scrollbar_visibility(0, 0)

        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" " * 4))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def line_number_area_width(self) -> int:
        digits = len(str(max(1, self.blockCount())))
        return 20 + self.fontMetrics().horizontalAdvance("9") * digits

    def update_line_number_area_width(self, _block_count: int) -> None:
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def update_line_number_area(self, rect: QRect, dy: int) -> None:
        if dy:
            self._line_number_area.scroll(0, dy)
        else:
            self._line_number_area.update(0, rect.y(), self._line_number_area.width(), rect.height())

        if rect.contains(self.viewport().rect()):
            self.update_line_number_area_width(0)

    def _sync_scrollbar_visibility(self, minimum: int, maximum: int) -> None:
        self.verticalScrollBar().setVisible(maximum > minimum)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        contents = self.contentsRect()
        self._line_number_area.setGeometry(
            QRect(contents.left(), contents.top(), self.line_number_area_width(), contents.height())
        )

    def paint_line_number_area(self, event) -> None:
        painter = QPainter(self._line_number_area)
        painter.fillRect(event.rect(), QColor(self._colors["gutter_bg"]))

        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        current_line = self.textCursor().blockNumber()

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = str(block_number + 1)
                color = QColor(self._colors["editor_fg"] if block_number == current_line else self._colors["gutter_fg"])
                painter.setPen(color)
                painter.drawText(
                    0,
                    top,
                    self._line_number_area.width() - 10,
                    self.fontMetrics().height(),
                    Qt.AlignmentFlag.AlignRight,
                    number,
                )

            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            block_number += 1

    def highlight_current_line(self) -> None:
        if self.isReadOnly():
            self.setExtraSelections([])
            return

        selection = QTextEdit.ExtraSelection()
        selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        selection.format.setBackground(QColor(self._colors["focus"]).lighter(130))
        selection.format.setForeground(QColor(self._colors["editor_fg"]))
        selection.cursor = self.textCursor()
        selection.cursor.clearSelection()
        self.setExtraSelections([selection])

    def apply_theme(self, colors: dict[str, str]) -> None:
        self._colors = {**self._colors, **colors}
        self._line_number_area.update()
        self.highlight_current_line()
        self.setStyleSheet(
            (
                "QPlainTextEdit {"
                f"background: {self._colors['editor_bg']};"
                f"color: {self._colors['editor_fg']};"
                "border: none;"
                "padding: 14px 16px 14px 0;"
                f"selection-background-color: {self._colors['select_bg']};"
                f"selection-color: {self._colors['select_fg']};"
                "}"
            )
        )
        self.viewport().update()


class PaintableWidget(QWidget):
    def paintEvent(self, event) -> None:  # type: ignore[override]
        option = QStyleOption()
        option.initFrom(self)
        painter = QPainter(self)
        self.style().drawPrimitive(QStyle.PrimitiveElement.PE_Widget, option, painter, self)
        super().paintEvent(event)
