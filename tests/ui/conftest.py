"""
UI tests configuration and fixtures.

См. spec://testing/ui#fixtures
"""

import os
import sys
import tempfile
from unittest.mock import Mock, MagicMock

# Добавляем корень проекта в sys.path для импорта ui модулей
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    """
    Создаёт QApplication для всех UI-тестов.

    Использует QT_QPA_PLATFORM=offscreen для работы без GUI.
    Это позволяет запускать тесты в CI без X11.
    """
    # Устанавливаем offscreen platform для headless тестов
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app
    # Само приложение не удаляем, но оставшиеся окна тестов (созданные без
    # родителя) удаляем сейчас: иначе PySide6 при выходе уничтожает
    # QApplication, обходит их обёртки и падает на уже удалённых виджетах.
    import gc

    from PySide6.QtCore import QCoreApplication, QEvent

    for w in app.topLevelWidgets():
        w.close()
        w.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    gc.collect()


@pytest.fixture
def temp_db():
    """
    Создаёт временную in-memory БД для тестов.

    In-memory SQLite быстрее и изолированнее файловой БД.
    Используется для интеграционных тестов UI ↔ Facade ↔ DB.
    """
    # Для in-memory БД используем :memory:
    yield ":memory:"


@pytest.fixture
def container(temp_db):
    """
    Контейнер с временной in-memory БД.

    Создаёт полноценный DI-контейнер с реальными сервисами,
    но на временной БД. После теста БД уничтожается.
    """
    from core.settings import Settings
    from core.container import Container

    # Сохраняем оригинальный метод load
    original_load = Settings.load

    # Подменяем на тестовую конфигурацию
    def mock_load():
        settings = Settings()
        settings.db_path = temp_db
        return settings

    Settings.load = staticmethod(mock_load)

    c = None
    try:
        c = Container()
        yield c
    finally:
        # Закрываем соединения с БД если есть
        if c is not None and hasattr(c, "db_manager") and c.db_manager:
            try:
                # Попытка закрыть все соединения
                if hasattr(c.db_manager, "close"):
                    c.db_manager.close()
                elif hasattr(c.db_manager, "engine"):
                    c.db_manager.engine.dispose()
            except Exception:
                pass
        # Восстанавливаем оригинальный метод
        Settings.load = original_load


@pytest.fixture
def facade(container):
    """
    Фасад из контейнера.

    Используется для интеграционных тестов UI ↔ Facade.
    """
    return container.facade


@pytest.fixture
def mock_facade():
    """
    Mock ApplicationFacade для изолированных unit-тестов UI.

    Возвращает Mock-объект с предустановленными возвращаемыми значениями
    для типичных операций с участниками.

    См. plans/ui_testing_plan.md секция 5.2
    """
    facade = Mock()

    # Данные участников по умолчанию
    participants_data = [
        {
            "id": 1,
            "name": "Иванов Иван",
            "gender": "male",
            "service_type": "elder",
            "is_active": True,
            "qualifications": ["chairman", "prayer"],
            "last_assignment_date": "2026-02-15",
            "last_assignment_date_real": "15.02.2026",
            "total_assignments": 5,
            "family_group_id": None,
        },
        {
            "id": 2,
            "name": "Петров Пётр",
            "gender": "male",
            "service_type": "ministerial_servant",
            "is_active": True,
            "qualifications": ["bible_reading"],
            "last_assignment_date": None,
            "last_assignment_date_real": "—",
            "total_assignments": 0,
            "family_group_id": 1,
        },
        {
            "id": 3,
            "name": "Сидорова Анна",
            "gender": "female",
            "service_type": "publisher",
            "is_active": True,
            "qualifications": [],
            "last_assignment_date": None,
            "last_assignment_date_real": "—",
            "total_assignments": 0,
            "family_group_id": 1,
        },
    ]

    facade.get_all_participants.return_value = participants_data
    # Алиас для совместимости с HistoryView
    facade.get_participants_list.return_value = participants_data

    # Данные конкретного участника
    facade.get_participant.return_value = {
        "id": 1,
        "name": "Иванов Иван",
        "gender": "male",
        "service_type": "elder",
        "is_active": True,
        "qualifications": ["chairman", "prayer"],
        "last_assignment_date": "2026-02-15",
        "last_assignment_date_real": "15.02.2026",
        "total_assignments": 5,
        "family_group_id": None,
    }

    # Методы добавления/обновления/удаления
    facade.add_participant.return_value = 1  # Возвращает ID нового участника
    facade.update_participant.return_value = True
    facade.delete_participant.return_value = True

    # История назначений (пустой список по умолчанию)
    facade.get_participant_history.return_value = []

    return facade


@pytest.fixture
def mock_worker():
    """
    Mock TaskWorker для тестов асинхронных операций.

    Используется в тестах schedule_view.py и workbook_view.py,
    где есть фоновые операции через QThread.
    """
    worker = MagicMock()
    worker.start = MagicMock()
    worker.isRunning = MagicMock(return_value=False)
    worker.quit = MagicMock()
    worker.wait = MagicMock()
    return worker
