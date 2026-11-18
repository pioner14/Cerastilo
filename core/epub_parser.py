"""
EPUB Parser для рабочих тетрадей.

Парсит .epub файлы рабочих тетрадей, извлекая:
- Заголовки недель (с датами: start_day, end_day, month)
- Задания с секцией (section) и позицией (section_position)
- Песни
- Чтение Библии

Ключевые принципы:
1. Номера заданий берутся из EPUB «как есть» (сквозная нумерация 1-10+)
2. Каждое задание обогащается section и section_position
3. Квалификация определяется по (section, position), а НЕ по глобальному номеру
"""

import posixpath
import zipfile
import xml.etree.ElementTree as ET
from urllib.parse import unquote

from bs4 import BeautifulSoup
import re
import json
import warnings
import logging
from pathlib import Path

warnings.filterwarnings("ignore", category=UserWarning)
logger = logging.getLogger(__name__)

# Русские месяцы для парсинга заголовков
MONTHS_PATTERN = (
    r"ЯНВАРЯ|ФЕВРАЛЯ|МАРТА|АПРЕЛЯ|МАЯ|ИЮНЯ|ИЮЛЯ|АВГУСТА|СЕНТЯБРЯ|ОКТЯБРЯ|НОЯБРЯ|ДЕКАБРЯ"
)
MONTHS_TO_NUM = {
    "ЯНВАРЯ": 1,
    "ФЕВРАЛЯ": 2,
    "МАРТА": 3,
    "АПРЕЛЯ": 4,
    "МАЯ": 5,
    "ИЮНЯ": 6,
    "ИЮЛЯ": 7,
    "АВГУСТА": 8,
    "СЕНТЯБРЯ": 9,
    "ОКТЯБРЯ": 10,
    "НОЯБРЯ": 11,
    "ДЕКАБРЯ": 12,
}

# Слова, по которым пропускаем H3 (не задания)
SKIP_KEYWORDS = ["песня", "псалом", "заключительные", "вступительные"]

_EN_MONTHS = {
    name: number
    for number, name in enumerate(
        "JANUARY FEBRUARY MARCH APRIL MAY JUNE JULY AUGUST SEPTEMBER OCTOBER NOVEMBER DECEMBER".split(),
        1,
    )
}
_LANGUAGE_RULES = {
    "ru": {
        "skip": "|".join(SKIP_KEYWORDS),
        "song": r"Песня\s+(\d+)",
        "bible_heading": r"^[А-ЯЁ].*?\d+",
        "reading": "чтение библии",
        "bible_fallback": "Чтение Библии",
        "gems": "жемчужины",
        "minutes": r"мин\.?",
        "discussion": "Обсуждение",
        "talk": r"Речь(?:\s+председателя)?",
        "talk_title": r"речь|доклад|обучающая",
        "cbs": "изучение библии в собрании",
        "unnumbered_cbs": r"изучение|библии в собрании",
        "reader": "Чтец (Изучение Библии)",
    },
    "en": {
        "skip": r"^(?:song\s+\d+|opening comments\b|concluding comments\b)",
        "song": r"Song\s+(\d+)",
        "bible_heading": r"^(?:[1-3]\s+)?[A-Z]+(?:\s+[A-Z]+)*\s+\d",
        "reading": "bible reading",
        "bible_fallback": "Bible Reading",
        "gems": "spiritual gems",
        "minutes": r"min\.?(?:\s+or less)?",
        "discussion": r"Discussion\b",
        "talk": r"Talk\b",
        "talk_title": r"\btalk\b",
        "cbs": "congregation bible study",
        "unnumbered_cbs": "congregation bible study",
        "reader": "Congregation Bible Study Reader",
    },
}
_EN_MONTH = "|".join(_EN_MONTHS)
_EN_WEEK = re.compile(
    rf"(?P<start_month>{_EN_MONTH})\s+(?P<start_day>\d{{1,2}})"
    rf"(?:,\s*(?P<start_year>\d{{4}}))?\s*[—–-]\s*"
    rf"(?:(?P<end_month>{_EN_MONTH})\s+)?(?P<end_day>\d{{1,2}})"
    rf"(?:,\s*\d{{4}})?",
    re.IGNORECASE,
)


