# tests/test_epub_parser.py
"""
Тесты для WorkbookParser (EPUB парсер).

См. spec://import/epub#parser
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from bs4 import BeautifulSoup

from core.epub_parser import (
    MONTHS_PATTERN,
    MONTHS_TO_NUM,
    SKIP_KEYWORDS,
    WorkbookParser,
    parse_meeting_workbook,
)

# =================================================================
#  ФИКСТУРЫ
# =================================================================


@pytest.fixture
def parser():
    """Создать парсер с тестовым путём."""
    return WorkbookParser("/path/to/test.epub")


@pytest.fixture
def sample_html_week():
    """HTML одной недели из EPUB."""
    return """
    <html>
    <head><title>4-10 марта 2024</title></head>
    <body>
    <h1>4-10 марта 2024</h1>
    <h2>Сокровища из Слова Бога</h2>
    <h3>1. Сокровища из Слова Бога (10 мин.)</h3>
    <h3>2. Ищем духовные жемчужины (8 мин.)</h3>
    <h3>3. Чтение Библии (4 мин.)</h3>
    <h2>Оттачиваем навыки служения</h2>
    <h3>4. Первое посещение (2 мин.)</h3>
    <h3>5. Повторное посещение (4 мин.)</h3>
    <h3>6. Изучение Библии (6 мин.)</h3>
    <h2>Христианская жизнь</h2>
    <p><strong>Песня 23</strong></p>
    <h3>7. Речь (15 мин.)</h3>
    <h3>Изучение Библии в собрании (30 мин.)</h3>
    <p><strong>Песня 45</strong></p>
    </body>
    </html>
    """


@pytest.fixture
def sample_soup(sample_html_week):
    """Create BeautifulSoup from HTML sample."""
    return BeautifulSoup(sample_html_week, "html.parser")


# =================================================================
#  ТЕСТЫ КОНСТАНТ
# =================================================================


class TestConstants:
    """Тесты констант модуля."""

    def test_months_pattern_contains_all_months(self):
        """Паттерн содержит все месяцы."""
        for month in MONTHS_TO_NUM.keys():
            assert month in MONTHS_PATTERN

    def test_months_to_num_has_12_months(self):
        """Словарь месяцев содержит 12 записей."""
        assert len(MONTHS_TO_NUM) == 12

    def test_skip_keywords_contains_required(self):
        """SKIP_KEYWORDS содержит нужные слова."""
        assert "песня" in SKIP_KEYWORDS
        assert "псалом" in SKIP_KEYWORDS

    def test_months_to_num_values(self):
        """Значения месяцев корректны."""
        assert MONTHS_TO_NUM["ЯНВАРЯ"] == 1
        assert MONTHS_TO_NUM["ДЕКАБРЯ"] == 12
        assert MONTHS_TO_NUM["МАРТА"] == 3


# =================================================================
#  ТЕСТЫ ИНИЦИАЛИЗАЦИИ
# =================================================================


class TestWorkbookParserInit:
    """Тесты инициализации WorkbookParser."""

    def test_init_stores_path(self, parser):
        """Путь сохраняется в атрибуте."""
        assert parser.epub_path == "/path/to/test.epub"

    def test_init_empty_weeks(self, parser):
        """Список недель пуст при инициализации."""
        assert parser.weeks == []


# =================================================================
#  ТЕСТЫ _try_parse_week
# =================================================================


class TestTryParseWeek:
    """Тесты парсинга недели из HTML."""

    def test_parse_valid_week(self, parser, sample_soup):
        """Парсинг валидной недели."""
        result = parser._try_parse_week(sample_soup)

        assert result is not None
        # week_title парсит только дату без года
        assert "4-10" in result["week_title"]
        assert "марта" in result["week_title"].lower()
        assert result["start_day"] == 4
        assert result["end_day"] == 10
        assert result["month"] == "МАРТА"
        assert result["month_num"] == 3

    def test_parse_year_boundary_week_with_years(self, parser):
        """Неделя на стыке лет пишется с годами — раньше она выпадала из импорта."""
        html = (
            "<html><head><title>28 ДЕКАБРЯ 2026 года — 3 ЯНВАРЯ 2027 года</title></head>"
            "<body><h1>28 ДЕКАБРЯ 2026 года — 3 ЯНВАРЯ 2027 года</h1></body></html>"
        )
        result = parser._try_parse_week(BeautifulSoup(html, "html.parser"))

        assert result is not None
        assert result["week_title"] == "28 ДЕКАБРЯ — 3 ЯНВАРЯ"
        assert (result["start_day"], result["start_month_num"], result["start_year"]) == (
            28,
            12,
            2026,
        )
        assert result["month_num"] == 12  # большинство дней недели — в декабре

    def test_parse_week_with_different_dash(self, parser):
        """Парсинг недели с другим типом тире."""
        html = "<html><head><title>4—10 марта 2024</title></head></html>"
        soup = BeautifulSoup(html, "html.parser")

        result = parser._try_parse_week(soup)

        assert result is not None
        assert result["start_day"] == 4
        assert result["end_day"] == 10

    def test_parse_week_from_h1(self, parser):
        """Парсинг недели из H1 если нет в title."""
        html = "<html><body><h1>11-17 апреля 2024</h1></body></html>"
        soup = BeautifulSoup(html, "html.parser")

        result = parser._try_parse_week(soup)

        assert result is not None
        assert result["month"] == "АПРЕЛЯ"

    def test_parse_invalid_week(self, parser):
        """Парсинг невалидной недели возвращает None."""
        html = "<html><head><title>Some random text</title></head></html>"
        soup = BeautifulSoup(html, "html.parser")

        result = parser._try_parse_week(soup)

        assert result is None

    def test_parse_week_structure(self, parser, sample_soup):
        """Структура возвращаемого словаря корректна."""
        result = parser._try_parse_week(sample_soup)

        assert "week_title" in result
        assert "start_day" in result
        assert "end_day" in result
        assert "month" in result
        assert "month_num" in result
        assert "assignments" in result
        assert "songs" in result
        assert "bible_reading" in result


# =================================================================
#  ТЕСТЫ _get_songs
# =================================================================


class TestGetSongs:
    """Тесты извлечения песен."""

    def test_get_songs_basic(self, parser):
        """Извлечение песен из HTML."""
        html = "<html><strong>Песня 23</strong><strong>Песня 45</strong></html>"
        soup = BeautifulSoup(html, "html.parser")

        songs = parser._get_songs(soup)

        assert "23" in songs
        assert "45" in songs

    def test_get_songs_from_anchor(self, parser):
        """Извлечение песен из тега <a>."""
        html = "<html><a>Песня 67</a></html>"
        soup = BeautifulSoup(html, "html.parser")

        songs = parser._get_songs(soup)

        assert "67" in songs

    def test_get_songs_no_duplicates(self, parser):
        """Дубликаты песен не добавляются."""
        html = "<html><strong>Песня 23</strong><strong>Песня 23</strong></html>"
        soup = BeautifulSoup(html, "html.parser")

        songs = parser._get_songs(soup)

        assert songs.count("23") == 1

    def test_get_songs_empty(self, parser):
        """Пустой список если песен нет."""
        html = "<html><p>No songs here</p></html>"
        soup = BeautifulSoup(html, "html.parser")

        songs = parser._get_songs(soup)

        assert songs == []


# =================================================================
#  ТЕСТЫ _get_bible_reading
# =================================================================


class TestGetBibleReading:
    """Тесты извлечения чтения Библии."""

    def test_get_bible_reading_found(self, parser):
        """Извлечение чтения Библии из H2."""
        html = "<html><h2>Матфея 5-7</h2></html>"
        soup = BeautifulSoup(html, "html.parser")

        result = parser._get_bible_reading(soup)

        assert result == "Матфея 5-7"

    def test_get_bible_reading_not_found(self, parser):
        """Дефолтное значение если не найдено."""
        html = "<html><h2>Some other text</h2></html>"
        soup = BeautifulSoup(html, "html.parser")

        result = parser._get_bible_reading(soup)

        assert result == "Чтение Библии"

    def test_get_bible_reading_multiple_h2(self, parser):
        """Берётся первый подходящий H2."""
        html = "<html><h2>First</h2><h2>Псалмы 1-5</h2></html>"
        soup = BeautifulSoup(html, "html.parser")

        result = parser._get_bible_reading(soup)

        assert "Псалмы" in result


# =================================================================
#  ТЕСТЫ _find_duration
# =================================================================


class TestFindDuration:
    """Тесты поиска длительности."""

    def test_find_duration_in_h3(self, parser):
        """Длительность в тексте H3."""
        html = "<h3>1. Тема (5 мин.)</h3>"
        soup = BeautifulSoup(html, "html.parser")
        tag = soup.find("h3")

        result = parser._find_duration(tag, "1. Тема (5 мин.)")

        assert result == 5

    def test_find_duration_various_formats(self, parser):
        """Разные форматы длительности."""
        test_cases = [
            ("(10 мин.)", 10),
            ("(15 мин)", 15),
            ("(2мин.)", 2),
        ]
        for text, expected in test_cases:
            html = f"<h3>{text}</h3>"
            soup = BeautifulSoup(html, "html.parser")
            tag = soup.find("h3")
            result = parser._find_duration(tag, text)
            assert result == expected

    def test_find_duration_not_found(self, parser):
        """None если длительность не найдена."""
        html = "<h3>1. Тема без длительности</h3>"
        soup = BeautifulSoup(html, "html.parser")
        tag = soup.find("h3")

        result = parser._find_duration(tag, "1. Тема без длительности")

        assert result is None


# =================================================================
#  ТЕСТЫ _determine_type
# =================================================================


class TestDetermineType:
    """Тесты определения типа задания."""

    def test_treasures_section(self, parser):
        """Типы в секции treasures."""
        assert parser._determine_type("treasures", "Сокровища из Слова Бога") == "treasures"
        assert parser._determine_type("treasures", "Ищем духовные жемчужины") == "gems"
        assert parser._determine_type("treasures", "Чтение Библии") == "reading"

    def test_ministry_section(self, parser):
        """Типы в секции ministry."""
        assert parser._determine_type("ministry", "Первое посещение") == "student"
        assert parser._determine_type("ministry", "Речь") == "teaching"
        assert parser._determine_type("ministry", "Доклад") == "teaching"

    def test_living_section(self, parser):
        """Типы в секции living."""
        assert parser._determine_type("living", "Речь") == "living"
        assert parser._determine_type("living", "Изучение Библии в собрании") == "cbs"

    def test_living_section_not_cbs(self, parser):
        """
        Заголовки с словом 'изучение', которые НЕ являются CBS.

        Regression test для бага, когда 'Проводите личное изучение Библии...'
        ошибочно классифицировалось как CBS из-за частичного совпадения.
        """
        # Эти заголовки содержат 'изучение', но НЕ являются CBS
        assert (
            parser._determine_type(
                "living", "Проводите личное изучение Библии, несмотря на препятствия"
            )
            == "living"
        )
        assert parser._determine_type("living", "Личное изучение Библии") == "living"
        assert parser._determine_type("living", "Как проводить личное изучение") == "living"
        # Только точная фраза "изучение библии в собрании" — это CBS
        assert parser._determine_type("living", "Изучение Библии в собрании") == "cbs"

    def test_unknown_section(self, parser):
        """Fallback для неизвестной секции."""
        assert parser._determine_type("unknown", "Any text") == "student"


# =================================================================
#  ТЕСТЫ _get_assignments
# =================================================================


class TestGetAssignments:
    """Тесты извлечения заданий."""

    def test_get_assignments_basic(self, parser, sample_soup):
        """Извлечение заданий из HTML."""
        with patch("core.validation_service.ValidationService") as mock_vs:
            mock_vs.identify_section.side_effect = lambda x: {
                "Сокровища из Слова Бога": "treasures",
                "Оттачиваем навыки служения": "ministry",
                "Христианская жизнь": "living",
            }.get(x)
            mock_vs.is_valid_assignment.return_value = True

            assignments = parser._get_assignments(sample_soup)

        assert len(assignments) > 0

    def test_get_assignments_skip_songs(self, parser):
        """Песни пропускаются в заданиях."""
        html = """
        <html>
        <h2>Сокровища из Слова Бога</h2>
        <h3>Песня 23</h3>
        <h3>1. Тема (5 мин.)</h3>
        </html>
        """
        soup = BeautifulSoup(html, "html.parser")

        with patch("core.validation_service.ValidationService") as mock_vs:
            mock_vs.identify_section.return_value = "treasures"
            mock_vs.is_valid_assignment.return_value = True

            assignments = parser._get_assignments(soup)

        # Песня не должна быть в заданиях
        titles = [a["text"] for a in assignments]
        assert "Песня 23" not in titles

    def test_get_assignments_structure(self, parser, sample_soup):
        """Структура заданий корректна."""
        with patch("core.validation_service.ValidationService") as mock_vs:
            mock_vs.identify_section.side_effect = lambda x: {
                "Сокровища из Слова Бога": "treasures",
                "Оттачиваем навыки служения": "ministry",
                "Христианская жизнь": "living",
            }.get(x)
            mock_vs.is_valid_assignment.return_value = True

            assignments = parser._get_assignments(sample_soup)

        for a in assignments:
            assert "number" in a
            assert "text" in a
            assert "type" in a
            assert "duration" in a
            assert "section" in a
            assert "section_position" in a


# =================================================================
#  ТЕСТЫ parse
# =================================================================


class TestParse:
    """Тесты основного метода parse."""

    @patch("core.epub_parser.iter_epub_documents")
    def test_parse_success(self, mock_iter, parser, sample_html_week):
        """Успешный парсинг EPUB."""
        mock_iter.return_value = [("chapter1.xhtml", sample_html_week.encode("utf-8"))]

        with patch("core.validation_service.ValidationService") as mock_vs:
            mock_vs.identify_section.side_effect = lambda x: {
                "Сокровища из Слова Бога": "treasures",
                "Оттачиваем навыки служения": "ministry",
                "Христианская жизнь": "living",
            }.get(x)
            mock_vs.is_valid_assignment.return_value = True

            result = parser.parse()

        assert len(result) == 1
        assert "4-10" in result[0]["week_title"]

    @patch("core.epub_parser.iter_epub_documents")
    def test_parse_skip_toc(self, mock_iter, parser):
        """TOC и NAV файлы пропускаются."""
        mock_iter.return_value = [("toc.xhtml", b"<html><body></body></html>")]

        result = parser.parse()

        assert result == []

    @patch("core.epub_parser.iter_epub_documents")
    def test_parse_error_handling(self, mock_iter, parser):
        """Обработка ошибок при парсинге."""
        mock_iter.side_effect = Exception("EPUB error")

        result = parser.parse()

        assert result == []


# =================================================================
#  ТЕСТЫ parse_meeting_workbook
# =================================================================


class TestParseMeetingWorkbook:
    """Тесты утилитарной функции parse_meeting_workbook."""

    @patch("core.epub_parser.WorkbookParser")
    def test_parse_meeting_workbook_success(self, mock_parser_class, tmp_path):
        """Успешный парсинг и сохранение JSON."""
        # Создаём временный EPUB файл
        epub_path = str(tmp_path / "test.epub")

        # Мок парсера
        mock_parser = MagicMock()
        mock_parser.parse.return_value = [{"week_title": "Test Week"}]
        mock_parser_class.return_value = mock_parser

        result = parse_meeting_workbook(epub_path)

        # Проверяем что JSON создан
        assert result is not None
        assert result.endswith(".json")

        # Проверяем содержимое JSON
        with open(result, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert "weeks" in data
        assert len(data["weeks"]) == 1

    @patch("core.epub_parser.WorkbookParser")
    def test_parse_meeting_workbook_empty(self, mock_parser_class, tmp_path):
        """Возврат None если недель нет."""
        epub_path = str(tmp_path / "test.epub")

        mock_parser = MagicMock()
        mock_parser.parse.return_value = []
        mock_parser_class.return_value = mock_parser

        result = parse_meeting_workbook(epub_path)

        assert result is None


# =================================================================
#  ИНТЕГРАЦИОННЫЕ ТЕСТЫ
# =================================================================


class TestIntegration:
    """Интеграционные тесты с реальным BeautifulSoup."""

    def test_full_week_parsing(self, parser):
        """Полный цикл парсинга одной недели."""
        html = """
        <html>
        <head><title>4-10 марта 2024</title></head>
        <body>
        <h1>4-10 марта 2024</h1>
        <h2>Сокровища из Слова Бога</h2>
        <h3>1. Сокровища из Слова Бога (10 мин.)</h3>
        <h3>2. Ищем духовные жемчужины (8 мин.)</h3>
        <h3>3. Чтение Библии (4 мин.)</h3>
        <h2>Оттачиваем навыки служения</h2>
        <h3>4. Первое посещение (2 мин.)</h3>
        <h3>5. Повторное посещение (4 мин.)</h3>
        <h3>6. Изучение Библии (6 мин.)</h3>
        <h2>Христианская жизнь</h2>
        <p><strong>Песня 23</strong></p>
        <h3>7. Речь (15 мин.)</h3>
        <h3>Изучение Библии в собрании (30 мин.)</h3>
        <p><strong>Песня 45</strong></p>
        <p><strong>Песня 67</strong></p>
        </body>
        </html>
        """
        soup = BeautifulSoup(html, "html.parser")

        with patch("core.validation_service.ValidationService") as mock_vs:
            mock_vs.identify_section.side_effect = lambda x: {
                "Сокровища из Слова Бога": "treasures",
                "Оттачиваем навыки служения": "ministry",
                "Христианская жизнь": "living",
            }.get(x)
            mock_vs.is_valid_assignment.return_value = True

            result = parser._try_parse_week(soup)

        assert result is not None
        assert "4-10" in result["week_title"]
        assert result["month_num"] == 3
        assert "23" in result["songs"]
        assert "45" in result["songs"]
        assert "67" in result["songs"]
        assert len(result["assignments"]) > 0

    def test_multiple_weeks_different_months(self, parser):
        """Парсинг недель из разных месяцев."""
        test_cases = [
            ("1-7 января 2024", "ЯНВАРЯ", 1, 1),
            ("15-21 февраля 2024", "ФЕВРАЛЯ", 2, 2),
            ("28 февраля-6 марта 2024", "МАРТА", 3, 2),  # переход месяца
        ]

        for title, expected_month, expected_num, expected_start_num in test_cases:
            html = f"<html><head><title>{title}</title></head></html>"
            soup = BeautifulSoup(html, "html.parser")

            result = parser._try_parse_week(soup)

            assert result is not None
            assert result["month"] == expected_month
            assert result["month_num"] == expected_num
            assert result["start_month_num"] == expected_start_num
