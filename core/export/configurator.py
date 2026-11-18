# core/export/configurator.py
"""
Конфигуратор документа DOCX.

Отвечает за настройку полей, языка и других параметров документа.

См. spec://export/docx#configurator
"""

import logging
from docx import Document
from docx.shared import Cm
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

logger = logging.getLogger(__name__)


class DocumentConfigurator:
    """
    Настраивает параметры документа DOCX.

    Ответственности:
    - Установка полей страницы
    - Настройка языка документа (для проверки правописания)
    - Настройка шрифтов по умолчанию

    См. spec://export/docx#configurator
    """

    # Размеры полей по умолчанию (в см)
    DEFAULT_MARGIN = 1.27
    COMPACT_MODERN_MARGIN = 1.25

    def setup_margins(self, doc: Document, mode: str = "compact") -> None:
        """
        Настроить поля документа в зависимости от режима.

        Args:
            doc: Документ python-docx
            mode: Режим экспорта ('compact', 'compact_modern', 'full_modern', 'full')
        """
        margin_cm = self.COMPACT_MODERN_MARGIN if mode == "compact_modern" else self.DEFAULT_MARGIN
        section = doc.sections[0]
        section.left_margin = Cm(margin_cm)
        section.right_margin = Cm(margin_cm)
        section.top_margin = Cm(margin_cm)
        section.bottom_margin = Cm(margin_cm)

    def setup_language(self, doc: Document, lang: str = "ru-RU") -> None:
        """
        Установить язык документа для проверки правописания.

        Использует прямую XML-манипуляцию (OxmlElement) — надёжнее,
        чем высокоуровневые методы python-docx, которые могут отсутствовать.

        Args:
            doc: Документ python-docx
            lang: Код языка (по умолчанию 'ru-RU')
        """

        def _make_lang_element():
            """Создаёт элемент <w:lang w:val='ru-RU' .../>"""
            lang_el = OxmlElement("w:lang")
            lang_el.set(qn("w:val"), lang)
            lang_el.set(qn("w:eastAsia"), lang)
            lang_el.set(qn("w:bidi"), "ar-SA")
            return lang_el

        try:
            styles_elm = doc.styles.element

            # 1. docDefaults → rPrDefault → rPr → lang
            docDefaults = styles_elm.find(qn("w:docDefaults"))
            if docDefaults is None:
                docDefaults = OxmlElement("w:docDefaults")
                styles_elm.insert(0, docDefaults)

            rPrDefault = docDefaults.find(qn("w:rPrDefault"))
            if rPrDefault is None:
                rPrDefault = OxmlElement("w:rPrDefault")
                docDefaults.append(rPrDefault)

            rPr = rPrDefault.find(qn("w:rPr"))
            if rPr is None:
                rPr = OxmlElement("w:rPr")
                rPrDefault.append(rPr)

            # Удалить старый <w:lang> если есть, и вставить новый
            old_lang = rPr.find(qn("w:lang"))
            if old_lang is not None:
                rPr.remove(old_lang)
            rPr.append(_make_lang_element())

            # 2. Стиль «Normal» — принудительно устанавливаем язык
            for style_elm in styles_elm.findall(qn("w:style")):
                if style_elm.get(qn("w:styleId")) == "Normal":
                    style_rPr = style_elm.find(qn("w:rPr"))
                    if style_rPr is None:
                        style_rPr = OxmlElement("w:rPr")
                        style_elm.append(style_rPr)
                    old_lang = style_rPr.find(qn("w:lang"))
                    if old_lang is not None:
                        style_rPr.remove(old_lang)
                    style_rPr.append(_make_lang_element())
                    break

        except Exception as e:
            logger.warning(f"Could not set document language: {e}")

    def configure(self, doc: Document, mode: str = "compact", lang: str = "ru-RU") -> None:
        """
        Полная конфигурация документа.

        Args:
            doc: Документ python-docx
            mode: Режим экспорта
            lang: Код языка
        """
        self.setup_margins(doc, mode)
        self.setup_language(doc, lang)
