"""Окно встроенной справки: руководство пользователя и «Быстрый старт».

Слева — оглавление по заголовкам (клик переносит к разделу), справа — текст
со скриншотами, сверху — переключатель документов и поиск. Рисует Qt
(QTextBrowser + Markdown), одинаково на ПК и на планшете.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QEvent, QRect, QSize, QTimer, QUrl, Qt
from PySide6.QtGui import QImageReader, QPalette, QKeySequence, QShortcut, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QScroller,
    QStyle,
    QSplitter,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from core.help_docs import DEFAULT_LANGUAGE, read_document, section_matches, tr
from core.utils.android_storage import is_android

logger = logging.getLogger(__name__)

_POSITION_ROLE = Qt.ItemDataRole.UserRole


class _WrapDelegate(QStyledItemDelegate):
    """Высота строки оглавления по переносу текста в ширину колонки.

    Сам QTreeView считает высоту строки без ширины колонки — длинный заголовок
    получает одну строку и обрезается «…», а на планшете подсказок нет.
    """

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        view = self.parent()
        depth = 0
        parent = index.parent()
        while parent.isValid():
            depth += 1
            parent = parent.parent()
        # Запас на отступы строки из QSS и на эмодзи, которые шире букв
        width = view.viewport().width() - view.indentation() * (depth + 1) - 32
        if width <= 50:
            return size
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        rect = option.fontMetrics.boundingRect(
            QRect(0, 0, width, 100000), int(Qt.TextFlag.TextWordWrap), text
        )
        return QSize(size.width(), max(size.height(), rect.height() + 6))

    def paint(self, painter, option, index):
        # Стиль приложения (QSS) рисует текст строки в одну строку с «…» —
        # фон и выделение рисует стиль, а текст с переносом рисуем сами
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        widget = opt.widget
        style = widget.style() if widget is not None else QApplication.style()
        text_rect = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, opt, widget)
        text = opt.text
        opt.text = ""
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)
        painter.save()
        # Цвет обычного текста и для выделенной строки: в темах приложения
        # выделение светлое, белый HighlightedText на нём не читается
        painter.setPen(opt.palette.color(QPalette.ColorRole.Text))
        painter.setFont(opt.font)
        painter.drawText(
            text_rect.adjusted(2, 0, -2, 0),
            int(
                Qt.AlignmentFlag.AlignLeft
                | Qt.AlignmentFlag.AlignVCenter
                | Qt.TextFlag.TextWordWrap
            ),
            text,
        )
        painter.restore()


class HelpDialog(QDialog):
    def __init__(self, parent=None, language: str = DEFAULT_LANGUAGE):
        super().__init__(parent)
        self.language = language
        self.current_doc = None
        self._base_dir: Path | None = None
        self._image_sizes: dict[str, tuple[int, int] | None] = {}
        # Куда прокрутить, когда окно получит окончательный размер: на Android
        # окно разворачивается уже после open_section, текст переносится заново,
        # и прокрутка, сделанная раньше, указывает не туда
        self._pending_position: int | None = None
        self._headings: list[tuple[int, str, int]] = []  # (уровень, заголовок, позиция)

        self.setWindowTitle(tr("title", language))
        self.resize(1100, 760)

        layout = QVBoxLayout(self)

        # Панель: оглавление, документ, поиск, закрыть
        bar = QHBoxLayout()
        self.toggle_contents_btn = QPushButton(tr("toggle_contents", language))
        self.toggle_contents_btn.setCheckable(True)
        self.toggle_contents_btn.setChecked(True)
        self.toggle_contents_btn.toggled.connect(self._set_contents_visible)
        # Значок Qt, а не «☰»: на Android символа нет в шрифте (пустой квадрат)
        self.toggle_contents_btn.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogListView)
        )
        bar.addWidget(self.toggle_contents_btn)

        self.doc_group = QButtonGroup(self)
        self.doc_buttons = {}
        for doc in ("guide", "quick_start"):
            btn = QPushButton(tr(doc, language))
            btn.setCheckable(True)
            self.doc_group.addButton(btn)
            btn.clicked.connect(lambda _=False, d=doc: self.load_document(d))
            self.doc_buttons[doc] = btn
            bar.addWidget(btn)

        bar.addStretch()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(tr("search", language))
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setMinimumWidth(220)
        self.search_edit.returnPressed.connect(self.find_next)
        bar.addWidget(self.search_edit)
        find_btn = QPushButton(tr("find_next", language))
        find_btn.clicked.connect(self.find_next)
        bar.addWidget(find_btn)
        close_btn = QPushButton(tr("close", language))
        close_btn.clicked.connect(self.close)
        bar.addWidget(close_btn)
        layout.addLayout(bar)

        self.status_label = QLabel()
        self.status_label.setVisible(False)
        layout.addWidget(self.status_label)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.toc = QTreeWidget()
        self.toc.setHeaderHidden(True)
        # Длинные заголовки переносятся, а не обрезаются «…» (на планшете нет подсказок)
        self.toc.setWordWrap(True)
        self.toc.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.toc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.toc.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.toc.setItemDelegate(_WrapDelegate(self.toc))
        self.toc.itemClicked.connect(self._on_toc_clicked)
        # Высоты строк считаются по ширине оглавления. Пока оно скрыто, ширина
        # неверная — после показа (и любого изменения ширины) пересчитываем,
        # иначе перенесённые строки наезжают друг на друга
        self._toc_relayout = QTimer(self)
        self._toc_relayout.setSingleShot(True)
        self._toc_relayout.setInterval(0)
        self._toc_relayout.timeout.connect(self.toc.doItemsLayout)
        self.toc.viewport().installEventFilter(self)
        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        # Без отступов ячейки таблиц Markdown липнут к рамкам
        self.browser.document().setDefaultStyleSheet(
            "table { border-collapse: collapse; } th, td { padding: 4px 8px; }"
        )
        self.splitter.addWidget(self.toc)
        self.splitter.addWidget(self.browser)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([330, 770])
        self.splitter.splitterMoved.connect(lambda *_: self.toc.doItemsLayout())
        layout.addWidget(self.splitter, 1)

        QShortcut(QKeySequence(QKeySequence.StandardKey.Find), self).activated.connect(
            self.search_edit.setFocus
        )
        QShortcut(QKeySequence(QKeySequence.StandardKey.FindNext), self).activated.connect(
            self.find_next
        )

        # Картинки подгоняются под ширину текста — после изменения размера окна
        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.setInterval(150)
        self._fit_timer.timeout.connect(self._fit_images)

        self.load_document("guide")

    # --- документы ---------------------------------------------------------

    def load_document(self, doc: str) -> bool:
        self.doc_buttons[doc].setChecked(True)
        if doc == self.current_doc:
            return True
        try:
            text, path = read_document(doc, self.language)
        except OSError:
            logger.exception("Не удалось открыть справку %s", doc)
            self.current_doc = None
            self.browser.setPlainText(tr("missing", self.language, path=doc))
            self.toc.clear()
            self._headings = []
            return False

        self.current_doc = doc
        self._base_dir = path.parent
        base = str(path.parent)
        self.browser.setSearchPaths([base])
        self.browser.document().setBaseUrl(QUrl.fromLocalFile(base + "/"))
        self.browser.setMarkdown(text)
        self._fit_images()
        self._build_toc()
        self.browser.verticalScrollBar().setValue(0)
        self._show_status("")
        return True

    def _build_toc(self) -> None:
        self.toc.clear()
        self._headings = []
        parent_item = None
        block = self.browser.document().begin()
        while block.isValid():
            level = block.blockFormat().headingLevel()
            title = block.text().strip()
            if level >= 2 and title:
                self._headings.append((level, title, block.position()))
                if level == 2 or parent_item is None:
                    item = QTreeWidgetItem(self.toc, [title])
                    parent_item = item
                else:
                    item = QTreeWidgetItem(parent_item, [title])
                item.setToolTip(0, title)
                item.setData(0, _POSITION_ROLE, block.position())
            block = block.next()

    def headings(self) -> list[tuple[int, str]]:
        """Заголовки текущего документа: (уровень, текст)."""
        return [(level, title) for level, title, _ in self._headings]

    # --- переходы ----------------------------------------------------------

    def _on_toc_clicked(self, item: QTreeWidgetItem) -> None:
        position = item.data(0, _POSITION_ROLE)
        if position is not None:
            self.scroll_to_position(int(position))

    def scroll_to_position(self, position: int) -> None:
        # На Android инерционная прокрутка пальцем (QScroller) иначе сбросит переход
        QScroller.scroller(self.browser.viewport()).stop()
        doc = self.browser.document()
        block = doc.findBlock(position)
        cursor = QTextCursor(block)
        self.browser.setTextCursor(cursor)
        # Заголовок — к верхнему краю, а не куда-нибудь в середину окна
        top = doc.documentLayout().blockBoundingRect(block).top()
        self.browser.verticalScrollBar().setValue(int(top))

    def open_section(self, number: str | None) -> bool:
        """Открыть руководство на главе ``number`` («6», «8.1»). True — найдена."""
        if not number:
            return False
        if not self.load_document("guide"):
            return False
        for _, title, position in self._headings:
            if section_matches(title, number):
                self.scroll_to_position(position)
                self._pending_position = position
                self._select_toc_item(position)
                return True
        return False

    def _select_toc_item(self, position: int) -> None:
        items = self.toc.findItems("*", Qt.MatchFlag.MatchWildcard | Qt.MatchFlag.MatchRecursive)
        for item in items:
            if item.data(0, _POSITION_ROLE) == position:
                self.toc.setCurrentItem(item)
                self.toc.scrollToItem(item)
                parent = item.parent()
                if parent is not None:
                    parent.setExpanded(True)
                return

    # --- поиск -------------------------------------------------------------

    def find_next(self) -> bool:
        text = self.search_edit.text().strip()
        if not text:
            return False
        doc = self.browser.document()
        found = doc.find(text, self.browser.textCursor())
        if found.isNull():  # дошли до конца — ищем с начала
            found = doc.find(text, 0)
        if found.isNull():
            self._show_status(tr("not_found", self.language, text=text))
            return False
        self._show_status("")
        self.browser.setTextCursor(found)
        # Найденное — у верхнего края: внизу на планшете его закрывает клавиатура
        bar = self.browser.verticalScrollBar()
        bar.setValue(bar.value() + self.browser.cursorRect(found).top() - 40)
        return True

    def _show_status(self, text: str) -> None:
        self.status_label.setText(text)
        self.status_label.setVisible(bool(text))

    # --- вид ---------------------------------------------------------------

    def _set_contents_visible(self, visible: bool) -> None:
        self.toc.setVisible(visible)
        if visible:
            self._toc_relayout.start()

    def eventFilter(self, obj, event):
        if obj is self.toc.viewport() and event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self._toc_relayout.start()
        return super().eventFilter(obj, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.toc.doItemsLayout()  # пересчитать переносы под новую ширину
        self._fit_timer.start()

    def _natural_size(self, name: str) -> tuple[int, int] | None:
        if name not in self._image_sizes:
            path = Path(name)
            if not path.is_absolute() and self._base_dir is not None:
                path = self._base_dir / name
            size = QImageReader(str(path)).size()
            self._image_sizes[name] = (size.width(), size.height()) if size.isValid() else None
        return self._image_sizes[name]

    def _fit_images(self) -> None:
        """Сжать скриншоты под ширину текста — иначе на планшете они шире экрана."""
        max_width = max(200, self.browser.viewport().width() - 40)
        doc = self.browser.document()
        block = doc.begin()
        while block.isValid():
            it = block.begin()
            while not it.atEnd():
                fragment = it.fragment()
                fmt = fragment.charFormat()
                if fragment.isValid() and fmt.isImageFormat():
                    image_fmt = fmt.toImageFormat()
                    size = self._natural_size(image_fmt.name())
                    if size:
                        width = min(size[0], max_width)
                        if abs(image_fmt.width() - width) > 1:
                            image_fmt.setWidth(width)
                            image_fmt.setHeight(size[1] * width / size[0])
                            cursor = QTextCursor(doc)
                            cursor.setPosition(fragment.position())
                            cursor.setPosition(
                                fragment.position() + fragment.length(),
                                QTextCursor.MoveMode.KeepAnchor,
                            )
                            cursor.setCharFormat(image_fmt)
                it += 1
            block = block.next()
        if self._pending_position is not None:
            self.scroll_to_position(self._pending_position)
            self._pending_position = None


def show_help(parent, section: str | None = None, language: str = DEFAULT_LANGUAGE) -> HelpDialog:
    """Показать справку (одно окно на главное окно) и открыть главу ``section``."""
    dialog = getattr(parent, "_help_dialog", None) if parent is not None else None
    if dialog is None or dialog.language != language:
        dialog = HelpDialog(parent, language)
        if parent is not None:
            parent._help_dialog = dialog
    if not dialog.open_section(section) and section:
        logger.warning("В справке нет главы %s", section)
    if is_android():
        dialog.showMaximized()
    else:
        dialog.show()
    dialog.raise_()
    dialog.activateWindow()
    return dialog


__all__ = ["HelpDialog", "show_help"]
