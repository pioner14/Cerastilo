# Migrations for NHJS_N

## Использование

### Создание новой миграции

```bash
# В среде nix-shell
nix-shell

# Создать новую миграцию
PYTHONPATH=. alembic -c migrations revision -m "description_of_change"

# Создать миграцию с автогенерацией (сравнение с БД)
PYTHONPATH=. alembic -c migrations revision --autogenerate -m "description"
```

### Применение миграций

```bash
# Применить все миграции
PYTHONPATH=. alembic -c migrations upgrade head

# Применить до конкретной ревизии
PYTHONPATH=. alembic -c migrations upgrade <revision_id>

# Откатить на одну миграцию
PYTHONPATH=. alembic -c migrations downgrade -1

# Откатить к конкретной ревизии
PYTHONPATH=. alembic -c migrations downgrade <revision_id>
```

### Проверка статуса

```bash
# Показать текущую ревизию
PYTHONPATH=. alembic -c migrations current

# Показать список миграций
PYTHONPATH=. alembic -c migrations history

# Показать детально
PYTHONPATH=. alembic -c migrations history -v
```

## Структура

```
migrations/
├── __init__.py
├── env.py              # Конфигурация окружения
├── script.py.mako      # Шаблон для миграций
├── versions/           # Файлы миграций
│   ├── 001_initial.py  # Начальная схема
│   └── ...
```

## Ревизии

| Revision | Description | Date |
|----------|-------------|------|
| 001_initial | Initial schema - все таблицы | 2026-03-11 |

## Интеграция с приложением

Миграции применяются автоматически при инициализации `DatabaseManager`:

```python
from core.database import DatabaseManager

db = DatabaseManager()  # Миграции применяются в _init_db()
```

Для ручного применения:

```bash
PYTHONPATH=. alembic -c migrations upgrade head
```

## Spec

See: `spec://database/migrations`
