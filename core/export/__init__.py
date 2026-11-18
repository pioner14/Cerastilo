# core/export/__init__.py
"""
Модуль экспорта расписания в DOCX.

Архитектура: Builder Pattern
- BaseTableBuilder — абстрактный базовый класс
- CompactTableBuilder — компактный формат (2 колонки)
- CompactV2TableBuilder — компактный современный формат (3 колонки)
- ModernTableBuilder — современный формат с цветными полосами
- FullModernTableBuilder — полный современный формат

См. spec://export/docx#architecture
"""

# Билдеры DOCX импортируются лениво: на Android нет python-docx, а
# compact_layout и fetcher (общие с PDF на Android) должны импортироваться.
_LAZY = {
    "BaseTableBuilder": "core.export.base_builder",
    "DocumentConfigurator": "core.export.configurator",
    "DataFetcher": "core.export.fetcher",
    "CompactTableBuilder": "core.export.compact_builder",
    "CompactV2TableBuilder": "core.export.compact_v2_builder",
    "ModernTableBuilder": "core.export.modern_builder",
    "FullModernTableBuilder": "core.export.full_modern_builder",
}

__all__ = list(_LAZY)


def __getattr__(name):
    if name in _LAZY:
        import importlib

        return getattr(importlib.import_module(_LAZY[name]), name)
    raise AttributeError(f"module 'core.export' has no attribute {name!r}")
