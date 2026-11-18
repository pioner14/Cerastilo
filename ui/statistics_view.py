"""Вкладка «Статистика»: кто, когда и с какими пунктами выступает.

Два вида на одних данных (core/statistics):
- тепловая карта — строки участники, столбцы недели, цвет — раздел пункта;
- полосы нагрузки — сколько заданий у каждого и из чего они состоят.
Рисуется QPainter'ом, без внешних библиотек графиков.
"""

from datetime import date, timedelta
from typing import Any, Dict, List

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from core.statistics import CATEGORIES, CATEGORY_NAMES, GROUPS
from core.styles import palette, register_theme_listener, unregister_theme_listener
from core.i18n import _

# Цвета категорий — средние тона, читаются и на светлом, и на тёмном фоне
CATEGORY_COLORS = {
    "chairman": "#eda100",
    "treasures": "#2a78d6",
    "ministry": "#eb6834",
    "living": "#1baf7a",
    "cbs": "#6250d6",
    "assistant": "#e87ba4",
    "prayer": "#a8a69d",
}

PERIODS = [(3, _("3 месяца")), (4, _("4 месяца")), (6, _("6 месяцев")), (12, _("12 месяцев"))]

NAME_W = 190  # ширина колонки имён
ROW_H = 20  # высота строки
GAP = 2  # промежуток между клетками
HEADER_H = 20  # подписи недель


def _fmt(d: date) -> str:
    return d.strftime("%d.%m.%Y")


class HeatmapWidget(QWidget):
    """Строки — участники, столбцы — недели; клетка окрашена по разделу пункта."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.weeks: List[date] = []
        self.people: List[Dict[str, Any]] = []
        self.setMouseTracking(True)

    def set_data(self, weeks, people):
        self.weeks, self.people = weeks, people
        self.updateGeometry()
        self.update()

    def _cell_w(self) -> float:
        return max(6.0, (self.width() - NAME_W) / max(1, len(self.weeks)))

    def sizeHint(self):
        return QSize(NAME_W + 17 * 24, HEADER_H + len(self.people) * ROW_H + 4)

    def minimumSizeHint(self):
        return QSize(NAME_W + 200, self.sizeHint().height())

    def paintEvent(self, _event):
        colors = palette()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cw = self._cell_w()
        name_font = p.font()
        week_font = p.font()
        week_font.setPointSizeF(max(7.0, week_font.pointSizeF() - 1))

        # подписи недель — через одну, чтобы не слипались (мельче имён)
        p.setFont(week_font)
        p.setPen(QColor(colors.text_secondary))
        step = 1 if cw >= 40 else 2 if cw >= 20 else 4
        for i, wk in enumerate(self.weeks):
            if i % step == 0:
                rect = QRect(int(NAME_W + i * cw), 0, int(cw * step), HEADER_H)
                p.drawText(
                    rect,
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    wk.strftime("%d.%m"),
                )

        p.setFont(name_font)
        empty = QColor(colors.hover)
        for r, person in enumerate(self.people):
            y = HEADER_H + r * ROW_H
            p.setPen(QColor(colors.text_primary))
            p.drawText(
                QRect(0, y, NAME_W - 8, ROW_H),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                p.fontMetrics().elidedText(person["name"], Qt.TextElideMode.ElideRight, NAME_W - 8),
            )
            p.setPen(Qt.PenStyle.NoPen)
            for i, wk in enumerate(self.weeks):
                cell = QRect(int(NAME_W + i * cw), y + 1, int(cw) - GAP, ROW_H - 2 * GAP)
                cats = person["weeks"].get(wk)
                if not cats:
                    p.setBrush(empty)
                    p.drawRoundedRect(cell, 3, 3)
                    continue
                # Несколько заданий в неделю — клетка делится по горизонтали
                part = cell.height() / len(cats)
                for j, cat in enumerate(cats):
                    p.setBrush(QColor(CATEGORY_COLORS[cat]))
                    sub = QRect(cell.x(), int(cell.y() + j * part), cell.width(), int(part) or 1)
                    p.drawRoundedRect(sub, 3, 3)
        p.end()

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        r = (pos.y() - HEADER_H) // ROW_H
        i = int((pos.x() - NAME_W) // self._cell_w())
        if pos.x() >= NAME_W and 0 <= r < len(self.people) and 0 <= i < len(self.weeks):
            person, wk = self.people[r], self.weeks[i]
            cats = person["weeks"].get(wk, [])
            what = ", ".join(CATEGORY_NAMES[c] for c in cats) if cats else _("нет заданий")
            QToolTip.showText(
                event.globalPosition().toPoint(), f"{person['name']}\n{_fmt(wk)}: {what}", self
            )
        else:
            QToolTip.hideText()


class LoadBarsWidget(QWidget):
    """Полоса на участника: длина — число заданий, сегменты — категории."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.people: List[Dict[str, Any]] = []
        self._segments: List[tuple] = []  # (QRect, текст подсказки)
        self.setMouseTracking(True)

    def set_data(self, people):
        self.people = sorted(people, key=lambda r: (-r["total"], r["name"]))
        self.updateGeometry()
        self.update()

    def sizeHint(self):
        return QSize(NAME_W + 400, len(self.people) * ROW_H + 4)

    def minimumSizeHint(self):
        return QSize(NAME_W + 200, self.sizeHint().height())

    def paintEvent(self, _event):
        colors = palette()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        max_total = max((r["total"] for r in self.people), default=0) or 1
        bar_w = self.width() - NAME_W - 40
        self._segments = []
        for r, person in enumerate(self.people):
            y = r * ROW_H
            p.setPen(QColor(colors.text_primary))
            p.drawText(
                QRect(0, y, NAME_W - 8, ROW_H),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                p.fontMetrics().elidedText(person["name"], Qt.TextElideMode.ElideRight, NAME_W - 8),
            )
            x = float(NAME_W)
            unit = bar_w / max_total
            p.setPen(Qt.PenStyle.NoPen)
            for cat in CATEGORIES:
                n = person["counts"].get(cat, 0)
                if not n:
                    continue
                seg = QRect(int(x), y + 3, max(1, int(n * unit) - GAP), ROW_H - 6)
                p.setBrush(QColor(CATEGORY_COLORS[cat]))
                p.drawRoundedRect(seg, 3, 3)
                self._segments.append((seg, f"{person['name']}\n{CATEGORY_NAMES[cat]}: {n}"))
                x += n * unit
            p.setPen(QColor(colors.text_secondary))
            p.drawText(
                QRect(int(x) + 6, y, 40, ROW_H),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                str(person["total"]),
            )
        p.end()

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        for rect, text in self._segments:
            if rect.contains(pos):
                QToolTip.showText(event.globalPosition().toPoint(), text, self)
                return
        QToolTip.hideText()


