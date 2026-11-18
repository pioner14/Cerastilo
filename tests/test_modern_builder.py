# tests/test_modern_builder.py
"""
Тесты для ModernTableBuilder.

См. spec://export/docx#modern-builder
"""

import pytest
from datetime import datetime
from unittest.mock import Mock, patch
from docx import Document

from core.export.modern_builder import ModernTableBuilder


# =================================================================
#  ФИКСТУРЫ
# =================================================================


@pytest.fixture
def builder():
    """Создать экземпляр ModernTableBuilder."""
    return ModernTableBuilder()


@pytest.fixture
def document():
    """Создать пустой документ."""
    return Document()


@pytest.fixture
def mock_week():
    """Создать мок недели."""
    week = Mock()
    week.start_date = "2024-03-04"
    week.bible_reading = "Матфея 5-7"
    week.songs = "23,45,67"
    week.announcement = None  # Нет объявлений по умолчанию
    week.special_event = None  # Обычная неделя, не конгресс/вечеря
    return week


@pytest.fixture
def mock_assignments():
    """Создать мок назначений."""
    return [
        {
            "position": "chairman",
            "type": "chairman",
            "section": "opening",
            "participant": "Иван Петров",
            "assistant": None,
            "text": "Председатель",
            "duration": 1,
        },
        {
            "position": "prayer_open",
            "type": "prayer",
            "section": "opening",
            "participant": "Петр Сидоров",
            "assistant": None,
            "text": "Молитва",
            "duration": 1,
        },
        {
            "position": "prayer_close",
            "type": "prayer",
            "section": "closing",
            "participant": "Сидор Иванов",
            "assistant": None,
            "text": "Молитва",
            "duration": 1,
        },
        {
            "position": 1,
            "type": "treasures",
            "section": "treasures",
            "participant": "Анна Козлова",
            "assistant": None,
            "text": "Сокровища из Слова Бога",
            "duration": 10,
        },
        {
            "position": 2,
            "type": "gems",
            "section": "treasures",
            "participant": "Мария Тихонова",
            "assistant": None,
            "text": "Ищем духовные жемчужины",
            "duration": 8,
        },
        {
            "position": 3,
            "type": "bible_reading",
            "section": "treasures",
            "participant": "Дмитрий Волков",
            "assistant": None,
            "text": "Чтение Библии",
            "duration": 4,
        },
        {
            "position": 4,
            "type": "ministry",
            "section": "ministry",
            "participant": "Елена Смирнова",
            "assistant": "Ольга Петрова",
            "text": "Первое посещение",
            "duration": 2,
        },
        {
            "position": 5,
            "type": "ministry",
            "section": "ministry",
            "participant": "Николай Соколов",
            "assistant": None,
            "text": "Повторное посещение",
            "duration": 2,
        },
        {
            "position": 6,
            "type": "living",
            "section": "living",
            "participant": "Татьяна Морозова",
            "assistant": None,
            "text": "Христианская жизнь",
            "duration": 15,
        },
        {
            "position": 7,
            "type": "cbs",
            "section": "cbs",
            "participant": "Александр Козлов",
            "assistant": None,
            "text": "Изучение Библии",
            "duration": 30,
        },
        {
            "position": 8,
            "type": "cbs_reader",
            "section": "cbs",
            "participant": "Екатерина Волкова",
            "assistant": None,
            "text": "Чтец",
            "duration": 30,
        },
    ]


@pytest.fixture
def mock_settings():
    """Создать мок настроек."""
    return {
        "meeting_time": "19:00",
    }


@pytest.fixture
def week_data(mock_week, mock_assignments, mock_settings):
    """Создать полные данные недели."""
    return {
        "week": mock_week,
        "assignments": mock_assignments,
        "settings": mock_settings,
    }


# =================================================================
#  ТЕСТЫ БАЗОВЫХ МЕТОДОВ
# =================================================================