from core.chairman_talk import role_talk_type

_CONTAINER_NS = "urn:oasis:names:tc:opendocument:xmlns:container"
_OPF_NS = "http://www.idpf.org/2007/opf"


def iter_epub_documents(epub_path, *, on_language=None):
    """Читает EPUB через zipfile и отдаёт (имя, байты) всех XHTML-документов.

    Порядок — как в manifest OPF; имя — href без URL-кодирования, относительно
    папки OPF. Входят все элементы application/xhtml+xml (в том числе nav и
    cover — так же, как раньше отдавал EbookLib; лишнее отсекает вызывающий).
    """
    with zipfile.ZipFile(epub_path, "r") as zf:
        container = ET.fromstring(zf.read("META-INF/container.xml"))
        opf_path = None
        for root_file in container.iter(f"{{{_CONTAINER_NS}}}rootfile"):
            if root_file.get("media-type") == "application/oebps-package+xml":
                opf_path = root_file.get("full-path")
                break
        if not opf_path:
            raise ValueError("В container.xml нет пакета OPF")
        opf_dir = posixpath.dirname(opf_path)

        opf = ET.fromstring(zf.read(posixpath.normpath(opf_path)))
        if on_language is not None:
            language = opf.findtext(
                f"{{{_OPF_NS}}}metadata/{{http://purl.org/dc/elements/1.1/}}language"
            )
            on_language(language)

        manifest = opf.find(f"{{{_OPF_NS}}}manifest")
        if manifest is None:
            raise ValueError("В OPF нет manifest")
        for item in manifest.findall(f"{{{_OPF_NS}}}item"):
            if item.get("media-type") != "application/xhtml+xml":
                continue
            name = unquote(item.get("href", ""))
            data = zf.read(posixpath.normpath(posixpath.join(opf_dir, name)))
            yield name, data


