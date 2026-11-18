# Архитектура Cerastilo

## 1. Обзор

Cerastilo — планировщик встреч собрания. Десктопное приложение на **PySide6** с базой **SQLite** через **SQLAlchemy** и миграциями **Alembic**. Один и тот же код (`core/`, `ui/`, `modules/`, `assets/`, `migrations/`) используется и на ПК, и на Android: APK собирается из `android/build_src/`, где десктопный `main.py` лежит под именем `app_main.py`, а `android/main.py` — точка входа.

- Точка входа десктопа: `main.py`, запускается из `.venv` через `start.sh`.
- Точка входа APK: `android/main.py`.
- Рабочая база: `scheduler.db` в корне проекта.

## 2. Слои и поток вызова

```
ui/ (виджеты PySide6)
      │  вызовы через self.facade
      ▼
фасад: core/facade.py (ApplicationFacade)
       core/base_facade.py (BaseApplicationFacade)
      │
      ▼
сервисы core/: services.py, schedule_service.py,
auto_assignment_service.py, import_service.py,
export_service.py, notification_service.py, sync_service.py
      │
      ▼
репозитории core/repositories/ → модели core/models.py
      │
      ▼
БД SQLite (SQLAlchemy, миграции Alembic)
```

Зависимости собираются в `core/container.py` (`Container`). Фасад — единая точка входа UI в логику: `BaseApplicationFacade` задаёт общий интерфейс для ПК и Android, `ApplicationFacade` добавляет поддержку модулей (`run_module_migrations`). События (в т.ч. ошибки, `Event.ERROR_OCCURRED`) идут через шину `core/events.py` (`SimpleEventBus` / `QtEventBus`).

## 3. Модули core/ и ui/

### БД и миграции
| Файл | Назначение |
|---|---|
| `core/database.py` | `DatabaseManager`: сессии, применение миграций, настройки, особые события недель |
| `core/models.py` | ORM-модели SQLAlchemy (участники, недели, задания, конфиги, уведомления, графики) |
| `core/migration.py` | Устаревшие миграции схемы и перенос участников |
| `core/android_migrations.py` | Чисто-питоновские SQL-миграции для Android без Alembic |
| `core/db_snapshot.py` | Снимок базы и откат к нему |
| `core/unit_of_work.py` | Unit of Work для транзакций |
| `core/repositories/base.py` | Базовый репозиторий с общим CRUD |
| `core/repositories/participant_repository.py` | Доступ к участникам, квалификациям, статистике |
| `core/repositories/assignment_repository.py` | Доступ к заданиям недель |
| `core/repositories/week_repository.py` | Доступ к неделям, дереву недель, особым событиям |
| `core/repositories/assignment_config_repository.py` | Конфигурация квалификаций по (section, position) |
| `migrations/001…018_*.py` | Alembic-миграции схемы (от начальной до ответов на уведомления) |

### Распределение заданий
| Файл | Назначение |
|---|---|
| `core/auto_assignment_service.py` | Автоматическое распределение участников по заданиям недели |
| `core/candidate_filter_service.py` | Фильтрация кандидатов по критериям задания |
| `core/assignment_rules.py` | Действующие правила пункта с поправкой на тип задания |
| `core/assignment_classifier.py` | Классификация заданий по разделам расписания |
| `core/validation_service.py` | Валидация заданий, разделов и номеров |

### Расписание и недели
| Файл | Назначение |
|---|---|
| `core/schedule_service.py` | Доменный сервис расписания через репозитории |
| `core/services.py` | `ParticipantService`, `ScheduleService` — операции над участниками и неделями |
| `core/schedule_preview.py` | HTML-предпросмотр расписания недели |
| `core/week_layout.py` | Порядок пунктов недели и время начала |
| `core/month_board.py` | Доска месяца: недели колонками, пункты строками |
| `core/leader_dashboard.py` | Пульт руководителя: дела и ближайшая встреча |
| `core/statistics.py` | Статистика выступлений для вкладки «Статистика» |
| `core/domain/entities.py` | Доменные сущности (Participant, Assignment, Week и др.) |
| `core/dto.py` | Неизменяемые DTO между слоями |
| `core/mappers.py` | Преобразование ORM → DTO → UI-словари |
| `core/backfill_service.py` | Синхронизация семантических полей заданий из EPUB без сброса назначений |