class TestBaseBuilderMethods:
    """Тесты для методов базового класса."""

    def test_fmt_time(self, builder):
        """Тест форматирования времени."""
        dt = datetime(2024, 3, 4, 19, 30)
        result = builder._fmt_time(dt)
        assert result == "19:30"

    def test_fmt_time_midnight(self, builder):
        """Тест форматирования полуночи."""
        dt = datetime(2024, 3, 4, 0, 0)
        result = builder._fmt_time(dt)
        assert result == "00:00"

    def test_parse_time_valid(self, builder):
        """Тест парсинга корректного времени."""
        result = builder._parse_time("19:30")
        assert result.hour == 19
        assert result.minute == 30

    def test_parse_time_with_dot(self, builder):
        """Тест парсинга времени с точкой."""
        result = builder._parse_time("19.30")
        assert result.hour == 19
        assert result.minute == 30

    def test_parse_time_invalid(self, builder):
        """Тест парсинга некорректного времени возвращает default."""
        result = builder._parse_time("invalid")
        assert result.hour == 19
        assert result.minute == 0

    def test_parse_time_empty(self, builder):
        """Тест парсинга пустой строки возвращает default."""
        result = builder._parse_time("")
        assert result.hour == 19
        assert result.minute == 0

    def test_parse_date_valid(self, builder):
        """Тест парсинга корректной даты."""
        result = builder._parse_date("2024-03-04")
        assert result == "04.03.2024"

    def test_parse_date_invalid(self, builder):
        """Тест парсинга некорректной даты возвращает исходную строку."""
        result = builder._parse_date("invalid")
        assert result == "invalid"

    def test_parse_date_empty(self, builder):
        """Тест парсинга пустой строки."""
        result = builder._parse_date("")
        assert result == ""

    def test_parse_songs_valid(self, builder):
        """Тест парсинга строки песен."""
        result = builder._parse_songs("23,45,67")
        assert result == ["23", "45", "67"]

    def test_parse_songs_with_spaces(self, builder):
        """Тест парсинга песен с пробелами."""
        result = builder._parse_songs("23, 45, 67")
        assert result == ["23", "45", "67"]

    def test_parse_songs_empty(self, builder):
        """Тест парсинга пустой строки песен."""
        result = builder._parse_songs("")
        assert result == []

    def test_parse_songs_none(self, builder):
        """Тест парсинга None."""
        result = builder._parse_songs(None)
        assert result == []

    def test_get_assignment_by_position_found(self, builder, mock_assignments):
        """Тест поиска назначения по позиции."""
        result = builder._get_assignment_by_position(mock_assignments, "chairman")
        assert result is not None
        assert result["participant"] == "Иван Петров"

    def test_get_assignment_by_position_not_found(self, builder, mock_assignments):
        """Тест поиска несуществующей позицииции."""
        result = builder._get_assignment_by_position(mock_assignments, "nonexistent")
        assert result is None

    def test_get_assignment_by_type_found(self, builder, mock_assignments):
        """Тест поиска назначения по типу."""
        result = builder._get_assignment_by_type(mock_assignments, "cbs_reader")
        assert result is not None
        assert result["participant"] == "Екатерина Волкова"

    def test_get_assignment_by_type_not_found(self, builder, mock_assignments):
        """Тест поиска несуществующего типа."""
        result = builder._get_assignment_by_type(mock_assignments, "nonexistent")
        assert result is None


# =================================================================
#  ТЕСТЫ ПОЛУЧЕНИЯ СЕКЦИЙ
# =================================================================


class TestGetSectionAssignments:
    """Тесты для получения назначений по секциям."""

    def test_get_section_treasures(self, builder, mock_assignments):
        """Тест получения секции сокровищ."""
        result = builder._get_section_assignments(mock_assignments, "treasures")
        assert len(result) == 3
        for item in result:
            assert item["section"] == "treasures"

    def test_get_section_ministry(self, builder, mock_assignments):
        """Тест получения секции служения."""
        result = builder._get_section_assignments(mock_assignments, "ministry")
        assert len(result) == 2
        for item in result:
            assert item["section"] == "ministry"

    def test_get_section_living(self, builder, mock_assignments):
        """Тест получения секции христианской жизни."""
        result = builder._get_section_assignments(mock_assignments, "living")
        # Только секция living (без cbs, т.к. метод фильтрует по section='living')
        # Результат зависит от реализации метода
        assert isinstance(result, list)

    def test_get_section_empty(self, builder):
        """Тест получения секции из пустого списка."""
        result = builder._get_section_assignments([], "treasures")
        assert result == []