class WorkbookParser:
    def __init__(self, epub_path):
        self.epub_path = epub_path
        self.weeks = []
        self._language = None

    @property
    def _rules(self):
        return _LANGUAGE_RULES[self._language or "ru"]

    def _set_epub_language(self, language):
        code = re.split(r"[-_]", (language or "").strip().lower(), maxsplit=1)[0]
        if code in _LANGUAGE_RULES:
            self._language = code

    def parse(self):
        """Парсит EPUB и возвращает список недель с заданиями."""
        try:
            filename_code = re.search(r"_([EU])_", Path(self.epub_path).name, re.IGNORECASE)
            self._language = (
                {"E": "en", "U": "ru"}[filename_code[1].upper()] if filename_code else None
            )
            for name, data in iter_epub_documents(
                self.epub_path, on_language=self._set_epub_language
            ):
                if "toc" in name.lower() or "nav" in name.lower() or "extracted" in name.lower():
                    continue

                # Байты, а не decode("utf-8"): BeautifulSoup сам определит
                # кодировку по BOM и XML-декларации (EPUB бывает и в UTF-16).
                soup = BeautifulSoup(data, "html.parser")
                # Раньше (через EbookLib) <head> отбрасывался, и заголовок недели
                # брался из <h1>; <title> в тетрадях даёт другой регистр.
                for head in soup.find_all("head"):
                    head.decompose()

                week_info = self._try_parse_week(soup)
                if week_info:
                    self.weeks.append(week_info)

            logger.info(f"✅ Найдено недель: {len(self.weeks)}")
            for w in self.weeks[:3]:
                logger.debug(
                    f"  📅 {w['week_title']}: Songs={w['songs']}, Assignments={len(w['assignments'])}"
                )
            return self.weeks

        except Exception as e:
            logger.error(f"❌ Ошибка при парсинге EPUB: {e}", exc_info=True)
            return []

    def _try_parse_week(self, soup):
        """Пытается распарсить HTML-документ как одну неделю.

        Возвращает dict с week_title, start_day, end_day, month, month_num, start_month_num,
        assignments, songs, bible_reading — или None если это не неделя.
        """
        if self._language != "ru":
            for tag in [soup.find("title"), soup.find("h1")]:
                if tag is None:
                    continue
                title = tag.get_text().replace("\xa0", " ").strip()
                match = _EN_WEEK.fullmatch(title)
                if match:
                    self._language = "en"
                    start_month = match["start_month"].upper()
                    end_day = int(match["end_day"])
                    month = (
                        (match["end_month"] or start_month).upper() if end_day >= 4 else start_month
                    )
                    return {
                        "week_title": title,
                        "start_day": int(match["start_day"]),
                        "end_day": end_day,
                        "month": month,
                        "month_num": _EN_MONTHS[month],
                        "start_month_num": _EN_MONTHS[start_month],
                        "start_year": int(match["start_year"]) if match["start_year"] else None,
                        "assignments": self._get_assignments(soup),
                        "songs": self._get_songs(soup),
                        "bible_reading": self._get_bible_reading(soup),
                    }
            if self._language == "en":
                return None

        # Паттерн для недель в пределах одного месяца: "1-7 АПРЕЛЯ"
        single_month_pattern = r"(\d+)\s*[—–\-]\s*(\d+)\s+(" + MONTHS_PATTERN + ")"

        # Паттерн для недель на границе месяцев: "28 АПРЕЛЯ — 4 МАЯ"
        cross_month_pattern = (
            r"(\d+)\s+(" + MONTHS_PATTERN + r")\s*[—–\-]\s*(\d+)\s+(" + MONTHS_PATTERN + ")"
        )

        # Неделя на стыке лет пишется с годами:
        # "28 ДЕКАБРЯ 2026 года — 3 ЯНВАРЯ 2027 года" — без этого шаблона она
        # не распознавалась и выпадала из импорта целиком.
        cross_year_pattern = (
            r"(\d+)\s+(" + MONTHS_PATTERN + r")\s+(\d{4})\s*(?:года|г\.)?\s*[—–\-]\s*"
            r"(\d+)\s+(" + MONTHS_PATTERN + r")\s+(\d{4})\s*(?:года|г\.)?"
        )

        week_title = None
        start_day = None
        end_day = None
        month = None
        start_month = None
        start_year = None

        # Ищем заголовок недели в <title> и <h1>
        for tag in [soup.find("title"), soup.find("h1")]:
            if not tag:
                continue
            text = tag.get_text().replace("\xa0", " ").strip()

            # Стык лет — с явными годами
            match = re.search(cross_year_pattern, text, re.IGNORECASE | re.UNICODE)
            if match:
                start_day = int(match.group(1))
                month1 = match.group(2).upper()
                start_year = int(match.group(3))
                end_day = int(match.group(4))
                month2 = match.group(5).upper()
                # Название — в том же виде, что у остальных недель
                week_title = f"{start_day} {month1} — {end_day} {month2}"
                month = month2 if end_day >= 4 else month1
                start_month = month1
                break

            # Сначала пробуем паттерн для границы месяцев
            match = re.search(cross_month_pattern, text, re.IGNORECASE | re.UNICODE)
            if match:
                week_title = match.group(0).replace("\xa0", " ")
                start_day = int(match.group(1))
                month1 = match.group(2).upper()
                end_day = int(match.group(3))
                month2 = match.group(4).upper()
                # Определяем месяц по большинству дней в неделе (кто забрал >= 4 дней)
                if end_day >= 4:
                    month = month2
                else:
                    month = month1
                start_month = month1
                break

            # Затем пробуем обычный паттерн
            match = re.search(single_month_pattern, text, re.IGNORECASE | re.UNICODE)
            if match:
                week_title = match.group(0).replace("\xa0", " ")
                start_day = int(match.group(1))
                end_day = int(match.group(2))
                month = match.group(3).upper()
                start_month = month
                break

        if not week_title:
            return None

        self._language = "ru"
        month_num = MONTHS_TO_NUM.get(month, 0)
        start_month_num = MONTHS_TO_NUM.get(start_month, 0)

        return {
            "week_title": week_title,
            "start_day": start_day,
            "end_day": end_day,
            "month": month,
            "month_num": month_num,
            "start_month_num": start_month_num,
            "start_year": start_year,  # только если год указан в заголовке
            "assignments": self._get_assignments(soup),
            "songs": self._get_songs(soup),
            "bible_reading": self._get_bible_reading(soup),
        }

    def _get_songs(self, soup):
        """Парсит номера песен из <strong> и <a> тегов."""
        songs = []
        for tag in soup.find_all(["strong", "a"]):
            text = tag.get_text()
            match = re.search(self._rules["song"], text)
            if match:
                num = match.group(1)
                if num not in songs:
                    songs.append(num)
        return songs

    def _get_bible_reading(self, soup):
        """Ищет чтение Библии в H2 заголовках."""
        for h2 in soup.find_all("h2"):
            text = h2.get_text().strip()
            if re.search(self._rules["bible_heading"], text):
                return text
        return self._rules["bible_fallback"]

    def _get_assignments(self, soup):
        """Парсит задания, обогащая каждое section и section_position.

        Возвращает список словарей:
        {
            'number': '7',           # сквозной номер из EPUB
            'text': 'Тема задания',
            'type': 'student',       # тип задания
            'duration': 5,           # длительность в минутах
            'section': 'ministry',   # раздел встречи
            'section_position': 4,   # позиция внутри раздела (1-based)
        }
        """
        from core.validation_service import ValidationService

        assignments = []
        seen_numbers = set()
        current_section = None

        # Счётчики позиций внутри каждого раздела
        section_counters = {"treasures": 0, "ministry": 0, "living": 0}

        for tag in soup.find_all(["h2", "h3"]):
            text = tag.get_text().strip()

            # --- ОБРАБОТКА РАЗДЕЛОВ (H2) ---
            if tag.name == "h2":
                new_section = ValidationService.identify_section(text)
                if new_section:
                    current_section = new_section
                continue

            # --- ОБРАБОТКА ЗАДАНИЙ (H3) ---
            if tag.name == "h3":
                if not current_section:
                    continue

                h3_text = text

                # Пропускаем песни и служебные строки
                lower_text = h3_text.lower()
                if re.search(self._rules["skip"], lower_text):
                    continue

                # Паттерн: "N. Название"
                match = re.match(r"^(\d+)[.\s]+(.+)$", h3_text, re.UNICODE)

                num = None
                title = h3_text

                if match:
                    potential_num = match.group(1)
                    potential_title = match.group(2).strip()

                    if ValidationService.is_valid_assignment(current_section, potential_num):
                        num = potential_num
                        title = potential_title

                # Пункты без номера в Living (или другой секции) — пропускаем
                # Мы НЕ генерируем виртуальные номера: берём только то, что есть в EPUB
                if not num:
                    # Но для Изучения Библии в собрании — особый случай:
                    # оно часто в H3 без номера, но мы его распознаём по тексту
                    if current_section == "living" and re.search(
                        self._rules["unnumbered_cbs"], lower_text
                    ):
                        # CBS обрабатывается ниже как спецслучай без номера
                        pass
                    else:
                        continue

                if num and num in seen_numbers:
                    continue

                # Ищем длительность (минуты) в текущем и соседних элементах
                duration = self._find_duration(tag, h3_text)

                # Ищем маркеры типа задания в параграфе после заголовка H3.
                # «Обсуждение» и «Речь» — один брат без напарника.
                # «Диалог» — стандартное студенческое задание (override не нужен).
                discussion_marker = None
                talk_marker = None
                if current_section == "ministry":
                    discussion_marker = self._find_discussion_marker(tag)
                    if not discussion_marker:
                        talk_marker = self._find_talk_marker(tag)

                # Для пронумерованных заданий без длительности в treasures/ministry —
                # доверяемся только если номер маленький
                if not duration and current_section != "living":
                    if num and int(num) <= 6:
                        duration = 5  # дефолт
                    else:
                        continue
                elif not duration:
                    duration = 5  # дефолт для Living

                if num:
                    seen_numbers.add(num)

                # Определяем тип по разделу и ключевым словам
                # talk_marker переопределяет тип как 'teaching' независимо от заголовка
                atype = self._determine_type(current_section, title, talk_marker=talk_marker)
                # «(N мин.) Речь председателя программы / ответственного за
                # служение / секретаря / координатора» — речь по обязанности,
                # не учебное задание (core/chairman_talk.py)
                if current_section in ("ministry", "living"):
                    atype = role_talk_type(self._first_paragraph(tag)) or atype

                # Увеличиваем счётчик позиции в секции
                if atype == "cbs":
                    section_pos_str = "conductor"
                else:
                    section_counters[current_section] = section_counters.get(current_section, 0) + 1
                    section_pos = section_counters[current_section]
                    section_pos_str = str(section_pos)

                assignment = {
                    "number": num or f"_auto_{current_section}_{section_pos_str}",
                    "text": title,
                    "type": atype,
                    "duration": duration,
                    "section": "cbs" if atype == "cbs" else current_section,
                    "section_position": section_pos_str,
                }
                if discussion_marker is not None:
                    assignment["discussion_marker"] = discussion_marker
                assignments.append(assignment)

                # CBS — автоматически добавляем чтеца
                if atype == "cbs":
                    assignments.append(
                        {
                            "number": f"{num}_reader" if num else "_auto_cbs_reader",
                            "text": self._rules["reader"],
                            "type": "cbs_reader",
                            "duration": duration,
                            "section": "cbs",
                            "section_position": "reader",
                        }
                    )

        # Сортируем по сквозному номеру
        def sort_key(a):
            try:
                return int(re.sub(r"\D", "", a["number"]))
            except (ValueError, TypeError):
                return 99

        assignments.sort(key=sort_key)
        return assignments

    def _find_duration(self, tag, h3_text):
        """Ищет длительность (N мин.) в тексте H3 и соседних элементах."""
        pattern = rf"\((\d+)\s*{self._rules['minutes']}\)"
        # Сначала в самом H3
        dur_match = re.search(pattern, h3_text)
        if dur_match:
            return int(dur_match.group(1))

        # Затем в соседних элементах
        search_tag = tag.next_element
        count = 0
        while search_tag and count < 30:
            if hasattr(search_tag, "name") and search_tag.name in ["h1", "h2", "h3"]:
                break
            text = ""
            if hasattr(search_tag, "get_text"):
                text = search_tag.get_text()
            elif isinstance(search_tag, str):
                text = search_tag

            dur_match = re.search(pattern, text)
            if dur_match:
                return int(dur_match.group(1))
            search_tag = search_tag.next_element
            count += 1

        return None

    @staticmethod
    def _first_paragraph(tag):
        """Текст первого абзаца после заголовка H3 (до следующего заголовка)."""
        search_tag = tag.next_element
        count = 0
        while search_tag and count < 30:
            name = getattr(search_tag, "name", None)
            if name in ("h1", "h2", "h3"):
                break
            if name == "p":
                return search_tag.get_text()
            search_tag = search_tag.next_element
            count += 1
        return ""

    def _find_discussion_marker(self, tag):
        """Ищет маркер «Обсуждение» в соседних элементах после H3.

        В EPUB обсуждения оформлены как параграф-тело, начинающийся
        с «(N мин.) Обсуждение. <тема>». Возвращаем найденную начальную
        подстроку «(N мин.) Обсуждение» или None, если маркера нет.

        Идём по тем же соседним элементам, что и _find_duration, но ищем
        именно токен «Обсуждение» (с заглавной — как в оригинале).
        """
        search_tag = tag.next_element
        count = 0
        while search_tag and count < 30:
            if hasattr(search_tag, "name") and search_tag.name in ["h1", "h2", "h3"]:
                break
            text = ""
            if hasattr(search_tag, "get_text"):
                text = search_tag.get_text()
            elif isinstance(search_tag, str):
                text = search_tag

            m = re.search(
                rf"\(\d+\s*{self._rules['minutes']}\)\s*{self._rules['discussion']}", text
            )
            if m:
                return m.group(0).strip()
            search_tag = search_tag.next_element
            count += 1

        return None

    def _find_talk_marker(self, tag):
        """Ищет маркер «Речь» в соседних элементах после H3.

        В EPUB речи оформлены как параграф-тело вида
        «(N мин.) Речь на основе ...» или просто «(N мин.) Речь».
        Это задание для одного брата без напарника (аналогично «Обсуждению»,
        но с другим маркером).

        Возвращает найденную подстроку «(N мин.) Речь» или None.
        Вызывается только для ministry-заданий, у которых нет discussion_marker.
        """
        search_tag = tag.next_element
        count = 0
        while search_tag and count < 30:
            if hasattr(search_tag, "name") and search_tag.name in ["h1", "h2", "h3"]:
                break
            text = ""
            if hasattr(search_tag, "get_text"):
                text = search_tag.get_text()
            elif isinstance(search_tag, str):
                text = search_tag

            # «Речь председателя программы» (с февраля 2027) ловим целиком
            m = re.search(rf"\(\d+\s*{self._rules['minutes']}\)\s*{self._rules['talk']}", text)
            if m:
                return m.group(0).strip()
            search_tag = search_tag.next_element
            count += 1

        return None

    def _determine_type(self, section, title, talk_marker=None):
        """Определяет тип задания по разделу и ключевым словам в заголовке.

        Args:
            section: Раздел встречи ('treasures', 'ministry', 'living').
            title: Заголовок задания из H3.
            talk_marker: Если передан (из _find_talk_marker), задание является
                «Речью» независимо от содержимого заголовка. Обрабатывает случаи,
                когда H3 содержит авторскую тему (напр. «Объясняйте свои взгляды»),
                а не стандартное слово «Речь».
        """
        lower_title = title.lower()

        if section == "treasures":
            if self._rules["reading"] in lower_title:
                return "reading"
            elif self._rules["gems"] in lower_title:
                return "gems"
            else:
                return "treasures"

        elif section == "ministry":
            # talk_marker — надёжнее, чем поиск слов в заголовке:
            # тема речи может быть произвольной («Объясняйте свои взгляды»),
            # тогда как маркер «(N мин.) Речь» всегда присутствует в теле параграфа.
            if talk_marker:
                return "teaching"
            if re.search(self._rules["talk_title"], lower_title):
                return "teaching"
            else:
                return "student"

        elif section == "living":
            # CBS определяется по точной фразе "изучение библии в собрании"
            # Не путать с другими заданиями, содержащими слово "изучение"
            if self._rules["cbs"] in lower_title:
                return "cbs"
            else:
                return "living"

        return "student"  # fallback


def parse_meeting_workbook(epub_path):
    """Утилита: парсит EPUB и сохраняет JSON рядом."""
    parser = WorkbookParser(epub_path)
    weeks = parser.parse()
    if not weeks:
        return None
    json_path = epub_path.replace(".epub", ".json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"weeks": weeks}, f, ensure_ascii=False, indent=2)
    return json_path