class StatisticsView(QWidget):
    """Вкладка «📊 Статистика»."""

    def __init__(self, facade, parent=None):
        super().__init__(parent)
        self.facade = facade

        layout = QVBoxLayout(self)

        filters = QHBoxLayout()
        self.period_combo = QComboBox()
        for months, label in PERIODS:
            self.period_combo.addItem(label, months)
        self.period_combo.setCurrentIndex(1)
        self.group_combo = QComboBox()
        for key, label in GROUPS.items():
            self.group_combo.addItem(label, key)
        filters.addWidget(QLabel(_("Период:")))
        filters.addWidget(self.period_combo)
        filters.addWidget(QLabel(_("Кто:")))
        filters.addWidget(self.group_combo)
        filters.addStretch()
        layout.addLayout(filters)

        self.legend = QLabel()
        self.legend.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self.legend)

        content = QWidget()
        body = QVBoxLayout(content)
        self.heatmap_title = QLabel(_("<b>Кто и когда выступал</b>"))
        self.heatmap = HeatmapWidget()
        self.bars_title = QLabel(_("<b>Нагрузка по участникам</b>"))
        self.bars = LoadBarsWidget()
        for w in (self.heatmap_title, self.heatmap, self.bars_title, self.bars):
            body.addWidget(w)
        body.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        layout.addWidget(scroll)

        self.period_combo.currentIndexChanged.connect(self.load_data)
        self.group_combo.currentIndexChanged.connect(self.load_data)
        register_theme_listener(self._on_theme_changed)
        self.destroyed.connect(lambda *_, cb=self._on_theme_changed: unregister_theme_listener(cb))

        self._update_legend()
        self.load_data()

    def _on_theme_changed(self, _theme):
        self._update_legend()
        self.heatmap.update()
        self.bars.update()

    def _update_legend(self):
        items = "".join(
            f'<span style="color:{CATEGORY_COLORS[c]}">■</span>&nbsp;{CATEGORY_NAMES[c]}&nbsp;&nbsp;&nbsp;'
            for c in CATEGORIES
        )
        self.legend.setText(f'<span style="color:{palette().text_secondary}">{items}</span>')

    def load_data(self, *_):
        """Перечитать данные (вызывается и при переключении на вкладку)."""
        months = self.period_combo.currentData()
        end = date.today() + timedelta(weeks=8)  # видно и уже распределённые недели вперёд
        start = date.today() - timedelta(days=int(months * 30.5))
        stats = self.facade.get_assignment_stats(start, end, self.group_combo.currentData())
        self.heatmap.set_data(stats["weeks"], stats["people"])
        self.bars.set_data(stats["people"])