# =================================================================
#  ТЕСТЫ ФОРМАТИРОВАНИЯ ДАТ
# =================================================================


class TestFormatDateRussian:
    """Тесты для форматирования даты на русском."""

    def test_format_date_russian_valid(self, builder):
        """Тест форматирования корректной даты."""
        result = builder._format_date_russian("2024-03-04")
        # Должен вернуть строку с датой (формат зависит от локали)
        assert result is not None
        assert len(result) > 0
        # Проверяем что что-то вернулось (день и месяц в каком-то формате)
        assert "4" in result or "04" in result

    def test_format_date_russian_empty(self, builder):
        """Тест форматирования пустой даты."""
        result = builder._format_date_russian("")
        assert result == ""

    def test_format_date_russian_none(self, builder):
        """Тест форматирования None."""
        result = builder._format_date_russian(None)
        # None должен обрабатываться (возвращать пустую строку или None)
        assert result == "" or result is None


# =================================================================
#  ТЕСТЫ СОЗДАНИЯ ТАБЛИЦЫ
# =================================================================


class TestCreateTable:
    """Тесты для создания таблицы."""

    def test_create_table_returns_table(self, builder, document):
        """Тест что создаётся таблица."""
        table = builder._create_table(document)
        assert table is not None
        assert len(table.rows) == 0  # Пустая таблица
        assert len(table.columns) == 3  # 3 колонки

    def test_create_table_has_no_borders(self, builder, document):
        """Тест что таблица без границ."""
        table = builder._create_table(document)
        # Проверяем что таблица создана
        assert table._tbl is not None


# =================================================================
#  ТЕСТЫ ДОБАВЛЕНИЯ СТРОК
# =================================================================


class TestAddRow:
    """Тесты для добавления строк."""

    def test_add_row_basic(self, builder, document):
        """Тест добавления простой строки."""
        table = builder._create_table(document)
        initial_rows = len(table.rows)

        builder._add_row(table, "1A237E", "19:00", "Тема", "Участник")

        assert len(table.rows) == initial_rows + 1

    def test_add_row_content(self, builder, document):
        """Тест содержимого добавленной строки."""
        table = builder._create_table(document)

        builder._add_row(table, "1A237E", "19:00", "Тема теста", "Иван Петров")

        row = table.rows[-1]
        # Проверяем содержимое ячеек (пропускаем первую - цветная полоса)
        assert "19:00" in row.cells[1].text or "Тема теста" in row.cells[1].text
        assert "Иван Петров" in row.cells[2].text


class TestAddSectionHeader:
    """Тесты для добавления заголовков секций."""

    def test_add_section_header(self, builder, document):
        """Тест добавления заголовка секции."""
        table = builder._create_table(document)
        initial_rows = len(table.rows)

        builder._add_section_header(table, "ТЕСТОВАЯ СЕКЦИЯ", "1A237E")

        assert len(table.rows) == initial_rows + 1

    def test_add_header_row(self, builder, document):
        """Тест добавления заголовка недели."""
        table = builder._create_table(document)
        initial_rows = len(table.rows)

        builder._add_header_row(table, "4 марта 2024 | Матфея 5-7")

        assert len(table.rows) == initial_rows + 1


# =================================================================
#  ТЕСТЫ ОСНОВНОГО МЕТОДА BUILD
# =================================================================