### Экспорт
| Файл | Назначение |
|---|---|
| `core/export_service.py` | Бизнес-логика экспорта (DOCX, S-89, TXT, PDF, предпросмотр) |
| `core/export/base_builder.py` | Базовый класс билдеров таблиц расписания |
| `core/export/compact_builder.py` | Компактный формат (2 колонки, 2 недели на страницу) |
| `core/export/compact_v2_builder.py` | Компактный современный формат v2 (3 колонки) |
| `core/export/compact_layout.py` | Строки компактного расписания без привязки к формату файла |
| `core/export/full_modern_builder.py` | Полный современный формат (Swiss Style) |
| `core/export/modern_builder.py` | Современный формат с цветными полосами |
| `core/export/configurator.py` | Настройка полей и языка DOCX |
| `core/export/fetcher.py` | Загрузка недель и настроек для экспорта |
| `core/export/qt_pdf.py` | PDF компактного расписания средствами Qt (Android) |
| `core/export_s89.py` | Экспорт карточек S-89 (2×2 на A4) |
| `core/export_schedule_docx.py` | Расписание для доски объявлений (Custom Design) |
| `core/utils/pdf_utils.py` | Конвертация DOCX → PDF через headless LibreOffice |

### Импорт
| Файл | Назначение |
|---|---|
| `core/epub_parser.py` | Парсер EPUB рабочих тетрадей (недели, задания, песни, чтение Библии) |
| `core/workbook_import.py` | Импорт распарсенных недель в БД с синхронизацией заданий |
| `core/import_service.py` | Импорт тетради и подготовка будущего года |
| `core/history_import.py` | Импорт истории назначений из CSV NW Scheduler |

### Уведомления и почта
| Файл | Назначение |
|---|---|
| `core/notification_service.py` | Отправка email-уведомлений участникам (SMTP, IMAP для ответов) |
| `core/notification_replies.py` | Разбор ответов «Подтверждаю»/«Не смогу» по метке в теме |
| `core/error_service.py` | Централизованная обработка и сообщение об ошибках |
| `core/secret_store.py` | Пароль SMTP в отдельном JSON-файле рядом с базой |
| `core/settings.py` | Настройки приложения (загрузка/сохранение в БД) |

### Синхронизация
| Файл | Назначение |
|---|---|
| `core/sync_service.py` | Слияние двух SQLite-баз, HTTP-сервер и клиент синхронизации ПК↔планшет |

### Android
| Файл | Назначение |
|---|---|
| `android/main.py` | Точка входа APK: папка данных, прокрутка касанием, запуск окна |
| `android/build_apk.sh` | Сборка APK из копии кода в `android/build_src/` |
| `core/utils/android_storage.py` | Папка экспорта на Android («Загрузки/Cerastilo») |
| `core/android_migrations.py` | Миграции без Alembic (см. выше) |

### Прочее
| Файл | Назначение |
|---|---|
| `core/config.py` | Пути к bundle/app и к базе данных |
| `core/container.py` | DI-контейнер сборки компонентов |
| `core/events.py` | Фабрика EventBus и публичный API событий |
| `core/events_base.py` | Абстрактный интерфейс EventBus |
| `core/qt_events.py` | Реализация EventBus на Qt-сигналах |
| `core/exceptions.py` | Иерархия исключений приложения |
| `core/workers.py` | `TaskWorker` и фабрика фоновых задач |
| `core/base_facade.py` | Абстрактный базовый фасад |
| `core/facade.py` | Десктопный фасад с поддержкой модулей |
| `core/backup_logic.py` | Создание/восстановление ZIP-бэкапов базы |
| `core/styles.py` | Темы QSS и палитры, определение системной темы |
| `core/utils/date_utils.py` | Утилиты работы с датами |
| `ui/schedule_view.py` | Вкладка «Расписание»: дерево недель, таблица назначений |
| `ui/month_board_view.py` | Доска месяца с кандидатами и перетаскиванием |
| `ui/leader_dashboard_view.py` | Вкладка «Сегодня» |
| `ui/participants_view.py` | Вкладка «Возвещатели» |
| `ui/participant_dialog.py` | Диалог редактирования участника |
| `ui/history_view.py` | Вкладка «История» |
| `ui/statistics_view.py` | Вкладка «Статистика» (тепловая карта и полосы нагрузки) |
| `ui/workbook_view.py` | Вкладка «Тетради»: импорт EPUB |
| `ui/settings_view.py` | Вкладка «Настройки» |
| `ui/assignment_config_view.py` | Настройка правил назначений |
| `ui/candidates.py` | Кандидаты и подсказки для пункта программы |
| `ui/export_dialog.py` | Диалог выбора недель и формата экспорта |
| `ui/notification_dialog.py` | Диалог отправки уведомлений |
| `ui/notification_log_dialog.py` | Журнал отправленных уведомлений |
| `ui/email_preview_dialog.py` | Предпросмотр и правка письма, сохранение .ics |
| `ui/sync_dialog.py` | Окна синхронизации ПК и планшета |
| `ui/file_dialogs.py` | Диалоги открытия/сохранения, совместимые с Android |
| `ui/toast.py` | Всплывающее уведомление в углу окна |
| `ui/crash_handler.py` | Журнал падений в `crash.log` |
| `ui/theme_watcher.py` | Слежение за сменой системной темы через портал |
| `ui/translations.py` | Русский перевод стандартных диалогов Qt |