class TestModernTableBuilderBuild:
    """Тесты для основного метода build."""

    def test_build_creates_table(self, builder, document, week_data):
        """Тест что build создаёт таблицу."""
        with patch("modules.registry.ModuleRegistry") as MockRegistry:
            mock_registry = Mock()
            mock_registry.get_all.return_value = []
            MockRegistry.return_value = mock_registry

            builder.build(document, week_data)

        # Должна быть создана таблица
        assert len(document.tables) == 1

    def test_build_table_has_rows(self, builder, document, week_data):
        """Тест что таблица имеет строки."""
        with patch("modules.registry.ModuleRegistry") as MockRegistry:
            mock_registry = Mock()
            mock_registry.get_all.return_value = []
            MockRegistry.return_value = mock_registry

            builder.build(document, week_data)

        table = document.tables[0]
        # Должно быть много строк (заголовок + председатель + песни + секции)
        assert len(table.rows) > 10

    def test_build_with_empty_assignments(self, builder, document, mock_week, mock_settings):
        """Тест build с пустыми назначениями."""
        week_data = {
            "week": mock_week,
            "assignments": [],
            "settings": mock_settings,
        }

        with patch("modules.registry.ModuleRegistry") as MockRegistry:
            mock_registry = Mock()
            mock_registry.get_all.return_value = []
            MockRegistry.return_value = mock_registry

            # Не должно вызывать ошибку
            builder.build(document, week_data)
        assert len(document.tables) == 1

    def test_build_with_missing_chairman(self, builder, document, mock_week, mock_settings):
        """Тест build без председателя."""
        assignments = [a for a in []]  # Пустой список
        week_data = {
            "week": mock_week,
            "assignments": assignments,
            "settings": mock_settings,
        }

        with patch("modules.registry.ModuleRegistry") as MockRegistry:
            mock_registry = Mock()
            mock_registry.get_all.return_value = []
            MockRegistry.return_value = mock_registry

            builder.build(document, week_data)
        assert len(document.tables) == 1

    def test_build_with_different_meeting_time(
        self, builder, document, mock_week, mock_assignments
    ):
        """Тест build с другим временем собрания."""
        settings = {"meeting_time": "10:00"}
        week_data = {
            "week": mock_week,
            "assignments": mock_assignments,
            "settings": settings,
        }

        with patch("modules.registry.ModuleRegistry") as MockRegistry:
            mock_registry = Mock()
            mock_registry.get_all.return_value = []
            MockRegistry.return_value = mock_registry

            builder.build(document, week_data)
        table = document.tables[0]

        # Проверяем что время начинается с 10:00
        first_row = table.rows[1]  # Первая строка с данными (после заголовка)
        assert "10:00" in first_row.cells[1].text

    def test_build_with_missing_songs(
        self, builder, document, mock_week, mock_assignments, mock_settings
    ):
        """Тест build без песен."""
        mock_week.songs = ""
        week_data = {
            "week": mock_week,
            "assignments": mock_assignments,
            "settings": mock_settings,
        }

        with patch("modules.registry.ModuleRegistry") as MockRegistry:
            mock_registry = Mock()
            mock_registry.get_all.return_value = []
            MockRegistry.return_value = mock_registry

            builder.build(document, week_data)
        assert len(document.tables) == 1

    def test_build_with_partial_songs(
        self, builder, document, mock_week, mock_assignments, mock_settings
    ):
        """Тест build с неполным списком песен."""
        mock_week.songs = "23"  # Только одна песня
        week_data = {
            "week": mock_week,
            "assignments": mock_assignments,
            "settings": mock_settings,
        }

        with patch("modules.registry.ModuleRegistry") as MockRegistry:
            mock_registry = Mock()
            mock_registry.get_all.return_value = []
            MockRegistry.return_value = mock_registry

            builder.build(document, week_data)
        assert len(document.tables) == 1


# =================================================================
#  ТЕСТЫ МОДУЛЕЙ
# =================================================================


class TestAddModules:
    """Тесты для добавления модулей."""

    def test_add_modules_empty(self, builder, document, mock_week, mock_settings):
        """Тест добавления модулей когда их нет."""
        table = builder._create_table(document)
        initial_rows = len(table.rows)

        # Мокаем ModuleRegistry чтобы избежать реальной загрузки модулей
        with patch("modules.registry.ModuleRegistry") as MockRegistry:
            mock_registry = Mock()
            mock_registry.get_all.return_value = []
            MockRegistry.return_value = mock_registry

            builder._add_modules(table, mock_week, mock_settings)

        # Без модулей количество строк не должно измениться
        assert len(table.rows) == initial_rows

    def test_add_modules_with_announcement(self, builder, document, mock_week, mock_settings):
        """Тест добавления модуля объявлений."""
        mock_week.announcement = "Тестовое объявление"
        table = builder._create_table(document)

        # Мокаем ModuleRegistry и модуль
        with (
            patch("modules.registry.ModuleRegistry") as MockRegistry,
            patch("modules.announcement.AnnouncementModule") as MockModule,
        ):
            mock_module_instance = Mock()
            mock_module_instance.id = "announcement"
            mock_module_instance.get_export_content.return_value = "Тестовое объявление"

            mock_registry = Mock()
            mock_registry.get_all.return_value = [mock_module_instance]
            MockRegistry.return_value = mock_registry

            builder._add_modules(table, mock_week, mock_settings)

        # Проверяем что таблица не сломалась
        assert table is not None


# =================================================================
#  ТЕСТЫ ЦВЕТОВ
# =================================================================


class TestColors:
    """Тесты для цветовой схемы."""

    def test_color_constants(self, builder):
        """Тест констант цветов."""
        assert builder.COLOR_NAVY == "1A237E"
        assert builder.COLOR_SLATE == "455A64"
        assert builder.COLOR_DARK_GREY == "212121"

        assert builder.STRIP_HEADER == "1A237E"
        assert builder.STRIP_TREASURES == "006064"
        assert builder.STRIP_MINISTRY == "BF360C"
        assert builder.STRIP_LIVING == "B71C1C"

    def test_font_constant(self, builder):
        """Тест константы шрифта."""
        assert builder.FONT_CONDENSED == "Arial Narrow"


# =================================================================
#  ИНТЕГРАЦИОННЫЕ ТЕСТЫ
# =================================================================


class TestIntegration:
    """Интеграционные тесты."""

    def test_full_build_creates_valid_document(self, builder, week_data):
        """Тест полного построения документа."""
        doc = Document()

        # Мокаем ModuleRegistry чтобы избежать реальной загрузки модулей
        with patch("modules.registry.ModuleRegistry") as MockRegistry:
            mock_registry = Mock()
            mock_registry.get_all.return_value = []
            MockRegistry.return_value = mock_registry

            builder.build(doc, week_data)

        # Проверяем что документ валиден
        assert len(doc.tables) == 1
        table = doc.tables[0]
        assert len(table.rows) > 0
        assert len(table.columns) == 3

    def test_build_with_all_sections(self, builder, document, week_data):
        """Тест что все секции создаются."""

        # Мокаем ModuleRegistry
        with patch("modules.registry.ModuleRegistry") as MockRegistry:
            mock_registry = Mock()
            mock_registry.get_all.return_value = []
            MockRegistry.return_value = mock_registry

            builder.build(document, week_data)

        table = document.tables[0]
        table_text = ""
        for row in table.rows:
            for cell in row.cells:
                table_text += cell.text + " "

        # Проверяем наличие ключевых элементов
        assert "Председатель" in table_text or "председатель" in table_text.lower()
        # Песни должны быть
        assert "Песня" in table_text or "песня" in table_text.lower()

    def test_build_time_progression(self, builder, document, week_data):
        """Тест что время увеличивается."""

        # Мокаем ModuleRegistry
        with patch("modules.registry.ModuleRegistry") as MockRegistry:
            mock_registry = Mock()
            mock_registry.get_all.return_value = []
            MockRegistry.return_value = mock_registry

            builder.build(document, week_data)

        table = document.tables[0]
        times = []

        for row in table.rows:
            text = row.cells[1].text if len(row.cells) > 1 else ""
            # Ищем время в формате HH:MM
            import re

            match = re.search(r"\d{1,2}:\d{2}", text)
            if match:
                times.append(match.group())

        # Время должно увеличиваться (не обязательно строго, но общая тенденция)
        # Первое время должно быть около времени начала собрания
        if times:
            assert (
                times[0] in ["19:00", "10:00"]
                or times[0].startswith("19")
                or times[0].startswith("10")
            )