## 4. Ключевые механизмы

**Авто-распределение и фильтр кандидатов.** `AutoAssignmentService` распределяет участников по заданиям недели и месяца с учётом справедливой ротации и квалификаций. `CandidateFilterService` отбирает подходящих по критериям пункта; `assignment_rules.py` уточняет правила по типу пункта (например, позиция 4 в «Оттачиваем навыки» бывает речью или ученическим заданием с напарником). `ui/candidates.py` показывает тех же кандидатов с подсказками о давности и частоте выступлений.

**Миграции.** На десктопе схему ведёт Alembic (`migrations/`), версия хранится в таблице `alembic_version`. На Android `core/android_migrations.py` выполняет SQL-миграции напрямую через stdlib `sqlite3`, обходя SIGSEGV в `alembic.command.upgrade()`, и пишет версию в ту же `alembic_version`. Базу с версией Alembic 012+ Android-менеджер не трогает.

**Синхронизация ПК↔планшет.** `SyncServer` на ПК поднимает HTTP-сервер и показывает адрес и код; клиент на планшете отправляет свою базу, `DatabaseMerger` сливает её с базой ПК и возвращает объединённую, которой планшет заменяет свою. Перед слиянием база копируется рядом.

**Экспорт PDF/DOCX.** DOCX собирают билдеры `core/export/*` поверх `BaseTableBuilder`; PDF на ПК получается конвертацией DOCX через headless LibreOffice (`pdf_utils.py`). На Android python-docx и LibreOffice недоступны, поэтому `core/export/qt_pdf.py` рисует PDF средствами Qt из тех же строк `compact_layout.py` — PDF на планшете совпадает с ПК.

**Снимок базы для отката.** `core/db_snapshot.py` делает полную копию SQLite через backup API (безопасно при открытом приложении) в папку `snapshots/` рядом с базой, хранит последние 5 (`KEEP_SNAPSHOTS`); откат пишет снимок обратно тем же API, без перезапуска приложения.

## 5. Android

- Точка входа — `android/main.py`. Готовит постоянную папку данных (`ANDROID_PRIVATE`), копирует туда базу из APK, если она там есть (сейчас базу в APK не кладут, планшет стартует пустым и получает данные синхронизацией), делает её рабочей папкой процесса и выставляет `DB_PATH`.
- Включает прокрутку пальцем во всех прокручиваемых виджетах и ставит `QT_SCALE_FACTOR` по умолчанию 0.85, чтобы панель кнопок влезала на планшете.
- Запускает то же главное окно `MainWindow` из `app_main.py` (копия десктопного `main.py`).
- Отличия: миграции через `core/android_migrations.py` вместо Alembic; файлы экспорта и бэкапа пишутся в «Загрузки/Cerastilo» без системного диалога (`ui/file_dialogs.py`, `core/utils/android_storage.py`), т.к. диалог Qt возвращает `content://`, который нельзя открыть `open()`; PDF рисуется Qt, а не LibreOffice.
- Признак Android в коде: `"ANDROID_ARGUMENT" in os.environ` (`core/utils/android_storage.is_android()`).

## 6. Важные соглашения

- `scheduler.db` в корне — рабочая база с личными данными: не коммитить и не портить. Копию для экспериментов называть НЕ `scheduler.db`: `migrations/env.py` подменяет URL `sqlite:///scheduler.db` на рабочую базу. Эксперименты с базой — только на копии в отдельной папке.
- `DatabaseManager` прогоняет миграции при каждом создании — открывать им можно только ту базу, которую не жалко изменить.
- `get_weeks_tree()` всегда возвращает dict `{год: {месяц: [недели]}}`.
- Признак Android — `"ANDROID_ARGUMENT" in os.environ`.
- Пароль SMTP хранится не в таблице `settings`, а в отдельном JSON рядом с базой (`core/secret_store.py`), чтобы не попадать в бэкапы и синхронизацию.
